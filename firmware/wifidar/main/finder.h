/*
 * finder.h: smoothing and percent for finder (TRACK) mode.
 *
 * Same math as bridge/fake_esp32.py and the screen twin, so the real
 * device and the fake behave the same.
 */
#pragma once

#include <stdbool.h>

/** One finder update, ready to send. */
typedef struct {
    int rssi;      // smoothed signal, dBm
    int raw_rssi;  // this scan's reading, or -100 if not found
    int percent;   // smoothed signal mapped to 0..100
    bool found;    // whether the network showed up in this scan
} finder_reading_t;

/** Forget the old reading. Call when starting to track a new network. */
void finder_reset(void);

/** Feed in one scan result and get the smoothed reading back. */
finder_reading_t finder_update(bool found, int raw_rssi);