/*
 * scanner.c: starts the Wi-Fi driver and runs scans.
 *
 * Setup is the same as IDF's scan example. We never connect to a network;
 * station mode just lets the radio listen for nearby access points.
 */
#include "scanner.h"

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

#include <string.h>

static const char *TAG = "scanner";

// Listen time per scan in finder mode. Shorter means faster updates
// but a higher chance of missing the access point's reply.
#define TRACK_SCAN_MIN_MS 50
#define TRACK_SCAN_MAX_MS 120

void scanner_init(void)
{
    // The Wi-Fi driver keeps calibration data in NVS, so NVS starts first.
    // If NVS is full or from an older IDF version, erase it and try again.
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    // Networking layer, plus the event loop the Wi-Fi driver reports through
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    // Start the driver with default settings, in station (client) mode
    wifi_init_config_t config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&config));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
}

uint16_t scanner_scan_all(wifi_ap_record_t *records, uint16_t max)
{
    wifi_scan_config_t scan_config = {
        .show_hidden = true, // include networks that hide their name
        // channel = 0 (left at the default) means every channel
    };

    // true = block until the scan finishes
    esp_err_t err = esp_wifi_scan_start(&scan_config, true);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "scan failed: %s", esp_err_to_name(err));
        return 0;
    }

    // count goes in as the array size and comes back as how many were stored.
    // This call also frees the driver's own copy of the results.
    uint16_t count = max;
    err = esp_wifi_scan_get_ap_records(&count, records);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "couldn't read scan results: %s", esp_err_to_name(err));
        return 0;
    }
    return count;
}

bool scanner_scan_one(const uint8_t bssid[6], uint8_t channel, int *rssi_out)
{
    wifi_scan_config_t scan_config = {
        .bssid = (uint8_t *)bssid,  // only report this one access point
        .channel = channel,         // only listen on its channel
        .show_hidden = true,
        .scan_type = WIFI_SCAN_TYPE_ACTIVE,
        .scan_time.active = {
            .min = TRACK_SCAN_MIN_MS,
            .max = TRACK_SCAN_MAX_MS,
        },
    };

    esp_err_t err = esp_wifi_scan_start(&scan_config, true);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "track scan failed: %s", esp_err_to_name(err));
        return false;
    }

    wifi_ap_record_t record;
    uint16_t count = 1;
    err = esp_wifi_scan_get_ap_records(&count, &record);
    if (err != ESP_OK || count == 0) {
        return false;  // didn't hear it this time
    }

    // Double-check it's the right one before trusting the reading
    if (memcmp(record.bssid, bssid, 6) != 0) {
        return false;
    }

    *rssi_out = record.rssi;
    return true;
}