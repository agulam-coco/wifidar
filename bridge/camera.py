"""Camera sources and the thread that publishes their frames to Foxglove.

Two sources share the same interface, read() -> JPEG bytes and close():
    FakeWebcam   a deterministic test pattern, no hardware needed
    Webcam       a real USB webcam through OpenCV

CameraPublisher runs a source on its own thread and publishes frames as
CompressedImage messages, so the camera never waits on the ESP32.
"""

import io
import math
import threading
import time

import foxglove
from foxglove.messages import CompressedImage, Timestamp
from PIL import Image, ImageDraw, ImageFont

import config

# The fake camera produces frames at the same rate a real webcam would
FAKE_CAMERA_FPS = 30

# Fake pattern geometry
ORBIT_RADIUS = 120         # pixels from center to the moving dot
ORBIT_PERIOD_SEC = 4       # seconds for one trip around the circle
DOT_RADIUS = 14

# Colors are (red, green, blue), each 0 to 255
BACKGROUND = (24, 26, 32)
GRID = (45, 48, 58)
GUIDE = (90, 95, 110)
TEXT = (230, 230, 235)
DOT = (255, 80, 60)
# Classic test-pattern color bars: white, yellow, cyan, green, magenta, red, blue
COLOR_BARS = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
              (255, 0, 255), (255, 0, 0), (0, 0, 255)]


def encode_jpeg(image: Image.Image) -> bytes:
    """Compress a Pillow image to JPEG bytes."""
    buffer = io.BytesIO()  # an in-memory file
    image.save(buffer, format="JPEG", quality=config.CAMERA_JPEG_QUALITY)
    return buffer.getvalue()


# ---------- Sources ----------

class FakeWebcam:
    """A test pattern where only a few things change each frame.

    The base image (grid, color bars, circle, title) is drawn once.
    Each frame copies it and adds a moving dot, a frame counter, and a
    time label. Everything depends on the frame number, not the clock,
    so frame N always looks the same. That makes dropped or delayed
    frames easy to spot.
    """

    def __init__(self) -> None:
        self.width = config.CAMERA_WIDTH
        self.height = config.CAMERA_HEIGHT
        self.frame_number = 0
        self.font = ImageFont.load_default(size=20)
        self.base_image = self._draw_base_image()

    def read(self) -> bytes:
        """Wait one camera frame, then return the next frame as JPEG bytes."""
        time.sleep(1 / FAKE_CAMERA_FPS)

        frame = self.base_image.copy()
        draw = ImageDraw.Draw(frame)
        elapsed = self.frame_number / FAKE_CAMERA_FPS

        # Dot moving around the circle, positioned by frame number
        angle = 2 * math.pi * (elapsed / ORBIT_PERIOD_SEC)
        x = self.width / 2 + ORBIT_RADIUS * math.cos(angle)
        y = self.height / 2 + ORBIT_RADIUS * math.sin(angle)
        draw.ellipse((x - DOT_RADIUS, y - DOT_RADIUS, x + DOT_RADIUS, y + DOT_RADIUS), fill=DOT)

        # Frame counter and elapsed time in the bottom-left corner
        draw.text((16, self.height - 60), f"frame {self.frame_number:06d}", fill=TEXT, font=self.font)
        draw.text((16, self.height - 34), f"t = {elapsed:7.2f} s", fill=TEXT, font=self.font)

        self.frame_number += 1
        return encode_jpeg(frame)

    def close(self) -> None:
        """Nothing to release; exists so it matches Webcam."""

    def _draw_base_image(self) -> Image.Image:
        """Draw the parts of the pattern that never change."""
        image = Image.new("RGB", (self.width, self.height), BACKGROUND)
        draw = ImageDraw.Draw(image)

        # Grid every 40 pixels
        for x in range(0, self.width, 40):
            draw.line((x, 0, x, self.height), fill=GRID)
        for y in range(0, self.height, 40):
            draw.line((0, y, self.width, y), fill=GRID)

        # Color bars across the top
        bar_width = self.width // len(COLOR_BARS)
        for i, color in enumerate(COLOR_BARS):
            draw.rectangle((i * bar_width, 0, (i + 1) * bar_width, 24), fill=color)

        # The circle the dot travels around, with a crosshair at the center
        cx, cy = self.width // 2, self.height // 2
        draw.ellipse((cx - ORBIT_RADIUS, cy - ORBIT_RADIUS, cx + ORBIT_RADIUS, cy + ORBIT_RADIUS),
                     outline=GUIDE, width=2)
        draw.line((cx - 10, cy, cx + 10, cy), fill=GUIDE)
        draw.line((cx, cy - 10, cx, cy + 10), fill=GUIDE)

        draw.text((16, 36), "wifidar FAKE CAM", fill=TEXT, font=self.font)
        return image


class Webcam:
    """A real USB webcam, read through OpenCV."""

    def __init__(self, index: int = 0) -> None:
        # Imported here so the fake camera works even if OpenCV isn't installed
        import cv2

        self._cv2 = cv2
        self._capture = cv2.VideoCapture(index)
        if not self._capture.isOpened():
            raise RuntimeError(
                f"Couldn't open camera {index}. Try another --camera-index, "
                "and check macOS camera permissions for your terminal."
            )
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)

    def read(self) -> bytes | None:
        """Wait for the next frame and return it as JPEG bytes, or None on a bad read."""
        ok, frame = self._capture.read()
        if not ok:
            return None
        ok, jpeg = self._cv2.imencode(
            ".jpg", frame, [self._cv2.IMWRITE_JPEG_QUALITY, config.CAMERA_JPEG_QUALITY]
        )
        return jpeg.tobytes() if ok else None

    def close(self) -> None:
        """Release the camera so other apps can use it."""
        self._capture.release()


# ---------- Publisher ----------

class CameraPublisher(threading.Thread):
    """Reads a camera source on its own thread and publishes frames to Foxglove.

    Reads every frame so it always has the newest one, but only publishes
    CAMERA_PUBLISH_FPS frames per second to keep recordings small.
    """

    def __init__(self, source: FakeWebcam | Webcam) -> None:
        # daemon=True: if the main program exits, this thread won't keep it alive
        super().__init__(name="camera", daemon=True)
        self.source = source
        # Not named _stop: threading.Thread already has an internal _stop method
        self._stop_event = threading.Event()

    def run(self) -> None:
        """The thread's main loop. Called by start(), never directly."""
        period = 1 / config.CAMERA_PUBLISH_FPS
        next_publish = 0.0
        try:
            while not self._stop_event.is_set():
                jpeg = self.source.read()
                if jpeg is None:
                    time.sleep(0.1)  # bad read, wait a moment and try again
                    continue

                now = time.monotonic()
                if now >= next_publish:
                    foxglove.log(config.CAMERA_TOPIC, CompressedImage(
                        timestamp=Timestamp.now(),
                        frame_id="webcam",
                        data=jpeg,
                        format="jpeg",
                    ))
                    next_publish = now + period
        finally:
            # The thread owns the source, so it releases it when it's done
            self.source.close()

    def stop(self) -> None:
        """Ask the thread to finish, and wait for it."""
        self._stop_event.set()
        self.join(timeout=2)