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

Usage:
    python bridge.py --fake                      record to recordings/<timestamp>.mcap
    python bridge.py --fake --no-record          live only
    python bridge.py --fake --record walk.mcap   record to a specific file
    python bridge.py --fake --camera fake        add the fake webcam
    python bridge.py --fake --camera webcam      add a real webcam
"""

import argparse
import hashlib
import json
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import foxglove
from foxglove.messages import CompressedImage, Log, LogLevel, Timestamp
from foxglove.websocket import ServerListener

import camera
import config
import scene
import screen
from fake_esp32 import FakeESP32

# Recordings go in <repo>/recordings, no matter where the bridge is run from.
# __file__ is this script's path; .parent is bridge/, .parent.parent is the repo root.
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"

# Draws the ESP32 screen twin. Created once and reused, since it loads fonts.
screen_twin = screen.ScreenTwin()

# Private ID -> display label, from the latest scans. Tracking messages only
# carry a BSSID, so this is how the finder screen knows what name to show.
network_labels: dict[str, str] = {}


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

    def on_subscribe(self, client, channel) -> None:
        # Live viewers only get messages sent after they subscribe,
        # so when someone starts watching /log, replay recent events.
        if channel.topic == "/log":
            self.resend_events.set()

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
        network_labels[net_id] = label
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
    label = network_labels.get(net_id, net_id)  # fall back to the ID if never scanned

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


# ---------- Main ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="wifidar bridge")
    parser.add_argument("--fake", action="store_true", help="use a simulated ESP32")
    parser.add_argument("--record", type=Path,
                        help="MCAP file to write (default: timestamped file in recordings/)")
    parser.add_argument("--no-record", action="store_true",
                        help="stream live only, don't save a recording")
    parser.add_argument("--camera", choices=["none", "fake", "webcam"], default="none",
                        help="camera source to publish on /camera/webcam")
    parser.add_argument("--camera-index", type=int, default=0,
                        help="which webcam to open (0 is usually the built-in one)")
    args = parser.parse_args()

    if not args.fake:
        # Real hardware support comes in Step 11
        raise SystemExit("Only --fake is supported so far.")

    # Start the WebSocket server the Foxglove app connects to
    listener = BridgeListener()
    server = foxglove.start_server(name="wifidar", port=config.WS_PORT, server_listener=listener)

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

    device = FakeESP32()
    log_event("Using fake ESP32")
    print(f"In Foxglove: Open connection > Foxglove WebSocket > ws://localhost:{config.WS_PORT}")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            if listener.resend_events.is_set():
                listener.resend_events.clear()
                resend_recent_events()
            raw = device.readline()
            if raw:
                handle_line(raw)
    except KeyboardInterrupt:
        print("\nStopping")
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
