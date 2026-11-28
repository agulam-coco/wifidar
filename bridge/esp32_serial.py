"""The real ESP32, over USB serial.

SerialESP32 has the same readline(), write() and close() methods as
FakeESP32, so bridge.py works with either one.

Two things the fake never had to deal with:
    - lines can arrive in pieces, so bytes are buffered until a full
      line (ending in a newline) is ready
    - opening the port can reset the ESP32-C3, so DTR and RTS are kept off
"""

import serial
from serial.tools import list_ports

import config

# How long one read waits for data before returning, in seconds.
# Short, so the bridge's main loop keeps checking for commands.
READ_TIMEOUT_SEC = 0.1

# If this many bytes pile up without a newline, something is wrong (noise,
# or the wrong device), so throw them away instead of growing forever.
MAX_LINE_BYTES = 16384


def find_esp32_port() -> str | None:
    """Return the port of the first connected Espressif device, or None."""
    for port in list_ports.comports():
        if port.vid == config.ESPRESSIF_USB_VID:
            return port.device
    return None


def list_port_names() -> list[str]:
    """Every serial port on this computer, for error messages."""
    return [port.device for port in list_ports.comports()]


class SerialESP32:
    """The real ESP32 over USB serial, with the same interface as FakeESP32."""

    def __init__(self, port: str) -> None:
        # Configure first, open last, so DTR and RTS are already off when
        # the port opens. On the ESP32-C3's built-in USB those two signals
        # control reset and boot mode, and leaving them on can reset the chip
        # or leave it stuck waiting to be flashed.
        self._serial = serial.Serial()
        self._serial.port = port
        self._serial.baudrate = config.SERIAL_BAUD
        self._serial.timeout = READ_TIMEOUT_SEC
        self._serial.dtr = False
        self._serial.rts = False
        self._serial.open()

        # Bytes received but not yet returned as a full line
        self._buffer = bytearray()

    def readline(self) -> bytes:
        """Return the next complete line, or b"" if one hasn't fully arrived yet.

        Waits at most READ_TIMEOUT_SEC for new data.
        """
        newline = self._buffer.find(b"\n")
        if newline == -1:
            # Read everything that's waiting, or wait briefly for at least 1 byte
            self._buffer.extend(self._serial.read(self._serial.in_waiting or 1))
            newline = self._buffer.find(b"\n")

        if newline == -1:
            if len(self._buffer) > MAX_LINE_BYTES:
                self._buffer.clear()  # garbage with no newline, drop it
            return b""

        line = bytes(self._buffer[: newline + 1])
        del self._buffer[: newline + 1]
        return line

    def write(self, data: bytes) -> None:
        """Send a command to the ESP32."""
        self._serial.write(data)

    def close(self) -> None:
        """Release the port so other programs (like idf.py monitor) can use it."""
        self._serial.close()