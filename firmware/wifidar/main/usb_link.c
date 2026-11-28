/*
 * usb_link.c: talks to the laptop over the C3's built-in USB-Serial-JTAG.
 */
#include "usb_link.h"

#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

static const char *TAG = "usb_link";

// The transmit buffer has to fit the biggest single message (a full scan)
#define TX_BUFFER_SIZE 8192
#define RX_BUFFER_SIZE 1024

// How long a write waits for room in the buffer before giving up
#define WRITE_TIMEOUT_MS 500

void usb_link_init(void)
{
    usb_serial_jtag_driver_config_t config = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    config.tx_buffer_size = TX_BUFFER_SIZE;
    config.rx_buffer_size = RX_BUFFER_SIZE;

    esp_err_t err = usb_serial_jtag_driver_install(&config);
    if (err != ESP_OK)
    {
        // Not fatal: the console may have installed it already
        ESP_LOGW(TAG, "driver install returned %s", esp_err_to_name(err));
    }
}

void usb_link_write(const char *data, size_t len)
{
    int written = usb_serial_jtag_write_bytes(data, len, pdMS_TO_TICKS(WRITE_TIMEOUT_MS));
    if (written < (int)len)
    {
        // Usually means the laptop isn't reading. Drop the message rather than block.
        ESP_LOGW(TAG, "only sent %d of %u bytes", written, (unsigned)len);
    }
}

bool usb_link_read_byte(uint8_t *out)
{
    // portMAX_DELAY = wait forever. Only the command task calls this,
    // so blocking here doesn't hold up anything else.
    return usb_serial_jtag_read_bytes(out, 1, portMAX_DELAY) == 1;
}