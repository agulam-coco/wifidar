# wifidar firmware

ESP-IDF v6 firmware for the ESP32-2424S012C (ESP32-C3 with a round GC9A01 display).

Scans Wi-Fi and sends each scan to the laptop as one line of JSON over the
board's built-in USB, in the same format as `bridge/fake_esp32.py`.

## Build and flash

```bash
idf.py set-target esp32c3
idf.py build
idf.py -p PORT flash monitor
```

Exit the monitor with `Ctrl+]`.

## Settings

`idf.py menuconfig` > **wifidar**:

- **Most networks reported per scan** (default 30)