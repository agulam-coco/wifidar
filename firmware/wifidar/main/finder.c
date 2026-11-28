/*
 * finder.c: smoothing and percent for finder (TRACK) mode.
 */
#include "finder.h"

#include <math.h>

// Same values as the bridge's config.py and the fake ESP32
#define RSSI_WEAK -90.0f    // 0% on the finder ring
#define RSSI_STRONG -35.0f  // 100% on the finder ring
#define SMOOTHING 0.7f      // weight of the old value: new = 0.7 * old + 0.3 * reading
#define NOT_FOUND_RSSI -100

static float s_smoothed = NOT_FOUND_RSSI;
static bool s_has_reading = false;

static int rssi_to_percent(float rssi)
{
    float percent = (rssi - RSSI_WEAK) * 100.0f / (RSSI_STRONG - RSSI_WEAK);
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    return (int)percent;
}

void finder_reset(void)
{
    s_smoothed = NOT_FOUND_RSSI;
    s_has_reading = false;
}

finder_reading_t finder_update(bool found, int raw_rssi)
{
    if (found) {
        if (!s_has_reading) {
            // First reading: use it directly, so the ring doesn't slowly climb from -100
            s_smoothed = (float)raw_rssi;
            s_has_reading = true;
        } else {
            s_smoothed = SMOOTHING * s_smoothed + (1.0f - SMOOTHING) * (float)raw_rssi;
        }
    }
    // If not found, keep the last smoothed value and report found = false

    finder_reading_t reading = {
        .rssi = (int)lroundf(s_smoothed),
        .raw_rssi = found ? raw_rssi : NOT_FOUND_RSSI,
        .percent = s_has_reading ? rssi_to_percent(s_smoothed) : 0,
        .found = found,
    };
    return reading;
}