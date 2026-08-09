#include "display_overlay.h"
#include <stdio.h>
#include <string.h>
#include <ctype.h>

#define WIDTH              800
#define HEIGHT             480
#define BAT_SQ_SIZE        6
#define BAT_SQ_X           (WIDTH - BAT_SQ_SIZE - 4)  // 790
#define BAT_SQ_Y           (HEIGHT - BAT_SQ_SIZE - 4) // 470
#define CRITICAL_BATTERY_PCT 20
#define BANNER_H           14
#define BANNER_Y           (HEIGHT - BANNER_H)

static const uint8_t *get_glyph(char c) {
    switch (toupper((int)c)) {
        case 'A': { static const uint8_t g[] = {0x7C,0x12,0x11,0x12,0x7C}; return g; }
        case 'B': { static const uint8_t g[] = {0x7F,0x49,0x49,0x49,0x36}; return g; }
        case 'C': { static const uint8_t g[] = {0x3E,0x41,0x41,0x41,0x22}; return g; }
        case 'D': { static const uint8_t g[] = {0x7F,0x41,0x41,0x22,0x1C}; return g; }
        case 'E': { static const uint8_t g[] = {0x7F,0x49,0x49,0x49,0x41}; return g; }
        case 'F': { static const uint8_t g[] = {0x7F,0x09,0x09,0x09,0x01}; return g; }
        case 'G': { static const uint8_t g[] = {0x3E,0x41,0x49,0x49,0x7A}; return g; }
        case 'H': { static const uint8_t g[] = {0x7F,0x08,0x08,0x08,0x7F}; return g; }
        case 'I': { static const uint8_t g[] = {0x00,0x41,0x7F,0x41,0x00}; return g; }
        case 'J': { static const uint8_t g[] = {0x20,0x40,0x41,0x3F,0x01}; return g; }
        case 'K': { static const uint8_t g[] = {0x7F,0x08,0x14,0x22,0x41}; return g; }
        case 'L': { static const uint8_t g[] = {0x7F,0x40,0x40,0x40,0x40}; return g; }
        case 'M': { static const uint8_t g[] = {0x7F,0x02,0x0C,0x02,0x7F}; return g; }
        case 'N': { static const uint8_t g[] = {0x7F,0x04,0x08,0x10,0x7F}; return g; }
        case 'O': { static const uint8_t g[] = {0x3E,0x41,0x41,0x41,0x3E}; return g; }
        case 'P': { static const uint8_t g[] = {0x7F,0x09,0x09,0x09,0x06}; return g; }
        case 'Q': { static const uint8_t g[] = {0x3E,0x41,0x51,0x21,0x5E}; return g; }
        case 'R': { static const uint8_t g[] = {0x7F,0x09,0x19,0x29,0x46}; return g; }
        case 'S': { static const uint8_t g[] = {0x46,0x49,0x49,0x49,0x31}; return g; }
        case 'T': { static const uint8_t g[] = {0x01,0x01,0x7F,0x01,0x01}; return g; }
        case 'U': { static const uint8_t g[] = {0x3F,0x40,0x40,0x40,0x3F}; return g; }
        case 'V': { static const uint8_t g[] = {0x1F,0x20,0x40,0x20,0x1F}; return g; }
        case 'W': { static const uint8_t g[] = {0x7F,0x20,0x18,0x20,0x7F}; return g; }
        case 'X': { static const uint8_t g[] = {0x63,0x14,0x08,0x14,0x63}; return g; }
        case 'Y': { static const uint8_t g[] = {0x07,0x08,0x70,0x08,0x07}; return g; }
        case 'Z': { static const uint8_t g[] = {0x61,0x51,0x49,0x45,0x43}; return g; }
        case '0': { static const uint8_t g[] = {0x3E,0x51,0x49,0x45,0x3E}; return g; }
        case '1': { static const uint8_t g[] = {0x00,0x42,0x7F,0x40,0x00}; return g; }
        case '2': { static const uint8_t g[] = {0x42,0x61,0x51,0x49,0x46}; return g; }
        case '3': { static const uint8_t g[] = {0x21,0x41,0x45,0x4B,0x31}; return g; }
        case '4': { static const uint8_t g[] = {0x18,0x14,0x12,0x7F,0x10}; return g; }
        case '5': { static const uint8_t g[] = {0x27,0x45,0x45,0x45,0x39}; return g; }
        case '6': { static const uint8_t g[] = {0x3C,0x4A,0x49,0x49,0x30}; return g; }
        case '7': { static const uint8_t g[] = {0x01,0x71,0x09,0x05,0x03}; return g; }
        case '8': { static const uint8_t g[] = {0x36,0x49,0x49,0x49,0x36}; return g; }
        case '9': { static const uint8_t g[] = {0x06,0x49,0x49,0x29,0x1E}; return g; }
        case ' ': { static const uint8_t g[] = {0x00,0x00,0x00,0x00,0x00}; return g; }
        case '.': { static const uint8_t g[] = {0x00,0x60,0x60,0x00,0x00}; return g; }
        case '-': { static const uint8_t g[] = {0x08,0x08,0x08,0x08,0x08}; return g; }
        case ':': { static const uint8_t g[] = {0x00,0x24,0x24,0x00,0x00}; return g; }
        case '/': { static const uint8_t g[] = {0x20,0x10,0x08,0x04,0x02}; return g; }
        case ',': { static const uint8_t g[] = {0x00,0x50,0x30,0x00,0x00}; return g; }
        case '\'': { static const uint8_t g[] = {0x00,0x05,0x03,0x00,0x00}; return g; }
        case '(': { static const uint8_t g[] = {0x00,0x1C,0x22,0x41,0x00}; return g; }
        case ')': { static const uint8_t g[] = {0x00,0x41,0x22,0x1C,0x00}; return g; }
        case '!': { static const uint8_t g[] = {0x00,0x00,0x5F,0x00,0x00}; return g; }
        case '?': { static const uint8_t g[] = {0x02,0x01,0x51,0x09,0x06}; return g; }
        case '_': { static const uint8_t g[] = {0x40,0x40,0x40,0x40,0x40}; return g; }
        case '+': { static const uint8_t g[] = {0x08,0x08,0x3E,0x08,0x08}; return g; }
        case '#': { static const uint8_t g[] = {0x14,0x7F,0x14,0x7F,0x14}; return g; }
        case '@': { static const uint8_t g[] = {0x3E,0x41,0x5D,0x55,0x5E}; return g; }
        default: { static const uint8_t g[] = {0x00,0x00,0x00,0x00,0x00}; return g; }
    }
}

static void set_pixel(uint8_t *buf, int x, int y, uint8_t color) {
    if (x < 0 || x >= WIDTH || y < 0 || y >= HEIGHT) return;
    int idx = (y * WIDTH + x) / 2;
    uint8_t b = buf[idx];
    if (x % 2 == 0) {
        buf[idx] = (b & 0x0F) | (color << 4);
    } else {
        buf[idx] = (b & 0xF0) | (color & 0x0F);
    }
}

static void set_pixel_portrait(uint8_t *buf, int vx, int vy, uint8_t color) {
    // Visual portrait coords (480 wide x 800 tall) onto physical 800x480
    // physical (width - 1 - vy, vx)
    set_pixel(buf, WIDTH - 1 - vy, vx, color);
}

static void render_text_line(uint8_t *buf, const char *text, int y, int scale, uint8_t color) {
    int char_w = 5;
    int spacing = 1;
    int total_w = strlen(text) * (char_w + spacing) * scale;
    int x_off = (WIDTH - total_w) / 2;
    if (x_off < 0) x_off = 0;

    for (int i = 0; text[i] != '\0'; i++) {
        const uint8_t *glyph = get_glyph(text[i]);
        for (int ci = 0; ci < 5; ci++) {
            uint8_t col_val = glyph[ci];
            for (int ri = 0; ri < 7; ri++) {
                if (col_val & (1 << ri)) {
                    for (int sx = 0; sx < scale; sx++) {
                        for (int sy = 0; sy < scale; sy++) {
                            set_pixel(buf, x_off + ci * scale + sx, y + ri * scale + sy, color);
                        }
                    }
                }
            }
        }
        x_off += (char_w + spacing) * scale;
    }
}

static void render_outlined_text_line_at(uint8_t *buf, const char *text, int x_start, int y, int scale) {
    int char_w = 5;
    int spacing = 1;

    // 1. Outline pass (white)
    int x_off = x_start;
    for (int i = 0; text[i] != '\0'; i++) {
        const uint8_t *glyph = get_glyph(text[i]);
        for (int ci = 0; ci < 5; ci++) {
            uint8_t col_val = glyph[ci];
            for (int ri = 0; ri < 7; ri++) {
                if (col_val & (1 << ri)) {
                    for (int ox = -1; ox <= 1; ox++) {
                        for (int oy = -1; oy <= 1; oy++) {
                            if (ox != 0 || oy != 0) {
                                for (int sx = 0; sx < scale; sx++) {
                                    for (int sy = 0; sy < scale; sy++) {
                                        set_pixel(buf, x_off + ci * scale + sx + ox, y + ri * scale + sy + oy, COL_WHITE);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        x_off += (char_w + spacing) * scale;
    }

    // 2. Body pass (black)
    x_off = x_start;
    for (int i = 0; text[i] != '\0'; i++) {
        const uint8_t *glyph = get_glyph(text[i]);
        for (int ci = 0; ci < 5; ci++) {
            uint8_t col_val = glyph[ci];
            for (int ri = 0; ri < 7; ri++) {
                if (col_val & (1 << ri)) {
                    for (int sx = 0; sx < scale; sx++) {
                        for (int sy = 0; sy < scale; sy++) {
                            set_pixel(buf, x_off + ci * scale + sx, y + ri * scale + sy, COL_BLACK);
                        }
                    }
                }
            }
        }
        x_off += (char_w + spacing) * scale;
    }
}

static void render_outlined_text_line(uint8_t *buf, const char *text, int y, int scale, int x_center) {
    int char_w = 5;
    int spacing = 1;
    int total_w = strlen(text) * (char_w + spacing) * scale;
    int x_start = (x_center < 0) ? (WIDTH - total_w) / 2 : x_center - total_w / 2;
    if (x_start < 0) x_start = 0;
    render_outlined_text_line_at(buf, text, x_start, y, scale);
}

static void render_outlined_text_line_portrait(uint8_t *buf, const char *text, int vy, int scale, int vx_center) {
    int char_w = 5;
    int spacing = 1;
    int total_w = strlen(text) * (char_w + spacing) * scale;
    int vx_start = (vx_center < 0) ? (480 - total_w) / 2 : vx_center - total_w / 2;
    if (vx_start < 0) vx_start = 0;

    // Outline pass (white)
    int vx_off = vx_start;
    for (int i = 0; text[i] != '\0'; i++) {
        const uint8_t *glyph = get_glyph(text[i]);
        for (int ci = 0; ci < 5; ci++) {
            uint8_t col_val = glyph[ci];
            for (int ri = 0; ri < 7; ri++) {
                if (col_val & (1 << ri)) {
                    for (int ox = -1; ox <= 1; ox++) {
                        for (int oy = -1; oy <= 1; oy++) {
                            if (ox != 0 || oy != 0) {
                                for (int sx = 0; sx < scale; sx++) {
                                    for (int sy = 0; sy < scale; sy++) {
                                        set_pixel_portrait(buf, vx_off + ci * scale + sx + ox, vy + ri * scale + sy + oy, COL_WHITE);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        vx_off += (char_w + spacing) * scale;
    }

    // Body pass (black)
    vx_off = vx_start;
    for (int i = 0; text[i] != '\0'; i++) {
        const uint8_t *glyph = get_glyph(text[i]);
        for (int ci = 0; ci < 5; ci++) {
            uint8_t col_val = glyph[ci];
            for (int ri = 0; ri < 7; ri++) {
                if (col_val & (1 << ri)) {
                    for (int sx = 0; sx < scale; sx++) {
                        for (int sy = 0; sy < scale; sy++) {
                            set_pixel_portrait(buf, vx_off + ci * scale + sx, vy + ri * scale + sy, COL_BLACK);
                        }
                    }
                }
            }
        }
        vx_off += (char_w + spacing) * scale;
    }
}

void display_overlay_battery_square(uint8_t *buf, int battery_pct) {
    if (battery_pct < 0) battery_pct = 100;

    if (battery_pct < CRITICAL_BATTERY_PCT) {
        // Render red banner
        for (int y = BANNER_Y; y < HEIGHT; y++) {
            for (int x = 0; x < WIDTH; x++) {
                set_pixel(buf, x, y, COL_RED);
            }
        }
        const char *msg = "LOW POWER: REFRESH DISABLED. MANUALLY SKIP IMAGES OR PLUG IN.";
        render_text_line(buf, msg, BANNER_Y + (BANNER_H - 7) / 2, 1, COL_WHITE);
        return;
    }

    uint8_t color = COL_GREEN;
    if (battery_pct < 40) color = COL_RED;
    else if (battery_pct < 60) color = COL_YELLOW;

    for (int dy = 0; dy < BAT_SQ_SIZE; dy++) {
        for (int dx = 0; dx < BAT_SQ_SIZE; dx++) {
            set_pixel(buf, BAT_SQ_X + dx, BAT_SQ_Y + dy, color);
        }
    }
}

static void wrap_text(const char *text, int max_chars, char lines_out[3][128], int *line_count) {
    *line_count = 0;
    char temp[512];
    strncpy(temp, text, sizeof(temp) - 1);
    temp[sizeof(temp) - 1] = '\0';

    char *word = strtok(temp, " ");
    char curr_line[128] = {0};

    while (word && *line_count < 3) {
        if (strlen(curr_line) + strlen(word) + (curr_line[0] != '\0' ? 1 : 0) > max_chars) {
            strncpy(lines_out[*line_count], curr_line, 127);
            (*line_count)++;
            strcpy(curr_line, word);
        } else {
            if (curr_line[0] != '\0') strcat(curr_line, " ");
            strcat(curr_line, word);
        }
        word = strtok(NULL, " ");
    }
    if (curr_line[0] != '\0' && *line_count < 3) {
        strncpy(lines_out[*line_count], curr_line, 127);
        (*line_count)++;
    }
}

void display_overlay_caption(uint8_t *buf, const char *filename, const char *mode, const char *description, bool is_portrait, int battery_pct) {
    if (!mode || strcmp(mode, "none") == 0 || strlen(mode) == 0) return;

    int shift = (battery_pct >= 0 && battery_pct < CRITICAL_BATTERY_PCT) ? BANNER_H : 0;

    // Extract Title from filename
    char title[128] = {0};
    const char *base = strrchr(filename, '/');
    base = base ? base + 1 : filename;
    strncpy(title, base, sizeof(title) - 1);

    // Strip suffix like .bin, _l, _p, _l_u etc.
    char *dot = strrchr(title, '.');
    if (dot) *dot = '\0';
    
    char *suffix = strstr(title, "_l");
    if (!suffix) suffix = strstr(title, "_p");
    if (suffix) *suffix = '\0';

    // Replace underscores with spaces and capitalize
    for (int i = 0; title[i] != '\0'; i++) {
        title[i] = toupper((int)title[i]);
        if (title[i] == '_') title[i] = ' ';
    }

    char desc_upper[512] = {0};
    if (description) {
        for (int i = 0; description[i] != '\0' && i < 511; i++) {
            desc_upper[i] = toupper((int)description[i]);
        }
    }

    if (strcmp(mode, "title") == 0) {
        render_outlined_text_line(buf, title, HEIGHT - 18 - shift, 1, -1);
    } else if (strcmp(mode, "details") == 0) {
        if (strlen(desc_upper) == 0) {
            render_outlined_text_line(buf, title, HEIGHT - 18 - shift, 1, -1);
            return;
        }
        if (!is_portrait) {
            render_outlined_text_line(buf, desc_upper, HEIGHT - 18 - shift, 1, -1);
        } else {
            char lines[3][128];
            int line_count = 0;
            wrap_text(desc_upper, 76, lines, &line_count);
            if (line_count == 1) {
                render_outlined_text_line(buf, lines[0], HEIGHT - 18 - shift, 1, -1);
            } else {
                for (int i = 0; i < line_count; i++) {
                    int y = HEIGHT - 12 - shift - (line_count - 1 - i) * 10;
                    render_outlined_text_line(buf, lines[i], y, 1, -1);
                }
            }
        }
    } else if (strcmp(mode, "title_details") == 0) {
        if (strlen(desc_upper) == 0) {
            render_outlined_text_line(buf, title, HEIGHT - 18 - shift, 1, -1);
            return;
        }
        if (!is_portrait) {
            render_outlined_text_line(buf, desc_upper, HEIGHT - 12 - shift, 1, -1);
            render_outlined_text_line(buf, title, HEIGHT - 22 - shift, 1, -1);
        } else {
            char lines[3][128];
            int line_count = 0;
            wrap_text(desc_upper, 76, lines, &line_count);
            for (int i = 0; i < line_count; i++) {
                int y = HEIGHT - 12 - shift - (line_count - 1 - i) * 10;
                render_outlined_text_line(buf, lines[i], y, 1, -1);
            }
            int title_y = HEIGHT - 12 - shift - line_count * 10;
            render_outlined_text_line(buf, title, title_y, 1, -1);
        }
    }
}

void display_overlay_status(uint8_t *buf, const char *text) {
    if (!text || strlen(text) == 0) return;
    char text_upper[80] = {0};
    for (int i = 0; text[i] != '\0' && i < 78; i++) {
        text_upper[i] = toupper((int)text[i]);
    }
    render_outlined_text_line_at(buf, text_upper, 4, 8, 1);
}

void display_overlay_debug(uint8_t *buf, const char **lines, int line_count) {
    int glyph_stride = 6;
    int line_height = 9;
    int margin_right = 4;
    int margin_top = 4;

    int y = margin_top;
    for (int i = 0; i < line_count; i++) {
        if (!lines[i] || strlen(lines[i]) == 0) continue;
        int w = strlen(lines[i]) * glyph_stride;
        int x = WIDTH - margin_right - w;
        render_outlined_text_line_at(buf, lines[i], x, y, 1);
        y += line_height;
    }
}
