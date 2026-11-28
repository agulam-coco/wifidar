# The "main" component: our own code.
# The project uses MINIMAL_BUILD, so every IDF component we use is listed here.
# Libraries from idf_component.yml (LVGL, GC9A01) are added automatically.
idf_component_register(
    SRCS
        "main.c"
        "usb_link.c"
        "protocol.c"
        "scanner.c"
        "commands.c"
        "finder.c"
        "display.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES
        esp_wifi                       # Wi-Fi driver and scanning
        esp_netif                      # networking layer the Wi-Fi driver needs
        esp_event                      # event loop the Wi-Fi driver reports through
        nvs_flash                      # storage the Wi-Fi driver keeps calibration in
        esp_timer                      # uptime in microseconds
        esp_driver_usb_serial_jtag     # talking to the laptop over USB
        esp_driver_spi                 # SPI bus to the display
        esp_driver_gpio                # backlight pin
        esp_lcd                        # LCD panel interface
)