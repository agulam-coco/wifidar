"""A pretend ESP32 for testing the bridge without hardware.

FakeESP32 behaves like a pyserial port: it has the same readline(),
write() and close() methods and speaks the same line-based protocol
as the real firmware. bridge.py can't tell the difference.

Protocol recap (one message per line):
    ESP32 -> laptop: JSON objects with a "type" of hello, scan, or track
    laptop -> ESP32: plain-text commands "TRACK <bssid> <channel> <label>" or "STOP"
"""

import json
import math
import random
import time

# Made-up networks. "base" is each network's average signal strength in dBm.
FAKE_NETWORKS = [
    {"ssid": "YourWifiName", "bssid": "a4:2b:b0:1c:9e:7f", "ch": 6, "base": -50},
    {"ssid": "CampusNet", "bssid": "10:aa:bb:cc:dd:01", "ch": 1, "base": -62},
    {"ssid": "CampusNet", "bssid": "10:aa:bb:cc:dd:02", "ch": 11, "base": -75},
    {"ssid": "Neighbor5", "bssid": "3c:11:22:33:44:55", "ch": 3, "base": -84},
    {"ssid": "", "bssid": "de:ad:be:ef:00:01", "ch": 9, "base": -70},  # hidden network
]

# How often the fake device "scans", in seconds. Roughly matches the real ESP32.
SCAN_INTERVAL_SEC = 1.5
TRACK_INTERVAL_SEC = 0.2

# Same smoothing the firmware uses: new = 0.7 * old + 0.3 * reading
SMOOTHING = 0.7


class FakeESP32:
    """Simulates the ESP32 firmware's serial output and command handling."""

    def __init__(self) -> None:
        self.mode = "scan"  # "scan" or "track", like the firmware's state machine
        self.track_bssid: str | None = None
        self.smoothed_rssi: float | None = None
        self.start_time = time.time()
        # Messages waiting to be read. The real firmware says hello on boot.
        self.pending_lines = [json.dumps({"type": "hello", "fw": "fake"})]

    # ----- pyserial-compatible interface -----

    def readline(self) -> bytes:
        """Return the next message as one line of bytes, like a serial port.

        Blocks for a moment to mimic how long a real scan takes.
        """
        if self.pending_lines:
            return self._encode_line(self.pending_lines.pop(0))

        if self.mode == "scan":
            time.sleep(SCAN_INTERVAL_SEC)
            message = self._make_scan_message()
        else:
            time.sleep(TRACK_INTERVAL_SEC)
            message = self._make_track_message()
        return self._encode_line(json.dumps(message))

    def write(self, data: bytes) -> None:
        """Handle a command sent from the laptop, like the firmware does."""
        line = data.decode().strip()
        if line.startswith("TRACK "):
            # Format: TRACK <bssid> <channel> <label...>; we only need the bssid
            bssid = line.split(" ", 3)[1]
            if any(net["bssid"] == bssid for net in FAKE_NETWORKS):
                self.track_bssid = bssid
                self.smoothed_rssi = None
                self.mode = "track"
        elif line == "STOP":
            self.mode = "scan"

    def close(self) -> None:
        """Nothing to clean up; exists so the bridge can treat this like a real port."""

    # ----- message builders -----

    def _make_scan_message(self) -> dict:
        """Build a 'scan' message with every fake network's current signal."""
        networks = [
            {
                "ssid": net["ssid"],
                "bssid": net["bssid"],
                "rssi": self._current_rssi(net),
                "ch": net["ch"],
                "open": False,
            }
            for net in FAKE_NETWORKS
        ]
        return {"type": "scan", "uptime_ms": self._uptime_ms(), "networks": networks}

    def _make_track_message(self) -> dict:
        """Build a 'track' message for the network currently being hunted."""
        net = next(n for n in FAKE_NETWORKS if n["bssid"] == self.track_bssid)
        raw = self._current_rssi(net)

        # Exponential moving average, same as the firmware
        if self.smoothed_rssi is None:
            self.smoothed_rssi = raw
        else:
            self.smoothed_rssi = SMOOTHING * self.smoothed_rssi + (1 - SMOOTHING) * raw

        # Map -90..-35 dBm to 0..100%, clamped
        percent = max(0, min(100, int((self.smoothed_rssi + 90) * 100 / 55)))

        return {
            "type": "track",
            "bssid": self.track_bssid,
            "rssi": round(self.smoothed_rssi),
            "raw_rssi": raw,
            "percent": percent,
            "found": True,
        }

    # ----- helpers -----

    def _current_rssi(self, net: dict) -> int:
        """Fake a signal that drifts up and down, like walking around a building."""
        elapsed = time.time() - self.start_time
        # Give each network its own stable offset so they don't all move together
        phase = int(net["bssid"].replace(":", ""), 16) % 10
        drift = 12 * math.sin(elapsed / 4 + phase)
        noise = random.uniform(-3, 3)
        return int(net["base"] + drift + noise)

    def _uptime_ms(self) -> int:
        return int((time.time() - self.start_time) * 1000)

    @staticmethod
    def _encode_line(text: str) -> bytes:
        """Serial ports deliver bytes ending in a newline."""
        return (text + "\n").encode()