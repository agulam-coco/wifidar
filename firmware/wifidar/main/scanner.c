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

static const char *TAG = "scanner";

void scanner_init(void)
{
    // The Wi-Fi driver keeps calibration data in NVS, so NVS starts first.
    // If NVS is full or from an older IDF version, erase it and try again.
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
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
        .show_hidden = true,  // include networks that hide their name
        // channel = 0 (left at the default) means every channel
    };

    // true = block until the scan finishes
    esp_err_t err = esp_wifi_scan_start(&scan_config, true);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "scan failed: %s", esp_err_to_name(err));
        return 0;
    }

    // count goes in as the array size and comes back as how many were stored.
    // This call also frees the driver's own copy of the results.
    uint16_t count = max;
    err = esp_wifi_scan_get_ap_records(&count, records);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "couldn't read scan results: %s", esp_err_to_name(err));
        return 0;
    }
    return count;
}