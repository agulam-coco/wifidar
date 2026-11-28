/*
 * protocol.c: builds the JSON messages and sends them over USB.
 *
 * Each message is built completely in one buffer, then sent in a single
 * write, so IDF log lines can't land in the middle of it. Every append
 * checks the remaining space, so a crowded scan can never overflow the
 * buffer: networks that don't fit are left out and the JSON stays valid.
 */
#include "protocol.h"

#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>

#include "esp_log.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "usb_link.h"

#define FW_VERSION "0.1.0"

// Biggest message we'll send, including the newline
#define MAX_LINE 4096

static const char *TAG = "protocol";

// The message being built. Static: one shared buffer, not on the stack.
static char s_line[MAX_LINE];
static size_t s_len;
static bool s_overflow;

// ---------- Buffer helpers ----------

static void line_reset(void)
{
    s_len = 0;
    s_overflow = false;
    s_line[0] = '\0';
}

/* Append formatted text, like printf. Marks overflow instead of writing past the end. */
static void line_appendf(const char *format, ...)
{
    if (s_overflow) {
        return;
    }
    size_t space = sizeof(s_line) - s_len;

    va_list args;
    va_start(args, format);
    int n = vsnprintf(s_line + s_len, space, format, args);
    va_end(args);

    if (n < 0 || (size_t)n >= space) {
        s_overflow = true;  // didn't fit; vsnprintf never writes past the end
        return;
    }
    s_len += (size_t)n;
}

/*
 * Append text as a JSON string, in quotes, with special characters escaped.
 *
 * Network names come from strangers' routers and can contain anything.
 * Quotes and backslashes get a backslash in front. Control characters and
 * non-ASCII bytes are written as \u00XX, so the output is always valid JSON.
 */
static void line_append_json_string(const char *text)
{
    line_appendf("\"");
    for (const unsigned char *p = (const unsigned char *)text; *p != '\0'; p++) {
        if (*p == '"' || *p == '\\') {
            line_appendf("\\%c", *p);
        } else if (*p < 0x20 || *p >= 0x7f) {
            line_appendf("\\u%04x", *p);
        } else {
            line_appendf("%c", *p);
        }
    }
    line_appendf("\"");
}

/* Finish the line with a newline and send it in one write. */
static void line_send(void)
{
    line_appendf("\n");
    if (s_overflow) {
        ESP_LOGW(TAG, "message too long, dropped");
        return;
    }
    usb_link_write(s_line, s_len);
}

static long long uptime_ms(void)
{
    return (long long)(esp_timer_get_time() / 1000);  // esp_timer counts microseconds
}

// ---------- Messages ----------

void protocol_send_hello(void)
{
    line_reset();
    line_appendf("{\"type\":\"hello\",\"fw\":\"%s\"}", FW_VERSION);
    line_send();
}

void protocol_send_scan(const wifi_ap_record_t *records, uint16_t count)
{
    line_reset();
    line_appendf("{\"type\":\"scan\",\"uptime_ms\":%lld,\"networks\":[", uptime_ms());

    uint16_t included = 0;
    for (uint16_t i = 0; i < count; i++) {
        const wifi_ap_record_t *ap = &records[i];
        size_t before = s_len;  // so we can undo this network if it doesn't fit

        if (included > 0) {
            line_appendf(",");  // commas go between items, not after the last one
        }
        line_appendf("{\"ssid\":");
        line_append_json_string((const char *)ap->ssid);
        line_appendf(",\"bssid\":\"" MACSTR "\",\"rssi\":%d,\"ch\":%d,\"open\":%s}",
                     MAC2STR(ap->bssid),
                     ap->rssi,
                     ap->primary,
                     ap->authmode == WIFI_AUTH_OPEN ? "true" : "false");

        // Keep room for the closing "]}\n". If this network didn't fit, undo it and stop.
        if (s_overflow || s_len + 4 > sizeof(s_line)) {
            s_len = before;
            s_overflow = false;
            ESP_LOGW(TAG, "scan message full, sent %u of %u networks", included, count);
            break;
        }
        included++;
    }

    line_appendf("]}");
    line_send();
}

void protocol_send_track(const uint8_t bssid[6], const finder_reading_t *reading)
{
    line_reset();
    line_appendf("{\"type\":\"track\",\"bssid\":\"" MACSTR "\","
                 "\"rssi\":%d,\"raw_rssi\":%d,\"percent\":%d,\"found\":%s}",
                 MAC2STR(bssid),
                 reading->rssi,
                 reading->raw_rssi,
                 reading->percent,
                 reading->found ? "true" : "false");
    line_send();
}