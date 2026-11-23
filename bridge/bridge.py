"""wifidar bridge: connects the ESP32 to Foxglove.

Reads JSON lines from the ESP32 (or a fake one), hides other people's
network details, and publishes the data as Foxglove topics.

Topics published:
    /wifi/scan      JSON   every network from the latest scan, strongest first
    /wifi/tracked   JSON   live strength of the network being hunted
    /log            Log    human-readable events for Foxglove's Log panel

Usage:
    python bridge.py --fake
"""

import argparse
import hashlib
import json
import threading

import foxglove
from foxglove.messages import Log, LogLevel
from foxglove.websocket import ServerListener

import config
from fake_esp32 import FakeESP32

# ---------- Privacy helpers ----------

def private_id(bssid: str) -> str:
    """Turn a BSSID into a short, stable, anonymous ID like 'net-3fa2c1'."""
    digest = hashlib.sha1(bssid.lower().encode()).hexdigest()
    return "net-" + digest[:6]


def display_label(ssid: str, net_id: str) -> str:
    """Show the real name only for our own networks."""
    return ssid if ssid in config.MY_NETWORKS else net_id


# ---------- Logging ----------
# The most recent status line, resent to viewers who connect late
last_status = "Bridge started"

def log_event(text: str, level: LogLevel = LogLevel.Info) -> None:
    """Print to the terminal, send to Foxglove's Log panel, and remember it."""
    global last_status
    last_status = text
    print(text)
    foxglove.log("/log", Log(level=level, message=text, name="wifidar"))

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
    args = parser.parse_args()

    if not args.fake:
        # Real hardware support comes in Step 9
        raise SystemExit("Only --fake is supported so far.")

    # Start the WebSocket server the Foxglove app connects to
    listener = BridgeListener()
    server = foxglove.start_server(name="wifidar", port=config.WS_PORT, server_listener=listener)

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
        server.stop()


if __name__ == "__main__":
    main()