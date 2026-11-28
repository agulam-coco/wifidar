/*
 * commands.h: commands from the laptop.
 *
 * A background task reads lines from USB, parses them, and queues them.
 * The main loop picks them up with commands_receive().
 *
 * Commands (one per line, plain text):
 *     TRACK <bssid> <channel> <label...>    e.g. TRACK a4:2b:b0:1c:9e:7f 6 MyWifi
 *     STOP
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef enum
{
    COMMAND_TRACK,
    COMMAND_STOP,
} command_type_t;

typedef struct
{
    command_type_t type;
    uint8_t bssid[6]; // TRACK only: which access point to hunt
    uint8_t channel;  // TRACK only: its channel
    char label[33];   // TRACK only: name for the screen (SSIDs max out at 32 chars)
} command_t;

/** Start the background task that reads commands. Call once, after usb_link_init(). */
void commands_start(void);

/** Get the next waiting command without blocking. Returns false if there isn't one. */
bool commands_receive(command_t *out);