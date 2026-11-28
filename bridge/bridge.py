"""wifidar bridge: connects the ESP32 to Foxglove.

Reads JSON lines from the ESP32 (or a fake one), hides other people's
network details, and publishes the data as Foxglove topics.

Topics published:
    /wifi/scan      JSON            every network from the latest scan, strongest first
    /wifi/radar     SceneUpdate     3D radar of the latest scan
    /tf             FrameTransform  places frame "base" (you) in "world"
    /wifi/tracked   JSON            live strength of the network being hunted
    /camera/webcam  CompressedImage camera frames, real or fake
    /esp32/screen   CompressedImage what the ESP32's screen is showing (digital twin)
    /log            Log             human-readable events for Foxglove's Log panel
    
Topics received (published by the Signal Hunter panel):
    /esp32/cmd      JSON            {"action": "track", "id": ...} or {"action": "stop"}

Usage:
    python bridge.py                             real ESP32, port found automatically
    python bridge.py --port /dev/cu.usbmodem101  real ESP32 on a specific port
    python bridge.py --fake                      simulated ESP32
    python bridge.py --no-record                 live only
    python bridge.py --record walk.mcap          record to a specific file
    python bridge.py --camera fake               add the fake webcam
    python bridge.py --camera webcam             add a real webcam
"""

import argparse
import hashlib
import json
import queue
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import foxglove
import serial
from foxglove.messages import CompressedImage, Log, LogLevel, Timestamp
from foxglove.websocket import Capability, ServerListener

import camera
import config
import scene
import screen
from esp32_serial import SerialESP32, find_esp32_port, list_port_names
from fake_esp32 import FakeESP32

# Recordings go in <repo>/recordings, no matter where the bridge is run from.
# __file__ is this script's path; .parent is bridge/, .parent.parent is the repo root.
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"

# Draws the ESP32 screen twin. Created once and reused, since it loads fonts.
screen_twin = screen.ScreenTwin()

# Private ID -> real details, from the latest scans. Only the bridge knows
# real BSSIDs. Foxglove only ever sees the private ID, so when the panel says
# "track net-3fa2c1", this is how the bridge finds the real BSSID and channel.
known_networks: dict[str, dict] = {}

# Commands from Foxglove, waiting for the main loop to send them to the ESP32
commands: "queue.Queue[dict]" = queue.Queue()


# ---------- Privacy helpers ----------

def private_id(bssid: str) -> str:
    """Turn a BSSID into a short, stable, anonymous ID like 'net-3fa2c1'."""
    digest = hashlib.sha1(bssid.lower().encode()).hexdigest()
    return "net-" + digest[:6]


def display_label(ssid: str, net_id: str) -> str:
    """Show the real name only for our own networks."""
    return ssid if ssid in config.MY_NETWORKS else net_id


# ---------- Recording ----------

def default_recording_path() -> Path:
    """A new timestamped file, e.g. recordings/wifidar_2026-11-23_22-15-04.mcap."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return RECORDINGS_DIR / f"wifidar_{stamp}.mcap"


# ---------- Logging ----------

# How many recent events to resend to a viewer who connects late
RESEND_LIMIT = 20

# Recent events as (timestamp, level, text). Oldest drops off automatically.
recent_events: deque[tuple[Timestamp, LogLevel, str]] = deque(maxlen=RESEND_LIMIT)


def publish_log(timestamp: Timestamp, level: LogLevel, text: str, name: str = "wifidar") -> None:
    """Send one line to Foxglove's Log panel."""
    foxglove.log("/log", Log(timestamp=timestamp, level=level, message=text, name=name))


def log_event(text: str, level: LogLevel = LogLevel.Info) -> None:
    """Print to the terminal, send to Foxglove, and remember it for late viewers."""
    timestamp = Timestamp.now()
    print(text)
    recent_events.append((timestamp, level, text))
    publish_log(timestamp, level, text)


def resend_recent_events() -> None:
    """Replay recent events for a viewer who just started watching /log.

    Live viewers only get messages sent after they subscribe, so this
    catches them up on startup events. Resent copies keep their original
    timestamps, are labeled 'wifidar (resent)', and aren't printed again.
    They also land in the recording, which is why they're labeled.
    """
    for timestamp, level, text in list(recent_events):
        publish_log(timestamp, level, text, name="wifidar (resent)")


class BridgeListener(ServerListener):
    """Reacts to events from connected Foxglove apps.

    The SDK calls these methods on its own thread, so they only set a flag.
    The main loop does the actual work.
    """

    def __init__(self) -> None:
        super().__init__()
        self.resend_events = threading.Event()
        # Client channel ID -> topic name, for topics a Foxglove app advertised
        self.client_topics: dict[int, str] = {}

    def on_subscribe(self, client, channel) -> None:
        # Live viewers only get messages sent after they subscribe,
        # so when someone starts watching /log, replay recent events.
        if channel.topic == "/log":
            self.resend_events.set()
    
    def on_client_advertise(self, client, channel) -> None:
        # A panel announced it will publish on a topic. Remember the
        # channel's ID so we know which topic later messages belong to.
        self.client_topics[channel.id] = channel.topic

    def on_client_unadvertise(self, client, client_channel_id: int) -> None:
        self.client_topics.pop(client_channel_id, None)

    def on_message_data(self, client, client_channel_id: int, data: bytes) -> None:
        # A panel published a message. Only accept commands, and don't touch
        # the serial port here: queue it for the main loop instead.
        if self.client_topics.get(client_channel_id) != config.COMMAND_TOPIC:
            return
        try:
            commands.put(json.loads(data))
        except ValueError:
            pass  # not valid JSON, ignore it

# ---------- Screen twin ----------

def publish_screen(png: bytes) -> None:
    """Publish a drawing of the ESP32's screen on /esp32/screen."""
    foxglove.log(config.SCREEN_TOPIC, CompressedImage(
        timestamp=Timestamp.now(),
        frame_id="esp32_screen",
        data=png,
        format="png",
    ))
    
# ---------- Message handlers ----------

def handle_scan(message: dict) -> None:
    """Clean up a scan and publish it on /wifi/scan."""
    networks = []
    for net in message["networks"]:
        net_id = private_id(net["bssid"])
        label = display_label(net["ssid"], net_id)
        known_networks[net_id] = {"bssid": net["bssid"], "ch": net["ch"], "label": label}
        networks.append({
            "id": net_id,
            "label": label,
            "rssi": net["rssi"],
            "ch": net["ch"],
            "open": net["open"],
            "mine": net["ssid"] in config.MY_NETWORKS,
        })
    networks.sort(key=lambda n: n["rssi"], reverse=True)

    foxglove.log("/wifi/scan", {
        "count": len(networks),
        "strongest_rssi": networks[0]["rssi"] if networks else None,
        "networks": networks,
    })

    # Draw the radar. The transform tells the 3D panel where "base" is.
    foxglove.log("/tf", scene.base_transform())
    foxglove.log("/wifi/radar", scene.build_scene(networks))
    
    # The real screen shows the network count in scan mode
    publish_screen(screen_twin.scan_screen(network_count=len(networks)))


def handle_track(message: dict) -> None:
    """Publish a tracking update on /wifi/tracked, with the BSSID anonymized."""
    net_id = private_id(message["bssid"])
    label = known_networks.get(net_id, {}).get("label", net_id)  # fall back to the ID
    
    foxglove.log("/wifi/tracked", {
        "id": net_id,
        "label": label,
        "rssi": message["rssi"],
        "raw_rssi": message["raw_rssi"],
        "percent": message["percent"],
        "found": message["found"],
    })

    # The real screen shows the finder ring in track mode
    publish_screen(screen_twin.finder_screen(
        rssi=message["rssi"],
        percent=message["percent"],
        label=label,
        found=message["found"],
    ))

def send_queued_commands(device) -> None:
    """Send any commands from Foxglove down to the ESP32."""
    while not commands.empty():
        command = commands.get()
        action = command.get("action")

        if action == "track":
            net_id = command.get("id", "")
            net = known_networks.get(net_id)
            if net is None:
                log_event(f"Can't track {net_id}: not in a recent scan", LogLevel.Warning)
                continue
            device.write(f'TRACK {net["bssid"]} {net["ch"]} {net["label"]}\n'.encode())
            foxglove.log("/esp32/cmd_log", {"action": "track", "id": net_id, "label": net["label"]})
            log_event(f'Tracking {net["label"]} on channel {net["ch"]}')

        elif action == "stop":
            device.write(b"STOP\n")
            foxglove.log("/esp32/cmd_log", {"action": "stop"})
            log_event("Back to scan mode")

        else:
            log_event(f"Unknown command: {command}", LogLevel.Warning)
            
def handle_line(raw: bytes) -> None:
    """Parse one line from the ESP32 and route it by message type."""
    try:
        message = json.loads(raw)
    except ValueError:
        # Half-received lines or boot noise from the ESP32. Safe to skip.
        return

    kind = message.get("type")
    if kind == "hello":
        log_event(f"ESP32 connected, firmware {message.get('fw')}")
    elif kind == "scan":
        handle_scan(message)
    elif kind == "track":
        handle_track(message)
    else:
        log_event(f"Unknown message type: {kind}", LogLevel.Warning)


# ---------- Device ----------

def open_device(args: argparse.Namespace) -> FakeESP32 | SerialESP32:
    """Open the fake or real ESP32, with clear errors if the real one isn't there."""
    if args.fake:
        log_event("Using fake ESP32")
        return FakeESP32()

    port = args.port or find_esp32_port()
    if port is None:
        ports = ", ".join(list_port_names()) or "none"
        raise SystemExit(
            f"No ESP32 found (ports on this computer: {ports}). "
            "Plug it in, pass --port, or use --fake."
        )

    try:
        device = SerialESP32(port)
    except serial.SerialException as error:
        raise SystemExit(
            f"Couldn't open {port}: {error}\n"
            "If idf.py monitor is running, close it first (Ctrl+])."
        )

    log_event(f"Connected to ESP32 on {port}")
    return device


# ---------- Main ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="wifidar bridge")
    parser.add_argument("--fake", action="store_true", help="use a simulated ESP32")
    parser.add_argument("--port", help="serial port of the real ESP32 (found automatically if omitted)")
    parser.add_argument("--record", type=Path,
                        help="MCAP file to write (default: timestamped file in recordings/)")
    parser.add_argument("--no-record", action="store_true",
                        help="stream live only, don't save a recording")
    parser.add_argument("--camera", choices=["none", "fake", "webcam"], default="none",
                        help="camera source to publish on /camera/webcam")
    parser.add_argument("--camera-index", type=int, default=0,
                        help="which webcam to open (0 is usually the built-in one)")
    args = parser.parse_args()

    # Start the WebSocket server the Foxglove app connects to
    listener = BridgeListener()
    server = foxglove.start_server(
        name="wifidar",
        port=config.WS_PORT,
        capabilities=[Capability.ClientPublish],  # let Foxglove send messages back
        supported_encodings=["json"],             # ...encoded as JSON
        server_listener=listener,
    )
    # Open the recording. From here on, every foxglove.log() call is also saved to the file.
    recording = None
    if not args.no_record:
        record_path = args.record or default_recording_path()
        record_path.parent.mkdir(parents=True, exist_ok=True)
        recording = foxglove.open_mcap(str(record_path), allow_overwrite=True)
        log_event(f"Recording to {record_path.name}")

    # Start the camera on its own thread so it never waits on the ESP32
    camera_thread = None
    if args.camera != "none":
        source = camera.FakeWebcam() if args.camera == "fake" else camera.Webcam(args.camera_index)
        camera_thread = camera.CameraPublisher(source)
        camera_thread.start()
        log_event(f"Camera started: {args.camera}")

    device = open_device(args)
    print(f"In Foxglove: Open connection > Foxglove WebSocket > ws://localhost:{config.WS_PORT}")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            if listener.resend_events.is_set():
                listener.resend_events.clear()
                resend_recent_events()
            send_queued_commands(device)
            raw = device.readline()
            if raw:
                handle_line(raw)
    except KeyboardInterrupt:
        print("\nStopping")
    except serial.SerialException as error:
        # The ESP32 was unplugged or reset mid-run. Stop cleanly so the recording still saves.
        log_event(f"Lost connection to the ESP32: {error}", LogLevel.Error)
    
    finally:
        # Stop the camera before closing the recording, so no frames
        # get logged after the file is closed
        if camera_thread is not None:
            camera_thread.stop()
        device.close()
        if recording is not None:
            # Writes the MCAP index. Skipping this can leave a broken file.
            recording.close()
            print(f"Saved {record_path}")
        server.stop()


if __name__ == "__main__":
    main()
