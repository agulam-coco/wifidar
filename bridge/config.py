"""Settings for the wifidar bridge.

Every tunable number lives here, so behavior can be changed without
touching the logic in the other files.
"""

# --- Serial connection to the ESP32 ---
# Must match Serial.begin() in the firmware
SERIAL_BAUD = 115200

# --- Foxglove connection ---
# Foxglove's default WebSocket port. The app connects to ws://localhost:<WS_PORT>
WS_PORT = 8765

# --- Privacy ---
# Networks shown by their real name. Every other network is shown as a
# hashed ID like "net-3fa2c1", so recordings never expose other people's info.
# Put your own network name(s) here.
MY_NETWORKS = {"YourWifiName"}
