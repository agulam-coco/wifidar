/*
 * scanner.h: starts the Wi-Fi driver and runs scans.
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>

#include "esp_wifi_types.h"

/** Start NVS and the Wi-Fi driver in station mode. Call once at boot. */
void scanner_init(void);

/**
 * Scan every channel and copy the results into records.
 * Blocks until the scan finishes (a couple of seconds).
 * Returns how many networks were stored (at most max), or 0 on failure.
 */
uint16_t scanner_scan_all(wifi_ap_record_t *records, uint16_t max);

/**
 * Look for one access point on one channel, using a short scan.
 * Returns true and sets *rssi_out if it was found.
 */
bool scanner_scan_one(const uint8_t bssid[6], uint8_t channel, int *rssi_out);