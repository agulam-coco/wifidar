/*
 * display.c: the round GC9A01 screen, drawn with LVGL 9.
 *
 * Hardware setup is the same as Watch My Tokens (proven on this board).
 * Layout mirrors bridge/screen.py. If one changes, change the other.
 */
#include "display.h"

#include <stdbool.h>
#include <stdio.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_lcd_gc9a01.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lvgl_port.h"

// ---------- Hardware (ESP32-2424S012C) ----------

#define PIN_MOSI 7
#define PIN_SCLK 6
#define PIN_CS 10
#define PIN_DC 2
#define PIN_RST -1 // not wired; the GC9A01 resets with a software command
#define PIN_BL 3   // backlight

#define LCD_H_RES 240
#define LCD_V_RES 240
#define LCD_SPI_HZ (40 * 1000 * 1000)

// ---------- Colors (same as the screen twin) ----------

#define COLOR_BLACK 0x000000
#define COLOR_WHITE 0xFFFFFF
#define COLOR_LIGHT_GREY 0xC6C3C6
#define COLOR_DARK_GREY 0x7B7D7B
#define COLOR_DARK_GREEN 0x007D00
#define COLOR_GREEN 0x00FF00

// ---------- LVGL objects, created once in display_init() ----------

static lv_obj_t *s_scan_view; // container for the scan screen
static lv_obj_t *s_count_label;

static lv_obj_t *s_finder_view; // container for the finder screen
static lv_obj_t *s_arc;
static lv_obj_t *s_dbm_label;
static lv_obj_t *s_name_label;

// ---------- Hardware setup ----------

static void init_backlight(void)
{
    gpio_config_t config = {
        .pin_bit_mask = 1ULL << PIN_BL,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_ERROR_CHECK(gpio_config(&config));
    gpio_set_level(PIN_BL, 1);
}

/* SPI bus + GC9A01 panel + LVGL */
static void init_panel_and_lvgl(void)
{
    spi_bus_config_t bus_config = {
        .sclk_io_num = PIN_SCLK,
        .mosi_io_num = PIN_MOSI,
        .miso_io_num = -1, // the display never sends data back
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = LCD_H_RES * LCD_V_RES * 2, // one full frame, 2 bytes per pixel
    };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus_config, SPI_DMA_CH_AUTO));

    esp_lcd_panel_io_handle_t io_handle = NULL;
    esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = PIN_DC,
        .cs_gpio_num = PIN_CS,
        .pclk_hz = LCD_SPI_HZ,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI2_HOST,
                                             &io_config, &io_handle));

    esp_lcd_panel_handle_t panel_handle = NULL;
    esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = PIN_RST,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_BGR,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_gc9a01(io_handle, &panel_config, &panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel_handle, true)); // this panel needs it
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel_handle, true));

    const lvgl_port_cfg_t lvgl_config = ESP_LVGL_PORT_INIT_CONFIG();
    ESP_ERROR_CHECK(lvgl_port_init(&lvgl_config));

    const lvgl_port_display_cfg_t display_config = {
        .io_handle = io_handle,
        .panel_handle = panel_handle,
        .buffer_size = LCD_H_RES * 24, // draw 24 rows at a time
        .double_buffer = false,
        .hres = LCD_H_RES,
        .vres = LCD_V_RES,
        .monochrome = false,
        .color_format = LV_COLOR_FORMAT_RGB565,
        .rotation = {
            .swap_xy = false,
            .mirror_x = true,
            .mirror_y = false,
        },
        .flags = {
            .buff_dma = true,
            .swap_bytes = true,
        },
    };
    lvgl_port_add_disp(&display_config);
}

// ---------- Small builders (call with the LVGL lock held) ----------

/* A transparent full-screen container that holds one screen's objects. */
static lv_obj_t *create_view(void)
{
    lv_obj_t *view = lv_obj_create(lv_screen_active());
    lv_obj_remove_style_all(view); // no background, border, or padding
    lv_obj_set_size(view, LCD_H_RES, LCD_V_RES);
    lv_obj_center(view);
    lv_obj_remove_flag(view, LV_OBJ_FLAG_SCROLLABLE);
    return view;
}

/* A thin circle outline centered on the screen. */
static void create_ring(lv_obj_t *parent, int radius, uint32_t color)
{
    lv_obj_t *ring = lv_obj_create(parent);
    lv_obj_remove_style_all(ring);
    lv_obj_set_size(ring, radius * 2, radius * 2);
    lv_obj_center(ring);
    lv_obj_set_style_radius(ring, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(ring, 1, 0);
    lv_obj_set_style_border_color(ring, lv_color_hex(color), 0);
    lv_obj_set_style_border_opa(ring, LV_OPA_COVER, 0);
}

/* A label centered horizontally, y pixels above (-) or below (+) the middle. */
static lv_obj_t *create_label(lv_obj_t *parent, const lv_font_t *font, uint32_t color,
                              int y, const char *text)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_obj_set_style_text_font(label, font, 0);
    lv_obj_set_style_text_color(label, lv_color_hex(color), 0);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_text(label, text);
    // Stored as a style, so LVGL re-centers it whenever the text changes width
    lv_obj_align(label, LV_ALIGN_CENTER, 0, y);
    return label;
}

/* 0% red, 50% yellow, 100% green, same as the radar, the twin, and Signal Hunter. */
static lv_color_t strength_color(int percent)
{
    if (percent < 50)
    {
        return lv_color_make(255, (uint8_t)(percent * 255 / 50), 0);
    }
    return lv_color_make((uint8_t)(255 - (percent - 50) * 255 / 50), 255, 0);
}

// ---------- The two screens ----------

static void build_scan_view(void)
{
    s_scan_view = create_view();
    create_ring(s_scan_view, 90, COLOR_DARK_GREEN);
    create_ring(s_scan_view, 55, COLOR_DARK_GREEN);
    s_count_label = create_label(s_scan_view, &lv_font_montserrat_48, COLOR_WHITE, -8, "0");
    create_label(s_scan_view, &lv_font_montserrat_16, COLOR_LIGHT_GREY, 28, "networks");
    create_label(s_scan_view, &lv_font_montserrat_16, COLOR_GREEN, 80, "SCAN");
}

static void build_finder_view(void)
{
    s_finder_view = create_view();

    // Ring from radius 100 to 115 (230 px wide, 15 px thick), like the twin.
    // LVGL angles start at 3 o'clock and go clockwise, same as Pillow,
    // so rotation 120 + a 300 degree sweep leaves the gap at the bottom.
    s_arc = lv_arc_create(s_finder_view);
    lv_obj_set_size(s_arc, 230, 230);
    lv_obj_center(s_arc);
    lv_arc_set_rotation(s_arc, 120);
    lv_arc_set_bg_angles(s_arc, 0, 300);
    lv_arc_set_range(s_arc, 0, 100);
    lv_arc_set_value(s_arc, 0);
    lv_obj_remove_style(s_arc, NULL, LV_PART_KNOB);   // no draggable knob
    lv_obj_remove_flag(s_arc, LV_OBJ_FLAG_CLICKABLE); // display only
    lv_obj_set_style_arc_width(s_arc, 15, LV_PART_MAIN);
    lv_obj_set_style_arc_color(s_arc, lv_color_hex(COLOR_DARK_GREY), LV_PART_MAIN);
    lv_obj_set_style_arc_width(s_arc, 15, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(s_arc, strength_color(0), LV_PART_INDICATOR);

    s_dbm_label = create_label(s_finder_view, &lv_font_montserrat_28, COLOR_WHITE, -8, "-- dBm");
    s_name_label = create_label(s_finder_view, &lv_font_montserrat_16, COLOR_LIGHT_GREY, 24, "");
    // Long names get cut off with "..." instead of running off the round screen
    lv_obj_set_width(s_name_label, 170);
    lv_label_set_long_mode(s_name_label, LV_LABEL_LONG_DOT);

    lv_obj_add_flag(s_finder_view, LV_OBJ_FLAG_HIDDEN); // start on the scan screen
}

// ---------- Public functions ----------

void display_init(void)
{
    init_backlight();
    init_panel_and_lvgl();

    lvgl_port_lock(0); // 0 = wait as long as it takes
    lv_obj_set_style_bg_color(lv_screen_active(), lv_color_hex(COLOR_BLACK), 0);
    lv_obj_set_style_bg_opa(lv_screen_active(), LV_OPA_COVER, 0);
    build_scan_view();
    build_finder_view();
    lvgl_port_unlock();
}

void display_show_scan(uint16_t network_count)
{
    char text[8];
    snprintf(text, sizeof(text), "%u", network_count);

    lvgl_port_lock(0);
    lv_label_set_text(s_count_label, text);
    lv_obj_add_flag(s_finder_view, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(s_scan_view, LV_OBJ_FLAG_HIDDEN);
    lvgl_port_unlock();
}

void display_show_finder(const finder_reading_t *reading, const char *label)
{
    char dbm_text[16];
    snprintf(dbm_text, sizeof(dbm_text), "%d dBm", reading->rssi);

    lvgl_port_lock(0);
    lv_arc_set_value(s_arc, reading->percent);
    lv_obj_set_style_arc_color(s_arc, strength_color(reading->percent), LV_PART_INDICATOR);
    lv_label_set_text(s_dbm_label, dbm_text);
    lv_label_set_text(s_name_label, reading->found ? label : "searching...");
    lv_obj_add_flag(s_scan_view, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(s_finder_view, LV_OBJ_FLAG_HIDDEN);
    lvgl_port_unlock();
}