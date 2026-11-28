/*
 * wifidar firmware entry point.
 *
 * A two-mode state machine:
 *     SCAN   full scans of every channel, sent as "scan" messages
 *     TRACK  quick scans for one access point, sent as "track" messages
 * Commands from the laptop (TRACK / STOP) switch between them.
 * Each mode also updates the round screen.
 */
#include <stdbool.h>

#include "commands.h"
#include "finder.h"
#include "protocol.h"
#include "scanner.h"
#include "usb_link.h"
#include "display.h"

#define MAX_NETWORKS CONFIG_WIFIDAR_MAX_NETWORKS // set in menuconfig > wifidar

typedef enum
{
    MODE_SCAN,
    MODE_TRACK,
} wifidar_mode_t;

// Static so they live in regular memory, not on app_main's small stack
static wifi_ap_record_t s_records[MAX_NETWORKS];
static wifidar_mode_t s_mode = MODE_SCAN;
static command_t s_target; // the network being tracked, from the last TRACK command

/* Switch modes based on a command from the laptop. */
static void apply_command(const command_t *cmd)
{
    switch (cmd->type)
    {
    case COMMAND_TRACK:
        s_target = *cmd; // copies the whole struct: bssid, channel, label
        finder_reset();
        s_mode = MODE_TRACK;
        break;
    case COMMAND_STOP:
        s_mode = MODE_SCAN;
        break;
    }
}

static void run_scan_mode(void)
{
    uint16_t count = scanner_scan_all(s_records, MAX_NETWORKS);
    protocol_send_scan(s_records, count);
    display_show_scan(count);
}

static void run_track_mode(void)
{
    int raw_rssi = 0;
    bool found = scanner_scan_one(s_target.bssid, s_target.channel, &raw_rssi);
    finder_reading_t reading = finder_update(found, raw_rssi);
    protocol_send_track(s_target.bssid, &reading);
    display_show_finder(&reading, s_target.label);
}

void app_main(void)
{
    usb_link_init();
    display_init();
    commands_start(); // after USB, since the command task reads from it
    scanner_init();
    protocol_send_hello();

    while (true)
    {
        // Handle every command that arrived since the last pass
        command_t cmd;
        while (commands_receive(&cmd))
        {
            apply_command(&cmd);
        }

        if (s_mode == MODE_SCAN)
        {
            run_scan_mode();
        }
        else
        {
            run_track_mode();
        }
    }
}