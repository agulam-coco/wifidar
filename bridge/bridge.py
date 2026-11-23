"""wifidar bridge: connects the ESP32 to Foxglove.

Current stage: reads messages from a (fake) ESP32 and prints them.
Foxglove streaming is added in the next step.

Usage:
    python bridge.py --fake
"""

import argparse
import json

from fake_esp32 import FakeESP32


def handle_line(raw: bytes) -> None:
    """Parse one line from the ESP32 and route it by message type."""
    try:
        message = json.loads(raw)
    except ValueError:
        # Half-received lines or boot noise from the ESP32. Safe to skip.
        return

    kind = message.get("type")
    if kind == "hello":
        print(f"ESP32 connected, firmware {message.get('fw')}")
    elif kind == "scan":
        print_scan(message)
    elif kind == "track":
        print(f"tracking {message['bssid']}: {message['rssi']} dBm ({message['percent']}%)")
    else:
        print(f"Unknown message type: {kind}")


def print_scan(message: dict) -> None:
    """Print a scan as a small table, strongest network first."""
    networks = sorted(message["networks"], key=lambda n: n["rssi"], reverse=True)
    print(f"\nScan at {message['uptime_ms'] / 1000:.1f}s: {len(networks)} networks")
    for net in networks:
        name = net["ssid"] or "(hidden)"
        print(f"  {net['rssi']:>4} dBm  ch {net['ch']:>2}  {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="wifidar bridge")
    parser.add_argument("--fake", action="store_true", help="use a simulated ESP32")
    args = parser.parse_args()

    if not args.fake:
        # Stand in for now until we support real hardware
        raise SystemExit("Only --fake is supported so far.")

    device = FakeESP32()
    print("Using fake ESP32. Press Ctrl+C to stop.")

    try:
        while True:
            raw = device.readline()
            if raw:
                handle_line(raw)
    except KeyboardInterrupt:
        print("\nStopping")
    finally:
        device.close()


if __name__ == "__main__":
    main()
