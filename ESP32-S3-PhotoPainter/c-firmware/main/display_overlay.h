#ifndef DISPLAY_OVERLAY_H
#define DISPLAY_OVERLAY_H

#include <stdbool.h>
#include <stdint.h>

#define COL_BLACK  0
#define COL_WHITE  1
#define COL_GREEN  6
#define COL_BLUE   5
#define COL_RED    3
#define COL_YELLOW 2

void display_overlay_battery_square(uint8_t *buf, int battery_pct);
void display_overlay_caption(uint8_t *buf, const char *filename, const char *mode, const char *description, bool is_portrait, int battery_pct);
void display_overlay_status(uint8_t *buf, const char *text);
void display_overlay_debug(uint8_t *buf, const char **lines, int line_count);

#endif // DISPLAY_OVERLAY_H
