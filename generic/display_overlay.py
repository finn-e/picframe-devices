# ==========================================
# FILE VERSION: 2.3.0
# DESCRIPTION: Display overlay routines: battery indicator square and
#              critical battery banner.
# ==========================================

COL_BLACK  = 0
COL_WHITE  = 1
COL_GREEN  = 6
COL_BLUE   = 5
COL_RED    = 3
COL_YELLOW = 2

BAT_SQ_SIZE = 6
BAT_SQ_X = 800 - BAT_SQ_SIZE - 4  # 790
BAT_SQ_Y = 480 - BAT_SQ_SIZE - 4  # 470

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

def _set_pixel(buf, x, y, color, width=800):
    if x < 0 or x >= width or y < 0 or y >= 480:
        return
    idx = (y * width + x) // 2
    b = buf[idx]
    if x % 2 == 0:
        buf[idx] = (b & 0x0F) | (color << 4)
    else:
        buf[idx] = (b & 0xF0) | color

def _render_text_line(buf, text, y, scale=1, color=COL_BLACK, width=800):
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

def _render_outlined_text_line_at(buf, text, x_start, y, scale=1, width=800):
    char_w = 5
    spacing = 1
    
    # 1. Outline pass (white)
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
                                        _set_pixel(buf, x_off + ci*scale + sx + ox, y + ri*scale + sy + oy, COL_WHITE, width)
        x_off += (char_w + spacing) * scale

    # 2. Body pass (black)
    x_off = x_start
    for ch in text:
        glyph = FONT.get(ch.upper(), FONT.get(' ', (0,0,0,0,0)))
        for ci in range(5):
            col_val = glyph[ci]
            for ri in range(7):
                if col_val & (1 << ri):
                    for sx in range(scale):
                        for sy in range(scale):
                            _set_pixel(buf, x_off + ci*scale + sx, y + ri*scale + sy, COL_BLACK, width)
        x_off += (char_w + spacing) * scale

def _render_outlined_text_line(buf, text, y, scale=1, x_center=None, width=800):
    char_w = 5
    spacing = 1
    total_w = len(text) * (char_w + spacing) * scale
    if x_center is None:
        x_start = max(0, (width - total_w) // 2)
    else:
        x_start = max(0, x_center - total_w // 2)
    _render_outlined_text_line_at(buf, text, x_start, y, scale, width)

def _set_pixel_portrait(buf, vx, vy, color, width=800):
    # Visual portrait coords (480 wide x 800 tall) onto the physical 800x480
    # landscape buffer, matching the server's 270-degree portrait packing:
    # visual (vx, vy) -> physical (width-1-vy, vx).
    _set_pixel(buf, width - 1 - vy, vx, color, width)

def _render_outlined_text_line_portrait(buf, text, vy, scale=1, vx_center=None, width=800):
    """Like _render_outlined_text_line but for portrait-packed buffers.
    vy is the visual row (0..799, top of the portrait view = 0)."""
    char_w  = 5
    spacing = 1
    total_w = len(text) * (char_w + spacing) * scale
    if vx_center is None:
        vx_start = max(0, (480 - total_w) // 2)
    else:
        vx_start = max(0, vx_center - total_w // 2)
    outline = [(ox, oy) for ox in (-1, 0, 1) for oy in (-1, 0, 1) if ox or oy]
    for color, offsets in ((COL_WHITE, outline), (COL_BLACK, [(0, 0)])):
        vx_off = vx_start
        for ch in text:
            glyph = FONT.get(ch.upper(), FONT.get(' ', (0, 0, 0, 0, 0)))
            for ci in range(5):
                col_val = glyph[ci]
                for ri in range(7):
                    if col_val & (1 << ri):
                        for ox, oy in offsets:
                            for sx in range(scale):
                                for sy in range(scale):
                                    _set_pixel_portrait(buf, vx_off + ci*scale + sx + ox,
                                                        vy + ri*scale + sy + oy, color, width)
            vx_off += (char_w + spacing) * scale

CRITICAL_BATTERY_PCT = 20
BANNER_H = 14
BANNER_Y = 480 - BANNER_H

def apply_battery_square(buf, battery_pct):
    """Renders a 6x6 square 4px from bottom-right: green 60-100%, yellow 40-60%, red 20-40%.
    Below 20% renders a red banner instead and returns False so callers can shift content up."""
    if battery_pct is None:
        battery_pct = 100
    if battery_pct < CRITICAL_BATTERY_PCT:
        _apply_critical_battery_banner(buf)
        return False
    if battery_pct >= 60:
        color = COL_GREEN
    elif battery_pct >= 40:
        color = COL_YELLOW
    else:
        color = COL_RED
    for dy in range(BAT_SQ_SIZE):
        for dx in range(BAT_SQ_SIZE):
            _set_pixel(buf, BAT_SQ_X + dx, BAT_SQ_Y + dy, color)
    return True

def _apply_critical_battery_banner(buf):
    for y in range(BANNER_Y, 480):
        for x in range(800):
            _set_pixel(buf, x, y, COL_RED)
    msg = 'LOW POWER: REFRESH DISABLED. MANUALLY SKIP IMAGES OR PLUG IN.'
    _render_text_line(buf, msg, BANNER_Y + (BANNER_H - 7) // 2, scale=1, color=COL_WHITE)


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

def apply_caption_overlay(buf, filename, mode, description, is_portrait, battery_pct=None, fw_suffix=None):
    """Paints caption (None, Title, Details, Verbose) centered at the bottom of the canvas.
    Shifts text up by BANNER_H when battery is critical so it clears the banner.
    fw_suffix: optional string appended to title as ' - Firmware:<fw_suffix>' when show_fw_version is set."""
    if not mode or mode == 'none':
        return

    # Shift everything up when the low-power banner occupies the bottom strip.
    shift = BANNER_H if (battery_pct is not None and battery_pct < CRITICAL_BATTERY_PCT) else 0

    # Extract Title text
    base = filename.split('/')[-1]
    if base.endswith('.bin'):
        base = base[:-4]
    for suffix in ['_l_u', '_l_f', '_p_u', '_p_f', '_l', '_p']:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    title = base.replace('_', ' ').upper().strip()
    if fw_suffix:
        title = title + ' - FIRMWARE:' + fw_suffix.upper()

    if mode == 'title':
        _render_outlined_text_line(buf, title, 480 - 18 - shift, scale=1)
    elif mode == 'details':
        desc = description.upper().strip()
        if not desc:
            _render_outlined_text_line(buf, title, 480 - 18 - shift, scale=1)
            return
        if not is_portrait:
            _render_outlined_text_line(buf, desc, 480 - 18 - shift, scale=1)
        else:
            lines = _wrap_text(desc, max_chars=76)[:3]
            if len(lines) == 1:
                _render_outlined_text_line(buf, lines[0], 480 - 18 - shift, scale=1)
            else:
                for i, line in enumerate(lines):
                    y = 480 - 12 - shift - (len(lines) - 1 - i) * 10
                    _render_outlined_text_line(buf, line, y, scale=1)
    elif mode == 'title_details':
        desc = description.upper().strip()
        if not desc:
            _render_outlined_text_line(buf, title, 480 - 18 - shift, scale=1)
            return
        if not is_portrait:
            _render_outlined_text_line(buf, desc, 480 - 12 - shift, scale=1)
            _render_outlined_text_line(buf, title, 480 - 22 - shift, scale=1)
        else:
            lines = _wrap_text(desc, max_chars=76)[:3]
            for i, line in enumerate(lines):
                y = 480 - 12 - shift - (len(lines) - 1 - i) * 10
                _render_outlined_text_line(buf, line, y, scale=1)
            title_y = 480 - 12 - shift - len(lines) * 10
            _render_outlined_text_line(buf, title, title_y, scale=1)

def apply_debug_overlay(buf, version, orient, filename, flipped_l, flipped_p, bat_pct):
    """Paints debug details (Verbose mode) at the bottom of the canvas."""
    v_str = f"V{version or '2.0.0'}"
    o_str = orient.upper()
    
    # Format filename to Title
    base = filename.split('/')[-1]
    if base.endswith('.bin'):
        base = base[:-4]
    for suffix in ['_l_u', '_l_f', '_p_u', '_p_f', '_l', '_p']:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    f_str = base.replace('_', ' ').upper()
    
    fl_str = f"L-FLIP:{'TRUE' if flipped_l else 'FALSE'}"
    fp_str = f"P-FLIP:{'TRUE' if flipped_p else 'FALSE'}"
    b_val = 100 if bat_pct is None else bat_pct
    b_str = f"BATT:{b_val}%"
    
    is_portrait = "portrait" in orient.lower()
    
    if not is_portrait:
        # Landscape: Spread along 1 line
        left_text = f"{v_str}  {o_str}  {f_str}  {fl_str}  {fp_str}"
        _render_outlined_text_line_at(buf, left_text, 8, 480 - 12, scale=1)
        
        bat_w = len(b_str) * 6
        _render_outlined_text_line_at(buf, b_str, 786 - bat_w, 480 - 12, scale=1)
    else:
        # Portrait: Spread along 2 lines
        line1 = f"{v_str}  {f_str}"
        line2 = f"{o_str}  {fl_str}  {fp_str}"
        
        _render_outlined_text_line_at(buf, line1, 8, 480 - 22, scale=1)
        _render_outlined_text_line_at(buf, line2, 8, 480 - 12, scale=1)
        
        bat_w = len(b_str) * 6
        _render_outlined_text_line_at(buf, b_str, 786 - bat_w, 480 - 12, scale=1)
