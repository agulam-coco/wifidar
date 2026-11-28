/*
 * display.h: the round GC9A01 screen.
 *
 * Two screens, matching the screen twin in bridge/screen.py:
 *     scan    two radar rings, the network count, and "SCAN"
 *     finder  a ring that fills with signal strength, the dBm, and the label
 *
 * These functions take the LVGL lock themselves, so any task can call them.
 */
#pragma once

#include <stdint.h>

#include "finder.h"

/** Set up the SPI bus, panel, backlight, and LVGL, and build both screens. Call once. */
void display_init(void);

/** Show the scan screen with this many networks. */
void display_show_scan(uint16_t network_count);

/** Show the finder screen with this reading and network label. */
void display_show_finder(const finder_reading_t *reading, const char *label);