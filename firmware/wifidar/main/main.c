/*
 * wifidar firmware entry point.
 *
 * Step 10A: start USB and Wi-Fi, say hello, then scan forever and send
 * each scan as one JSON line. Commands (10B) and the display (10C) come next.
 */
#include <stdbool.h>

#include "protocol.h"
#include "scanner.h"
#include "usb_link.h"

#define MAX_NETWORKS CONFIG_WIFIDAR_MAX_NETWORKS  // set in menuconfig > wifidar

// Static so it lives in regular memory, not on app_main's small stack.
// 30 records is a couple of KB, which could overflow the task's stack.
static wifi_ap_record_t s_records[MAX_NETWORKS];

void app_main(void)
{
    usb_link_init();
    scanner_init();
    protocol_send_hello();

    while (true) {
        // A full scan takes a couple of seconds, which paces this loop
        uint16_t count = scanner_scan_all(s_records, MAX_NETWORKS);
        protocol_send_scan(s_records, count);
    }
}