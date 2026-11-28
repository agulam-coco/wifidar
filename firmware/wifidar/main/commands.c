/*
 * commands.c: reads commands from the laptop on a background task.
 *
 * Same pattern as serial_read_task in Watch My Tokens: read one byte at a
 * time, collect them into a line, and handle the line at '\n' or '\r'.
 * Parsed commands go into a FreeRTOS queue for the main loop.
 */
#include "commands.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "usb_link.h"

static const char *TAG = "commands";

#define MAX_LINE 128    // longest command line we accept
#define QUEUE_LENGTH 4  // commands that can wait before new ones get dropped
#define TASK_STACK 4096 // bytes of stack for the reader task
#define TASK_PRIORITY 5 // FreeRTOS priority for the reader task

static QueueHandle_t s_queue;

// ---------- Parsing ----------

/* Value of one hex digit, or -1 if it isn't one. */
static int hex_value(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

/*
 * Parse a BSSID like "a4:2b:b0:1c:9e:7f" into 6 bytes.
 * Returns a pointer just past the BSSID, or NULL if it's malformed.
 */
static const char *parse_bssid(const char *text, uint8_t out[6])
{
    for (int i = 0; i < 6; i++)
    {
        int high = hex_value(text[0]);
        if (high < 0)
            return NULL;
        int low = hex_value(text[1]);
        if (low < 0)
            return NULL;

        out[i] = (uint8_t)((high << 4) | low); // two hex digits = one byte
        text += 2;

        if (i < 5)
        {
            if (*text != ':')
                return NULL;
            text++;
        }
    }
    return text;
}

/* Turn one line of text into a command. Returns false if the line is malformed. */
static bool parse_line(const char *line, command_t *cmd)
{
    memset(cmd, 0, sizeof(*cmd));

    if (strcmp(line, "STOP") == 0)
    {
        cmd->type = COMMAND_STOP;
        return true;
    }

    if (strncmp(line, "TRACK ", 6) != 0)
    {
        return false;
    }

    // BSSID, then a space
    const char *p = parse_bssid(line + 6, cmd->bssid);
    if (p == NULL || *p != ' ')
    {
        return false;
    }

    // Channel number. strtol sets end to the first character it didn't use.
    char *end;
    long channel = strtol(p + 1, &end, 10);
    if (end == p + 1 || channel < 1 || channel > 14)
    {
        return false; // no digits, or not a real 2.4 GHz channel
    }
    cmd->channel = (uint8_t)channel;

    // Everything after the next space is the label (it can contain spaces).
    // snprintf cuts it off safely if it's too long for the buffer.
    const char *label = (*end == ' ') ? end + 1 : "";
    snprintf(cmd->label, sizeof(cmd->label), "%s", label);

    cmd->type = COMMAND_TRACK;
    return true;
}

// ---------- Reader task ----------

static void command_task(void *arg)
{
    char line[MAX_LINE];
    size_t len = 0;

    while (true)
    {
        uint8_t byte;
        if (!usb_link_read_byte(&byte))
        {
            continue;
        }

        if (byte == '\n' || byte == '\r')
        {
            if (len == 0)
            {
                continue; // blank line, or the '\n' after a '\r'
            }
            line[len] = '\0'; // C strings end with a zero byte
            len = 0;

            command_t cmd;
            if (!parse_line(line, &cmd))
            {
                ESP_LOGW(TAG, "ignoring bad command: %s", line);
                continue;
            }
            // Timeout 0: if the queue is somehow full, drop it instead of blocking
            if (xQueueSend(s_queue, &cmd, 0) != pdTRUE)
            {
                ESP_LOGW(TAG, "command queue full, dropped a command");
            }
        }
        else if (len < sizeof(line) - 1)
        {
            line[len++] = (char)byte; // keep room for the '\0'
        }
    }
}

// ---------- Public functions ----------

void commands_start(void)
{
    s_queue = xQueueCreate(QUEUE_LENGTH, sizeof(command_t));
    xTaskCreate(command_task, "commands", TASK_STACK, NULL, TASK_PRIORITY, NULL);
}

bool commands_receive(command_t *out)
{
    return xQueueReceive(s_queue, out, 0) == pdTRUE; // 0 = don't wait
}