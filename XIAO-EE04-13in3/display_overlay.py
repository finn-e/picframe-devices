# ==========================================
# FILE VERSION: 1.4.0
# DESCRIPTION: Display overlay routines for 13.3" Spectra 6 (1200×1600 native).
#   Adapted from PhotoPainter display_overlay.py — same logic, different canvas size.
#   EPD_WIDTH=1200, EPD_HEIGHT=1600 (physical panel, portrait native orientation).
# ==========================================

COL_BLACK  = 0
COL_WHITE  = 1
COL_GREEN  = 6
COL_BLUE   = 5
COL_RED    = 3
COL_YELLOW = 2

EPD_WIDTH  = 1200
EPD_HEIGHT = 1600

BAT_SQ_SIZE = 6
BAT_SQ_X = EPD_WIDTH  - BAT_SQ_SIZE - 4   # 1190
BAT_SQ_Y = EPD_HEIGHT - BAT_SQ_SIZE - 4   # 1590

FONT = {
    'A': (0x7C,0x12,0x11,0x12,0x7C), 'B': (0x7F,0x49,0x49,0x49,0x36),
    'C': (0x3E,0x41,0x41,0x41,0x22), 'D': (0x7F,0x41,0x41,0x22,0x1C),
    'E': (0x7F,0x49,0x49,0x49,0x41), 'F': (0x7F,0x09,0x09,0x09,0x01),
    'G': (0x3E,0x41,0x49,0x49,0x7A), 'H': (0x7F,0x08,0x08,0x08,0x7F),
    'I': (0x00,0x41,0x7F,0x41,0x00), 'J': (0x20,0x40,0x41,0x3F,0x01),
    'K': (0x7F,0x08,0x14,0x22,0x41), 'L': (0x7F,0x40,0x40,0x40,0x40),
    'M': (0x7F,0x02,0x0C,0x02,0x7F), 'N': (0x7F,0x04,0x08,0x10,0x7F),
    'O': (0x3E,0x41,0x41,0x41,0x3E), 'P': (0x7F,0x09,0x09,0x09,0x06),
    'Q': (0x3E,0x41,0x51,0x21,0x5E), 'R': (0x7F,0x09,0x19,0x29,0x46),
    'S': (0x46,0x49,0x49,0x49,0x31), 'T': (0x01,0x01,0x7F,0x01,0x01),
    'U': (0x3F,0x40,0x40,0x40,0x3F), 'V': (0x1F,0x20,0x40,0x20,0x1F),
    'W': (0x7F,0x20,0x18,0x20,0x7F), 'X': (0x63,0x14,0x08,0x14,0x63),
    'Y': (0x07,0x08,0x70,0x08,0x07), 'Z': (0x61,0x51,0x49,0x45,0x43),
    '0': (0x3E,0x51,0x49,0x45,0x3E), '1': (0x00,0x42,0x7F,0x40,0x00),
    '2': (0x42,0x61,0x51,0x49,0x46), '3': (0x21,0x41,0x45,0x4B,0x31),
    '4': (0x18,0x14,0x12,0x7F,0x10), '5': (0x27,0x45,0x45,0x45,0x39),
    '6': (0x3C,0x4A,0x49,0x49,0x30), '7': (0x01,0x71,0x09,0x05,0x03),
    '8': (0x36,0x49,0x49,0x49,0x36), '9': (0x06,0x49,0x49,0x29,0x1E),
    ' ': (0x00,0x00,0x00,0x00,0x00), '.': (0x00,0x60,0x60,0x00,0x00),
    '-': (0x08,0x08,0x08,0x08,0x08), ':': (0x00,0x24,0x24,0x00,0x00),
    '/': (0x20,0x10,0x08,0x04,0x02), ',': (0x00,0x50,0x30,0x00,0x00),
    "'": (0x00,0x05,0x03,0x00,0x00),
    '(': (0x00,0x1C,0x22,0x41,0x00), ')': (0x00,0x41,0x22,0x1C,0x00),
    '!': (0x00,0x00,0x5F,0x00,0x00), '?': (0x02,0x01,0x51,0x09,0x06),
    '_': (0x40,0x40,0x40,0x40,0x40), '+': (0x08,0x08,0x3E,0x08,0x08),
    '#': (0x14,0x7F,0x14,0x7F,0x14), '@': (0x3E,0x41,0x5D,0x55,0x5E),
}

def _set_pixel(buf, x, y, color, width=EPD_WIDTH, height=EPD_HEIGHT):
    if x < 0 or x >= width or y < 0 or y >= height:
        return
    idx = (y * width + x) // 2
    b = buf[idx]
    if x % 2 == 0:
        buf[idx] = (b & 0x0F) | (color << 4)
    else:
        buf[idx] = (b & 0xF0) | color

def _render_text_line(buf, text, y, scale=1, color=COL_BLACK, width=EPD_WIDTH):
    char_w = 5
    spacing = 1
    total_w = len(text) * (char_w + spacing) * scale
    x_off = max(0, (width - total_w) // 2)
    for ch in text:
        glyph = FONT.get(ch.upper(), FONT.get(' ', (0,0,0,0,0)))
        for ci in range(5):
            col_val = glyph[ci]
            for ri in range(7):
                if col_val & (1 << ri):
                    for sx in range(scale):
                        for sy in range(scale):
                            _set_pixel(buf, x_off + ci*scale + sx, y + ri*scale + sy, color, width)
        x_off += (char_w + spacing) * scale

def _render_outlined_text_line_at(buf, text, x_start, y, scale=1, width=EPD_WIDTH):
    char_w = 5
    spacing = 1
    x_off = x_start
    for ch in text:
        glyph = FONT.get(ch.upper(), FONT.get(' ', (0,0,0,0,0)))
        for ci in range(5):
            col_val = glyph[ci]
            for ri in range(7):
                if col_val & (1 << ri):
                    for ox in (-1, 0, 1):
                        for oy in (-1, 0, 1):
                            if ox != 0 or oy != 0:
                                for sx in range(scale):
                                    for sy in range(scale):
                                        _set_pixel(buf, x_off+ci*scale+sx+ox, y+ri*scale+sy+oy, COL_BLACK, width)
        x_off += (char_w + spacing) * scale
    x_off = x_start
    for ch in text:
        glyph = FONT.get(ch.upper(), FONT.get(' ', (0,0,0,0,0)))
        for ci in range(5):
            col_val = glyph[ci]
            for ri in range(7):
                if col_val & (1 << ri):
                    for sx in range(scale):
                        for sy in range(scale):
                            _set_pixel(buf, x_off+ci*scale+sx, y+ri*scale+sy, COL_WHITE, width)
        x_off += (char_w + spacing) * scale

def _render_outlined_text_line(buf, text, y, scale=1, x_center=None, width=EPD_WIDTH):
    char_w = 5
    spacing = 1
    total_w = len(text) * (char_w + spacing) * scale
    if x_center is None:
        x_start = max(0, (width - total_w) // 2)
    else:
        x_start = max(0, x_center - total_w // 2)
    _render_outlined_text_line_at(buf, text, x_start, y, scale, width)

def apply_battery_square(buf, battery_pct):
    if battery_pct is None:
        battery_pct = 100
    if battery_pct >= 80:
        color = COL_GREEN
    elif battery_pct >= 60:
        color = COL_YELLOW
    elif battery_pct >= 20:
        color = COL_RED
    else:
        _apply_critical_battery_banner(buf)
        return
    for dy in range(BAT_SQ_SIZE):
        for dx in range(BAT_SQ_SIZE):
            _set_pixel(buf, BAT_SQ_X + dx, BAT_SQ_Y + dy, color)

def _apply_critical_battery_banner(buf):
    BANNER_H = 14
    BANNER_Y = EPD_HEIGHT - BANNER_H
    for y in range(BANNER_Y, EPD_HEIGHT):
        for x in range(EPD_WIDTH):
            _set_pixel(buf, x, y, COL_RED)
    msg = 'LOW BATTERY: PLEASE PLUG INTO POWER'
    _render_text_line(buf, msg, BANNER_Y + (BANNER_H - 7) // 2, scale=1, color=COL_WHITE)

def apply_branding_text(buf, battery_pct=None, img_path=None):
    if img_path:
        base = img_path.split('/')[-1]
        if base.endswith('.bin'):
            base = base[:-4]
        for suffix in ('_l_u', '_l_f', '_p_u', '_p_f', '_l', '_p'):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        msg = base.replace('_', ' ').upper().strip()
    else:
        msg = 'PICFRAMES'
    y = EPD_HEIGHT - 12
    if battery_pct is not None and battery_pct < 20:
        y = EPD_HEIGHT - 26
    _render_outlined_text_line(buf, msg, y, scale=1)

def _wrap_text(text, max_chars=76):
    words = text.split(' ')
    lines = []
    curr_line = []
    curr_len = 0
    for w in words:
        if not w: continue
        if curr_len + len(w) + (1 if curr_line else 0) > max_chars:
            if curr_line:
                lines.append(' '.join(curr_line))
            curr_line = [w]
            curr_len = len(w)
        else:
            curr_line.append(w)
            curr_len += len(w) + 1
    if curr_line:
        lines.append(' '.join(curr_line))
    return lines

def apply_caption_overlay(buf, filename, mode, description, is_portrait, battery_pct=None):
    if not mode or mode == 'none':
        return
    base = filename.split('/')[-1]
    if base.endswith('.bin'):
        base = base[:-4]
    for suffix in ['_l_u', '_l_f', '_p_u', '_p_f', '_l', '_p']:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    title = base.replace('_', ' ').upper().strip()
    if mode == 'title':
        _render_outlined_text_line(buf, title, EPD_HEIGHT - 18, scale=1)
    elif mode == 'details':
        desc = description.upper().strip()
        if not desc:
            _render_outlined_text_line(buf, title, EPD_HEIGHT - 18, scale=1)
            return
        if not is_portrait:
            _render_outlined_text_line(buf, desc, EPD_HEIGHT - 18, scale=1)
        else:
            lines = _wrap_text(desc, max_chars=76)[:3]
            if len(lines) == 1:
                _render_outlined_text_line(buf, lines[0], EPD_HEIGHT - 18, scale=1)
            else:
                for i, line in enumerate(lines):
                    y = EPD_HEIGHT - 12 - (len(lines) - 1 - i) * 10
                    _render_outlined_text_line(buf, line, y, scale=1)
    elif mode == 'title_details':
        desc = description.upper().strip()
        if not desc:
            _render_outlined_text_line(buf, title, EPD_HEIGHT - 18, scale=1)
            return
        if not is_portrait:
            _render_outlined_text_line(buf, desc,  EPD_HEIGHT - 12, scale=1)
            _render_outlined_text_line(buf, title, EPD_HEIGHT - 22, scale=1)
        else:
            lines = _wrap_text(desc, max_chars=76)[:3]
            for i, line in enumerate(lines):
                y = EPD_HEIGHT - 12 - (len(lines) - 1 - i) * 10
                _render_outlined_text_line(buf, line, y, scale=1)
            _render_outlined_text_line(buf, title, EPD_HEIGHT - 12 - len(lines) * 10, scale=1)

def apply_status_overlay(buf, text, width=EPD_WIDTH):
    """Draw one outlined status line at the top-left (x=4, y=8).
    Truncated to 196 chars (1200px / 6px per char = 200; leave margin).
    Call after apply_battery_square when fail_reason is set."""
    if not text:
        return
    text = str(text)[:196].upper()
    _render_outlined_text_line_at(buf, text, 4, 8, scale=1, width=width)

def apply_debug_overlay(buf, lines):
    """Render a small block of right-aligned debug lines in the upper-right corner.
    *lines* is a list of strings (empty/None entries are skipped).
    Canvas is EPD_WIDTH x EPD_HEIGHT (1200 x 1600). Lines are right-aligned by
    pixel width (len * 6) with a small margin from the right edge."""
    char_w = 5
    spacing = 1
    glyph_stride = char_w + spacing  # 6 px per character
    line_height = 9                  # 7px glyph + 2px gap
    margin_right = 4
    margin_top = 4

    y = margin_top
    for line in lines:
        if not line:
            continue
        text = str(line)
        w = len(text) * glyph_stride
        x = EPD_WIDTH - margin_right - w
        _render_outlined_text_line_at(buf, text, x, y, scale=1, width=EPD_WIDTH)
        y += line_height
