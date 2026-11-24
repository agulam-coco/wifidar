"""wifidar bridge: connects the ESP32 to Foxglove.

Reads JSON lines from the ESP32 (or a fake one), hides other people's
network details, and publishes the data as Foxglove topics.

Topics published:
    /wifi/scan      JSON            every network from the latest scan, strongest first
    /wifi/radar     SceneUpdate     3D radar of the latest scan
    /tf             FrameTransform  places frame "base" (you) in "world"
    /wifi/tracked   JSON            live strength of the network being hunted
    /log            Log             human-readable events for Foxglove's Log panel

Usage:
    python bridge.py --fake                      record to recordings/<timestamp>.mcap
    python bridge.py --fake --no-record          live only
    python bridge.py --fake --record walk.mcap   record to a specific file
"""

import argparse
import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path

import foxglove
from foxglove.messages import Log, LogLevel, Timestamp
from foxglove.websocket import ServerListener

import config
import scene
from fake_esp32 import FakeESP32

# Recordings go in <repo>/recordings, no matter where the bridge is run from.
# __file__ is this script's path; .parent is bridge/, .parent.parent is the repo root.
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"

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
# The most recent status line, resent to viewers who connect late
last_status = "Bridge started"

def log_event(text: str, level: LogLevel = LogLevel.Info) -> None:
    """Print to the terminal, send to Foxglove's Log panel, and remember it."""
    global last_status
    last_status = text
    print(text)
    foxglove.log("/log", Log(
        timestamp=Timestamp.now(),
        level=level,
        message=text,
        name="wifidar",
    ))

class BridgeListener(ServerListener):
    """Reacts to events from connected Foxglove apps.

    The SDK calls these methods on its own thread, so they only set a flag.
    The main loop does the actual work, which keeps all logging on one thread.
    """

    def __init__(self) -> None:
        super().__init__()
        self.resend_status = threading.Event()

    def on_subscribe(self, client, channel) -> None:
        # Live viewers only get messages sent after they subscribe,
        # so when someone starts watching /log, replay the latest status.
        if channel.topic == "/log":
            self.resend_status.set()

# ---------- Message handlers ----------

def handle_scan(message: dict) -> None:
    """Clean up a scan and publish it on /wifi/scan."""
    networks = []
    for net in message["networks"]:
        net_id = private_id(net["bssid"])
        networks.append({
            "id": net_id,
            "label": display_label(net["ssid"], net_id),
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


def handle_track(message: dict) -> None:
    """Publish a tracking update on /wifi/tracked, with the BSSID anonymized."""
    foxglove.log("/wifi/tracked", {
        "id": private_id(message["bssid"]),
        "rssi": message["rssi"],
        "raw_rssi": message["raw_rssi"],
        "percent": message["percent"],
        "found": message["found"],
    })


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
    parser.add_argument("--record", type=Path, help="MCAP file to write (default: timestamped file in recordings/)")
    parser.add_argument("--no-record", action="store_true", help="stream live only, don't save a recording")
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
        print(f"Recording to {record_path}")

    device = FakeESP32()
    print("Using fake ESP32.")
    print(f"In Foxglove: Open connection > Foxglove WebSocket > ws://localhost:{config.WS_PORT}")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            if listener.resend_status.is_set():
                listener.resend_status.clear()
                log_event(last_status)
            raw = device.readline()
            if raw:
                handle_line(raw)
    except KeyboardInterrupt:
        print("\nStopping")
    finally:
        device.close()
        if recording is not None:
            # Writes the MCAP index. Skipping this can leave a broken file.
            recording.close()
            print(f"Saved {record_path}")
        server.stop()


if __name__ == "__main__":
    main()