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

# --- 3D radar ---
# RSSI range mapped to 0..1 strength. Stronger than STRONG or weaker
# than WEAK gets clamped to the ends.
RSSI_WEAK = -90
RSSI_STRONG = -35

# Radar geometry, in meters inside Foxglove's 3D panel
RADAR_MIN_DIST = 1.0   # where the strongest networks sit
RADAR_MAX_DIST = 6.0   # where the weakest networks sit
BAR_MAX_HEIGHT = 2.5   # height of a full-strength bar
BAR_WIDTH = 0.35

# 2.4 GHz Wi-Fi has channels 1 to 13; each gets one slice of the circle
CHANNELS = 13

# Seconds a bar survives without a fresh scan before Foxglove removes it.
# Should be a few times longer than one scan.
BAR_LIFETIME_SEC = 6

# --- Camera ---
CAMERA_TOPIC = "/camera/webcam"
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
# Frames per second actually published to Foxglove (the camera itself runs faster)
CAMERA_PUBLISH_FPS = 5
# JPEG quality from 1 (tiny, blocky) to 95 (big, sharp). 70 is a good balance.
CAMERA_JPEG_QUALITY = 70

# --- ESP32 screen twin ---
SCREEN_TOPIC = "/esp32/screen"

# --- Commands from Foxglove ---
# Topic the Signal Hunter panel publishes commands on
COMMAND_TOPIC = "/esp32/cmd"