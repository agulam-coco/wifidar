/*
 * protocol.h: the messages the ESP32 sends to the laptop.
 *
 * Every message is one line of JSON, in the same format as
 * bridge/fake_esp32.py, so the bridge can't tell real from fake.
 */
#pragma once

#include <stdint.h>

#include "esp_wifi_types.h"
#include "finder.h"

/** Sent once at startup: {"type":"hello","fw":"0.1.0"} */
void protocol_send_hello(void);

/** Sent after every full scan, with one entry per network found. */
void protocol_send_scan(const wifi_ap_record_t *records, uint16_t count);

/** Sent after every finder-mode scan, with the smoothed reading. */
void protocol_send_track(const uint8_t bssid[6], const finder_reading_t *reading);