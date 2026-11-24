"""Digital twin of the ESP32's round screen.

The ESP32 draws its screen from data the bridge already has (mode,
network count, signal strength, label). So instead of streaming the
real framebuffer over serial (about 10 seconds per frame at 115200
baud), the bridge redraws the same screen here and publishes it.

The layout mirrors the firmware's drawScanScreen() and
drawFinderScreen(). If one changes, change the other.

Run this file directly to save sample images of both screens:
    python screen.py
"""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

import config

# The real screen is 240 x 240 pixels (GC9A01 round display)
SIZE = 240
CENTER = SIZE // 2

# Draw at 3x size, then shrink. Pillow doesn't smooth the edges of
# circles and arcs, so shrinking a big drawing is how we get smooth edges.
SCALE = 3

# Colors (red, green, blue), matching TFT_eSPI's built-in colors
BLACK = (0, 0, 0)
BEZEL = (40, 40, 44)          # area outside the round glass
WHITE = (255, 255, 255)
LIGHT_GREY = (198, 195, 198)  # TFT_LIGHTGREY
DARK_GREY = (123, 125, 123)   # TFT_DARKGREY
DARK_GREEN = (0, 125, 0)      # TFT_DARKGREEN
GREEN = (0, 255, 0)           # TFT_GREEN


def rssi_to_percent(rssi: float) -> int:
    """Map RSSI to 0..100 for the finder ring, same as the firmware."""
    p = (rssi - config.RSSI_WEAK) * 100 / (config.RSSI_STRONG - config.RSSI_WEAK)
    return int(max(0, min(100, p)))


def strength_color(percent: int) -> tuple[int, int, int]:
    """0% red, 50% yellow, 100% green, same as the firmware's strengthColor()."""
    if percent < 50:
        return (255, round(percent * 255 / 50), 0)
    return (round(255 - (percent - 50) * 255 / 50), 255, 0)


class ScreenTwin:
    """Draws what the ESP32's screen is showing right now."""

    def __init__(self) -> None:
        # Font sizes are multiplied by SCALE because we draw at 3x
        self.big = ImageFont.load_default(size=48 * SCALE)
        self.medium = ImageFont.load_default(size=26 * SCALE)
        self.small = ImageFont.load_default(size=16 * SCALE)

    # ----- the two screens -----

    def scan_screen(self, network_count: int) -> bytes:
        """SCAN mode: two radar rings, the network count, and 'SCAN'."""
        image, draw = self._blank()
        self._circle(draw, 90, DARK_GREEN)
        self._circle(draw, 55, DARK_GREEN)
        self._text(draw, str(network_count), CENTER - 8, self.big, WHITE)
        self._text(draw, "networks", CENTER + 28, self.small, LIGHT_GREY)
        self._text(draw, "SCAN", 200, self.small, GREEN)
        return self._finish(image)

    def finder_screen(self, rssi: int, percent: int, label: str, found: bool) -> bytes:
        """TRACK mode: a ring that fills with signal strength, plus dBm and the label."""
        image, draw = self._blank()

        # Gray track from 30 to 330 degrees (gap at the bottom),
        # then the colored fill on top, sized by percent
        self._arc(draw, 30, 330, DARK_GREY)
        if percent > 0:
            self._arc(draw, 30, 30 + 300 * percent / 100, strength_color(percent))

        self._text(draw, f"{rssi} dBm", CENTER - 8, self.medium, WHITE)
        self._text(draw, label if found else "searching...", CENTER + 24, self.small, LIGHT_GREY)
        return self._finish(image)

    # ----- drawing helpers (all coordinates in real 240px screen units) -----

    def _blank(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        """A bezel-colored square with the black round glass in the middle."""
        image = Image.new("RGB", (SIZE * SCALE, SIZE * SCALE), BEZEL)
        draw = ImageDraw.Draw(image)
        draw.ellipse((0, 0, SIZE * SCALE - 1, SIZE * SCALE - 1), fill=BLACK)
        return image, draw

    def _circle(self, draw: ImageDraw.ImageDraw, radius: int, color: tuple) -> None:
        """Thin circle outline centered on the screen."""
        r = radius * SCALE
        c = CENTER * SCALE
        draw.ellipse((c - r, c - r, c + r, c + r), outline=color, width=SCALE)

    def _arc(self, draw: ImageDraw.ImageDraw, start: float, end: float, color: tuple) -> None:
        """Thick ring segment between radius 100 and 115, in firmware angle units."""
        outer = 115 * SCALE
        c = CENTER * SCALE
        # Firmware angles start at 6 o'clock, Pillow's at 3 o'clock.
        # Both go clockwise, so adding 90 converts between them.
        draw.arc((c - outer, c - outer, c + outer, c + outer),
                 start=start + 90, end=end + 90, fill=color, width=15 * SCALE)

    def _text(self, draw: ImageDraw.ImageDraw, text: str, y: int,
              font: ImageFont.FreeTypeFont, color: tuple) -> None:
        """Text centered horizontally on the screen and vertically on y."""
        # anchor="mm" means (x, y) is the middle of the text,
        # same idea as setTextDatum(MC_DATUM) in the firmware
        draw.text((CENTER * SCALE, y * SCALE), text, font=font, fill=color, anchor="mm")

    def _finish(self, image: Image.Image) -> bytes:
        """Shrink to the real size (smoothing the edges) and encode as PNG."""
        small = image.resize((SIZE, SIZE), Image.LANCZOS)
        buffer = BytesIO()
        small.save(buffer, format="PNG")
        return buffer.getvalue()


if __name__ == "__main__":
    twin = ScreenTwin()
    with open("screen_scan.png", "wb") as f:
        f.write(twin.scan_screen(network_count=14))
    with open("screen_track.png", "wb") as f:
        f.write(twin.finder_screen(rssi=-48, percent=rssi_to_percent(-48),
                                   label="YourWifiName", found=True))
    print("Saved screen_scan.png and screen_track.png")