#ifndef EPD_7IN3F_H
#define EPD_7IN3F_H

#include <stdbool.h>

#define EPD_SCK_PIN   7
#define EPD_MOSI_PIN  9
#define EPD_CS_PIN    44
#define EPD_DC_PIN    10
#define EPD_RST_PIN   38
#define EPD_BUSY_PIN  4
#define EPD_POWER_PIN 43

#define EPD_WIDTH     800
#define EPD_HEIGHT    480
#define EPD_BUF_SIZE  192000 // 800 * 480 / 2

bool epd_init(void);
void epd_display_file(const char *filepath, const char *orientation);
void epd_power_off(void);

#endif // EPD_7IN3F_H
