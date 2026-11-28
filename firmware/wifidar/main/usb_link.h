/*
 * usb_link.h: talks to the laptop over the C3's built-in USB-Serial-JTAG.
 *
 * Install the driver once, then send and receive raw bytes.
 * This is the only file that touches the USB driver.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** Install the USB-Serial-JTAG driver. Call once at boot, before sending anything. */
void usb_link_init(void);

/** Send len bytes to the laptop. Gives up after a short timeout if nobody is reading. */
void usb_link_write(const char *data, size_t len);

/** Wait for the next byte from the laptop and store it in out. Blocks until one arrives. */
bool usb_link_read_byte(uint8_t *out);