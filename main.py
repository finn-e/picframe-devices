import time
import machine
import os
import json
import network
import urequests as requests
import socket
import urandom as random
import ubinascii
from unzip import extract_zip
from epd import EPD_7in3f

# Hardcoded safe fallback
def is_usb_connected():
    try:
        from axp import AXP2101
        axp_pmic = AXP2101()
        return axp_pmic.is_usb_connected()
    except Exception as e:
        print("Failed to read VBUS from PMIC:", e)
        return True

print("--- Frame main loop starting ---")

# Track awake time to enforce the 45s safety timeout
start_awake = time.time()
SAFETY_TIMEOUT = 45 # seconds

# Initialize Button Pins (active Low, with internal pull-ups)
boot_btn = machine.Pin(0, machine.Pin.IN, machine.Pin.PULL_UP)
key_btn = machine.Pin(4, machine.Pin.IN, machine.Pin.PULL_UP)
pwr_btn = machine.Pin(5, machine.Pin.IN, machine.Pin.PULL_DOWN)

# Settle and check buttons immediately on boot (debounced)
time.sleep_ms(100)

boot_pressed_on_boot = False
if boot_btn.value() == 0:
    print("BOOT button detected on boot.")
    boot_pressed_on_boot = True
    while boot_btn.value() == 0:
        time.sleep_ms(10)

key_pressed_on_boot = False
if key_btn.value() == 0:
    print("KEY button detected on boot.")
    key_pressed_on_boot = True
    while key_btn.value() == 0:
        time.sleep_ms(10)

# WLAN configuration and MAC Address resolution
wlan = network.WLAN(network.STA_IF)
mac_bytes = wlan.config('mac')
mac_str = ubinascii.hexlify(mac_bytes, ':').decode()
print("Device MAC Address:", mac_str)

# Load config settings
wifi_cfg = {}
try:
    with open('/sd/wifi_config.json', 'r') as f:
        wifi_cfg = json.load(f)
except Exception:
    try:
        with open('wifi_config.json', 'r') as f:
            wifi_cfg = json.load(f)
    except Exception:
        pass

def get_or_create_device_id():
    device_id = wifi_cfg.get("device_id")
    if not device_id or len(device_id) != 8:
        import urandom
        import ubinascii
        b = bytes([urandom.getrandbits(8) for _ in range(4)])
        device_id = ubinascii.hexlify(b).decode()
        wifi_cfg["device_id"] = device_id
        try:
            with open('/sd/wifi_config.json', 'w') as f:
                json.dump(wifi_cfg, f)
        except Exception:
            pass
        try:
            with open('wifi_config.json', 'w') as f:
                json.dump(wifi_cfg, f)
        except Exception:
            pass
    return device_id

FIRMWARE_VERSION = "0.1.6"

# Default server URLs (will be overridden by mDNS if discovered)
api_url = wifi_cfg.get("api_url", "https://picframes.treee.house/api/wakeup")
daily_zip_url = wifi_cfg.get("daily_zip_url", "https://picframes.treee.house/api/daily-zip")
update_url = wifi_cfg.get("update_url", "https://picframes.treee.house/api/update")
sleep_time = 900 # default 15 minutes

# Try loading from the sync config.json if present on SD
try:
    with open('/sd/config.json', 'r') as f:
        c = json.load(f)
        sleep_time = c.get("timer", sleep_time)
except Exception:
    pass

def go_to_sleep(seconds):
    if is_usb_connected():
        print("USB host detected. Skipping deep sleep to prevent disconnect/reconnect loop.")
        print("Waiting {} seconds instead (REPL/buttons active)...".format(seconds))
        wait_with_button_check(seconds)
        return

    print("Entering deep sleep for {} seconds...".format(seconds))
    try:
        from axp import AXP2101
        axp = AXP2101()
        axp.disable_power()
        print("PMIC power rails disabled for deep sleep.")
    except Exception as e:
        print("Failed to disable PMIC power rails:", e)
    # Configure RTC wakeup timer
    rtc = machine.RTC()
    rtc.datetime() # init RTC
    machine.deepsleep(seconds * 1000)

def ensure_wifi_connected():
    if not wlan.active():
        wlan.active(True)
    if not wlan.isconnected():
        print("Re-connecting to Wi-Fi...")
        ssid = wifi_cfg.get("ssid", "")
        password = wifi_cfg.get("password", "")
        if ssid:
            wlan.connect(ssid, password)
            start_t = time.time()
            while not wlan.isconnected() and time.time() - start_t < 10:
                time.sleep_ms(100)
    return wlan.isconnected()

# Discovery of central server via mDNS query
def discover_server_mdns():
    print("Attempting to discover PicFrames server via mDNS...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 20)
    except Exception:
        pass
        
    # Unicast Response (QU bit) query packet for PTR of _picframes._tcp.local
    packet = b'\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x0b_picframes\x04_tcp\x05local\x00\x00\x0c\x80\x01'
    
    for attempt in range(3):
        try:
            print("Sending mDNS query attempt {}...".format(attempt + 1))
            sock.sendto(packet, ('224.0.0.251', 5353))
            
            start_t = time.time()
            while time.time() - start_t < 2.0:
                data, addr = sock.recvfrom(1024)
                if b'_picframes' in data:
                    port = 8000
                    # Try to parse the port from the SRV record if present
                    idx = data.find(b'\x00\x21\x00\x01')
                    if idx == -1:
                        idx = data.find(b'\x00\x21\x80\x01')
                    if idx != -1:
                        if idx + 16 <= len(data):
                            port = (data[idx+14] << 8) | data[idx+15]
                            print("Parsed port from SRV record:", port)
                    
                    print("Discovered server at:", "http://{}:{}".format(addr[0], port))
                    sock.close()
                    return "http://{}:{}".format(addr[0], port)
        except Exception:
            pass
            
    sock.close()
    return None

FONT = {
    'A': (0x7C, 0x12, 0x11, 0x12, 0x7C),
    'B': (0x7F, 0x49, 0x49, 0x49, 0x36),
    'C': (0x3E, 0x41, 0x41, 0x41, 0x22),
    'D': (0x7F, 0x41, 0x41, 0x22, 0x1C),
    'E': (0x7F, 0x49, 0x49, 0x49, 0x41),
    'F': (0x7F, 0x09, 0x09, 0x09, 0x01),
    'G': (0x3E, 0x41, 0x49, 0x49, 0x7A),
    'H': (0x7F, 0x08, 0x08, 0x08, 0x7F),
    'I': (0x00, 0x41, 0x7F, 0x41, 0x00),
    'J': (0x20, 0x40, 0x41, 0x3F, 0x01),
    'K': (0x7F, 0x08, 0x14, 0x22, 0x41),
    'L': (0x7F, 0x40, 0x40, 0x40, 0x40),
    'M': (0x7F, 0x02, 0x0C, 0x02, 0x7F),
    'N': (0x7F, 0x04, 0x08, 0x10, 0x7F),
    'O': (0x3E, 0x41, 0x41, 0x41, 0x3E),
    'P': (0x7F, 0x09, 0x09, 0x09, 0x06),
    'Q': (0x3E, 0x41, 0x51, 0x21, 0x5E),
    'R': (0x7F, 0x09, 0x19, 0x29, 0x46),
    'S': (0x46, 0x49, 0x49, 0x49, 0x31),
    'T': (0x01, 0x01, 0x7F, 0x01, 0x01),
    'U': (0x3F, 0x40, 0x40, 0x40, 0x3F),
    'V': (0x1F, 0x20, 0x40, 0x20, 0x1F),
    'W': (0x7F, 0x20, 0x18, 0x20, 0x7F),
    'X': (0x63, 0x14, 0x08, 0x14, 0x63),
    'Y': (0x07, 0x08, 0x70, 0x08, 0x07),
    'Z': (0x61, 0x51, 0x49, 0x45, 0x43),
    '0': (0x3E, 0x51, 0x49, 0x45, 0x3E),
    '1': (0x00, 0x42, 0x7F, 0x40, 0x00),
    '2': (0x42, 0x61, 0x51, 0x49, 0x46),
    '3': (0x21, 0x41, 0x45, 0x4B, 0x31),
    '4': (0x18, 0x14, 0x12, 0x7F, 0x10),
    '5': (0x27, 0x45, 0x45, 0x45, 0x39),
    '6': (0x3C, 0x4A, 0x49, 0x49, 0x30),
    '7': (0x01, 0x71, 0x09, 0x05, 0x03),
    '8': (0x36, 0x49, 0x49, 0x49, 0x36),
    '9': (0x06, 0x49, 0x49, 0x29, 0x1E),
    ' ': (0x00, 0x00, 0x00, 0x00, 0x00),
    '.': (0x00, 0x60, 0x60, 0x00, 0x00),
    '-': (0x08, 0x08, 0x08, 0x08, 0x08),
    ':': (0x00, 0x24, 0x24, 0x00, 0x00),
    '/': (0x20, 0x10, 0x08, 0x04, 0x02),
    ',': (0x00, 0x50, 0x30, 0x00, 0x00),
    '(': (0x00, 0x1C, 0x22, 0x41, 0x00),
    ')': (0x00, 0x41, 0x22, 0x1C, 0x00),
    '"': (0x00, 0x07, 0x00, 0x07, 0x00),
}

def re_url_decode(s):
    res = []
    i = 0
    while i < len(s):
        if s[i] == '%' and i + 2 < len(s):
            try:
                char_code = int(s[i+1:i+3], 16)
                res.append(chr(char_code))
                i += 3
            except ValueError:
                res.append(s[i])
                i += 1
        elif s[i] == '+':
            res.append(' ')
            i += 1
        else:
            res.append(s[i])
            i += 1
    return "".join(res)

def draw_text_to_buffer(text_lines, width=800, height=160):
    buf = bytearray(width * height // 2)
    for i in range(len(buf)):
        buf[i] = 0x11
    
    def set_pixel(x, y, color):
        if x < 0 or x >= width or y < 0 or y >= height:
            return
        idx = (y * width + x) // 2
        curr = buf[idx]
        if x % 2 == 0:
            buf[idx] = (curr & 0x0F) | (color << 4)
        else:
            buf[idx] = (curr & 0xF0) | color

    char_w = 6
    char_h = 8
    total_text_h = len(text_lines) * char_h * 3
    y_offset = (height - total_text_h) // 2
    if y_offset < 0:
        y_offset = 0
    
    for line in text_lines:
        line_len = len(line) * char_w
        x_offset = (width - line_len * 2) // 2
        if x_offset < 0:
            x_offset = 0
            
        for char in line:
            glyph = FONT.get(char.upper(), FONT[' '])
            for col_idx in range(5):
                col_val = glyph[col_idx]
                for row_idx in range(7):
                    if (col_val & (1 << row_idx)) != 0:
                        for dx in range(2):
                            for dy in range(2):
                                set_pixel(x_offset + col_idx * 2 + dx, y_offset + row_idx * 2 + dy, 0)
            x_offset += char_w * 2
        y_offset += char_h * 3
        
    return buf

def overlay_portrait_text(buf, text_lines):
    scale = 2
    char_w = 6
    char_h = 8
    line_spacing = 6
    line_height = (char_h + line_spacing) * scale
    
    total_h = len(text_lines) * line_height
    y_offset = 600 + (200 - total_h) // 2
    
    for line in text_lines:
        line_w = len(line) * char_w * scale
        x_offset = (480 - line_w) // 2
        if x_offset < 0:
            x_offset = 0
            
        for char in line:
            glyph = FONT.get(char.upper(), FONT.get(' ', [0]*5))
            for col_idx in range(5):
                col_val = glyph[col_idx]
                for row_idx in range(7):
                    if (col_val & (1 << row_idx)) != 0:
                        for dx in range(scale):
                            for dy in range(scale):
                                px = x_offset + col_idx * scale + dx
                                py = y_offset + row_idx * scale + dy
                                
                                # Map virtual (px, py) to 90 degrees CW rotated (rx, ry)
                                rx = 799 - py
                                ry = px
                                
                                if 0 <= rx < 800 and 0 <= ry < 480:
                                    idx = (ry * 800 + rx) // 2
                                    curr = buf[idx]
                                    if rx % 2 == 0:
                                        buf[idx] = (curr & 0x0F) | 0x10  # white is 1
                                    else:
                                        buf[idx] = (curr & 0xF0) | 0x01  # white is 1
            x_offset += char_w * scale
        y_offset += line_height

def overlay_landscape_text(buf, text_lines):
    scale = 2
    char_w = 6
    char_h = 8
    line_spacing = 4
    line_height = (char_h + line_spacing) * scale
    
    total_h = len(text_lines) * line_height
    y_offset = 360 + (120 - total_h) // 2
    
    for line in text_lines:
        line_w = len(line) * char_w * scale
        x_offset = (800 - line_w) // 2
        if x_offset < 0:
            x_offset = 0
            
        for char in line:
            glyph = FONT.get(char.upper(), FONT.get(' ', [0]*5))
            for col_idx in range(5):
                col_val = glyph[col_idx]
                for row_idx in range(7):
                    if (col_val & (1 << row_idx)) != 0:
                        for dx in range(scale):
                            for dy in range(scale):
                                rx = x_offset + col_idx * scale + dx
                                ry = y_offset + row_idx * scale + dy
                                
                                if 0 <= rx < 800 and 0 <= ry < 480:
                                    idx = (ry * 800 + rx) // 2
                                    curr = buf[idx]
                                    if rx % 2 == 0:
                                        buf[idx] = (curr & 0x0F) | 0x10  # white is 1
                                    else:
                                        buf[idx] = (curr & 0xF0) | 0x01  # white is 1
            x_offset += char_w * scale
        y_offset += line_height

def show_setup_screen(device_id):
    current_orient = wifi_cfg.get('orientation', 'landscape')
    print("Showing setup screen on display in orientation:", current_orient)
    buf = bytearray(192000)
    logo_filename = 'picframes_logo_p.bin' if current_orient == 'portrait' else 'picframes_logo_l.bin'
    
    logo_loaded = False
    for path in ['/images/' + logo_filename, logo_filename, '/sd/images/' + logo_filename]:
        try:
            with open(path, 'rb') as f:
                f.readinto(buf)
            print("Loaded logo from:", path)
            logo_loaded = True
            break
        except Exception:
            pass
            
    if not logo_loaded:
        print("Logo bin not found. Using blank white buffer.")
        for i in range(len(buf)):
            buf[i] = 0x11
            
    if current_orient == 'portrait':
        text_lines = [
            "PLEASE CONNECT POWER SUPPLY",
            "IF NOT CONNECTED.",
            "",
            "ACCESS 'PICFRAME-{}'".format(device_id.upper()),
            "WIFI TO SETUP THE DEVICE."
        ]
        overlay_portrait_text(buf, text_lines)
    else:
        text_lines = [
            "PLEASE CONNECT POWER SUPPLY IF NOT CONNECTED.",
            "ACCESS 'PICFRAME-{}' WIFI".format(device_id.upper()),
            "TO SETUP THE DEVICE."
        ]
        overlay_landscape_text(buf, text_lines)
    
    orient_suffix = '_p' if current_orient.startswith('portrait') else '_l'
    sd_ok = True
    try:
        os.stat('/sd')
    except OSError:
        sd_ok = False
    target_path = ('/sd' if sd_ok else '') + '/no_images' + orient_suffix + '.bin'
        
    try:
        with open(target_path, 'wb') as f:
            f.write(buf)
        print("Setup screen bin written to:", target_path)
    except Exception as e:
        print("Failed to write setup screen bin:", e)
        
    try:
        epd = EPD_7in3f()
        epd.display_file(target_path)
        print("Display updated with setup screen.")
    except Exception as e:
        print("Failed to refresh EPD:", e)

def create_warning_image(message, filepath):
    if not message:
        message = "No images found and picFrames server unavailable. Connect to power to change wireless settings."
    
    words = message.split(" ")
    lines = []
    current_line = []
    current_len = 0
    for word in words:
        if current_len + len(word) + (1 if current_line else 0) <= 55:
            current_line.append(word)
            current_len += len(word) + (1 if current_line else 0)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_len = len(word)
    if current_line:
        lines.append(" ".join(current_line))
        
    text_buf = draw_text_to_buffer(lines, 800, 160)
    row_bytes = 400
    white_row = bytearray([0x11] * row_bytes)
    
    try:
        with open(filepath, 'wb') as f:
            for _ in range(160):
                f.write(white_row)
            f.write(text_buf)
            for _ in range(160):
                f.write(white_row)
        print("Warning image created successfully at:", filepath)
        return True
    except Exception as e:
        print("Failed to create warning image:", e)
        return False

ap_portal_active = False

def dns_server_thread():
    global ap_portal_active
    import socket
    import time
    
    udps = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udps.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    bound = False
    for attempt in range(5):
        try:
            udps.bind(('', 53))
            bound = True
            break
        except Exception as e:
            print("DNS bind attempt {} failed: {}".format(attempt + 1, e))
            time.sleep_ms(200)
            
    if not bound:
        print("DNS Server failed to bind to port 53")
        udps.close()
        return
        
    udps.settimeout(1.0)
    print("DNS Server thread started on port 53")
    
    while ap_portal_active:
        try:
            data, addr = udps.recvfrom(512)
            if not data or len(data) < 12:
                continue
            
            tx_id = data[0:2]
            flags = b'\x81\x80'
            qdcount = data[4:6]
            ancount = b'\x00\x01'
            nscount = b'\x00\x00'
            arcount = b'\x00\x00'
            
            idx = 12
            while idx < len(data):
                length = data[idx]
                if length == 0:
                    idx += 1
                    break
                idx += 1 + length
            
            question_end = idx + 4
            question = data[12:question_end]
            
            ans_name = b'\xc0\x0c'
            ans_type = b'\x00\x01'
            ans_class = b'\x00\x01'
            ans_ttl = b'\x00\x00\x00\x3c'
            ans_len = b'\x00\x04'
            ans_ip = b'\xc0\xa8\x04\x01'
            
            response = tx_id + flags + qdcount + ancount + nscount + arcount + question + ans_name + ans_type + ans_class + ans_ttl + ans_len + ans_ip
            udps.sendto(response, addr)
        except OSError:
            pass
        except Exception as e:
            print("DNS loop error:", e)
            
    udps.close()
    print("DNS Server thread stopped")

def start_ap_portal(timeout_seconds, require_server_ip=False):
    global ap_portal_active
    device_id = get_or_create_device_id()
    ap_ssid = "PicFrame - " + device_id
    print("Starting Setup Access Point Portal: SSID = '{}'".format(ap_ssid))
    
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=ap_ssid, authmode=network.AUTH_OPEN)
    
    print("AP started. IP Config:", ap.ifconfig())
    
    # Start the DNS responder thread
    ap_portal_active = True
    try:
        import _thread
        _thread.start_new_thread(dns_server_thread, ())
    except Exception as e:
        print("Failed to start DNS thread:", e)
        
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(1)
    s.settimeout(0.1)
    mac_bytes = wlan.config('mac')
    import ubinascii
    mac_str_clean = ubinascii.hexlify(mac_bytes, ':').decode()
    
    html_template = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>PicFrame Onboarding</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;700&display=swap');
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Outfit', sans-serif;
            background: radial-gradient(circle at center, hsl(220, 30%, 12%), hsl(220, 35%, 6%));
            color: hsl(220, 20%, 94%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            padding: 32px;
            border-radius: 20px;
            width: 100%;
            max-width: 440px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
            animation: fadeIn 0.6s ease-out;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        h2 {{
            font-weight: 700;
            font-size: 1.8rem;
            margin-bottom: 8px;
            background: linear-gradient(135deg, hsl(190, 100%, 55%), hsl(260, 90%, 65%));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: center;
        }}
        .subtitle {{
            text-align: center;
            font-size: 0.9rem;
            color: hsl(220, 15%, 60%);
            margin-bottom: 24px;
        }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            font-size: 0.85rem;
            font-family: monospace;
            background: rgba(0,0,0,0.2);
            padding: 8px 12px;
            border-radius: 8px;
            margin-bottom: 8px;
            color: hsl(200, 100%, 75%);
        }}
        .status-card {{
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background: rgba(0,0,0,0.15);
        }}
        .status-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 0.9rem;
        }}
        .status-label {{
            color: hsl(220, 10%, 70%);
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .status-value {{
            font-weight: 500;
        }}
        .battery-container {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .battery-outer {{
            width: 50px;
            height: 22px;
            border: 2px solid hsl(220, 15%, 60%);
            border-radius: 4px;
            padding: 2px;
            position: relative;
        }}
        .battery-outer::after {{
            content: '';
            position: absolute;
            right: -5px;
            top: 5px;
            width: 3px;
            height: 8px;
            background: hsl(220, 15%, 60%);
            border-radius: 0 2px 2px 0;
        }}
        .battery-inner {{
            height: 100%;
            border-radius: 2px;
            width: {battery_pct}%;
            background: {battery_color};
            transition: width 0.3s ease;
        }}
        .alert {{
            border-radius: 12px;
            padding: 14px;
            font-size: 0.85rem;
            line-height: 1.4;
            margin-bottom: 20px;
            display: flex;
            align-items: flex-start;
            gap: 10px;
        }}
        .alert-warning {{
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: hsl(0, 85%, 70%);
        }}
        .alert-success {{
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: hsl(140, 75%, 70%);
        }}
        label {{
            display: block;
            font-size: 0.85rem;
            color: hsl(220, 15%, 70%);
            margin-bottom: 6px;
            font-weight: 500;
        }}
        .input-group {{
            margin-bottom: 18px;
            position: relative;
        }}
        input[type=text], input[type=password] {{
            width: 100%;
            padding: 12px 14px;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 10px;
            color: #ffffff;
            font-size: 0.95rem;
            transition: all 0.25s ease;
        }}
        input[type=text]:focus, input[type=password]:focus {{
            outline: none;
            border-color: hsl(190, 100%, 55%);
            box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.15);
            background: rgba(15, 23, 42, 0.8);
        }}
        input[type=submit] {{
            width: 100%;
            padding: 14px;
            border: none;
            border-radius: 10px;
            background: linear-gradient(135deg, hsl(190, 100%, 45%), hsl(260, 90%, 55%));
            color: white;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.25s ease;
            box-shadow: 0 4px 12px rgba(56, 189, 248, 0.2);
            margin-top: 8px;
        }}
        input[type=submit]:hover {{
            background: linear-gradient(135deg, hsl(190, 100%, 50%), hsl(260, 90%, 60%));
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(56, 189, 248, 0.3);
        }}
        input[type=submit]:active {{
            transform: translateY(1px);
        }}
        .error-box {{
            color: hsl(0, 85%, 65%);
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.2);
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            font-size: 0.85rem;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h2>📷 PicFrame Onboarding</h2>
        <div class="subtitle">Device Initialization Portal</div>
        
        <div class="info-row">
            <span>ID: {dev_id}</span>
            <span>MAC: {mac}</span>
        </div>
        
        <div class="status-card">
            <div class="status-item">
                <span class="status-label">🔋 Battery Level</span>
                <div class="battery-container">
                    <span class="status-value">{battery_pct}%</span>
                    <div class="battery-outer">
                        <div class="battery-inner"></div>
                    </div>
                </div>
            </div>
            <div class="status-item">
                <span class="status-label">⚡ Power Source</span>
                <span class="status-value" style="color: {power_color};">{power_source}</span>
            </div>
        </div>
        
        {alert_card}
        {error_msg}
        
        <form method="POST" action="/save">
            <div class="input-group">
                <label>Wi-Fi Network Name (SSID)</label>
                <input type="text" name="ssid" value="{ssid}" placeholder="Enter Wi-Fi SSID" required>
            </div>
            <div class="input-group">
                <label>Wi-Fi Password</label>
                <input type="password" name="password" value="{password}" placeholder="Enter Wi-Fi Password">
            </div>
            <div class="input-group">
                <label>PicFrames Server IP/DNS {req_label}</label>
                <input type="text" name="server_ip" value="{server_ip}" {req_attr} placeholder="e.g. 192.168.1.100:8000">
            </div>
            <input type="submit" value="Save & Configure Frame">
        </form>
    </div>
</body>
</html>"""

    error_msg = ""
    if require_server_ip:
        error_msg = '<div class="error-box">Connected to Wi-Fi but could not discover the PicFrames server via mDNS. Server IP/DNS is required.</div>'
        
    req_label = "(Required)" if require_server_ip else "(Optional)"
    req_attr = "required" if require_server_ip else ""
    
    ssid_val = wifi_cfg.get("ssid", "")
    password_val = wifi_cfg.get("password", "")
    server_ip_val = wifi_cfg.get("server_ip", "")
    
    start_time = time.time()
    config_saved = False
    
    while time.time() - start_time < timeout_seconds:
        # Check buttons to allow reboot / toggle orientation
        if boot_btn.value() == 0:
            time.sleep_ms(50)
            if boot_btn.value() == 0:
                toggle_orientation()
        if key_btn.value() == 0:
            time.sleep_ms(50)
            if key_btn.value() == 0:
                advance_next_image()
                
        try:
            conn, addr = s.accept()
            req_bytes = conn.recv(1024)
            if not req_bytes:
                conn.close()
                continue
            request = req_bytes.decode('utf-8', 'ignore')
            
            # Parse request line to detect captive portal probes
            lines = request.split("\r\n")
            first_line = lines[0] if lines else ""
            parts = first_line.split(" ")
            method = parts[0] if len(parts) > 0 else ""
            path = parts[1] if len(parts) > 1 else ""
            
            is_portal_path = (path == "/" or path.startswith("/?") or path.startswith("/save"))
            is_local_host = ("192.168.4.1" in request)
            
            if not (is_portal_path and is_local_host):
                # Redirect non-portal requests to the portal root
                redirect_resp = (
                    "HTTP/1.1 302 Found\r\n"
                    "Location: http://192.168.4.1/\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n\r\n"
                )
                conn.send(redirect_resp)
                conn.close()
                continue
                
            if "POST /save" in request:
                body = request.split("\r\n\r\n")[-1]
                params = {}
                for param in body.split("&"):
                    if "=" in param:
                        k, v = param.split("=")
                        params[k] = re_url_decode(v)
                        
                ssid = params.get("ssid", "").strip()
                password = params.get("password", "").strip()
                server_ip = params.get("server_ip", "").strip()
                
                if ssid:
                    print("Testing Wi-Fi connection to:", ssid)
                    wlan.active(True)
                    wlan.connect(ssid, password)
                    
                    connect_success = False
                    test_start = time.time()
                    while time.time() - test_start < 10:
                        if wlan.isconnected():
                            connect_success = True
                            break
                        time.sleep_ms(100)
                        
                    # Always save credentials and reboot
                    wifi_cfg["ssid"] = ssid
                    wifi_cfg["password"] = password
                    wifi_cfg["server_ip"] = server_ip
                    wifi_cfg["require_server_ip"] = require_server_ip
                    
                    if server_ip:
                        resolved_ip = server_ip
                        resolved_port = 8000
                        if ":" in resolved_ip:
                            resolved_ip, port_str = resolved_ip.split(":")
                            try: resolved_port = int(port_str)
                            except ValueError: pass
                        wifi_cfg["api_url"] = "http://{}:{}/api/wakeup".format(resolved_ip, resolved_port)
                        wifi_cfg["daily_zip_url"] = "http://{}:{}/api/daily-zip".format(resolved_ip, resolved_port)
                        wifi_cfg["update_url"] = "http://{}:{}/api/update".format(resolved_ip, resolved_port)
                    else:
                        # Clear old manual configs so mDNS is used
                        wifi_cfg.pop("api_url", None)
                        wifi_cfg.pop("daily_zip_url", None)
                        wifi_cfg.pop("update_url", None)
                    
                    try:
                        with open('/sd/wifi_config.json', 'w') as f:
                            json.dump(wifi_cfg, f)
                    except Exception as e:
                        print("Write to SD failed:", e)
                    try:
                        with open('wifi_config.json', 'w') as f:
                            json.dump(wifi_cfg, f)
                    except Exception:
                        pass
                        
                    if connect_success:
                        print("Connection successful! Saving credentials and rebooting...")
                        conn.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
                        conn.send("<html><body><h3>Connection successful! Config saved. Rebooting...</h3></body></html>")
                    else:
                        print("Connection test failed. Saving and rebooting to retry connection...")
                        conn.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
                        conn.send("<html><body><h3>Connection test failed, but credentials saved. Rebooting to retry connection...</h3></body></html>")
                    conn.close()
                    config_saved = True
                    break
            else:
                # Query PMIC state dynamically
                try:
                    from axp import AXP2101
                    axp_pmic = AXP2101()
                    bat_pct = axp_pmic.get_battery_percentage()
                    usb_conn = axp_pmic.is_usb_connected()
                except Exception:
                    bat_pct = 100
                    usb_conn = True

                if bat_pct >= 60:
                    bat_color = "hsl(140, 75%, 50%)"
                elif bat_pct >= 30:
                    bat_color = "hsl(45, 85%, 50%)"
                else:
                    bat_color = "hsl(10, 80%, 55%)"

                if usb_conn:
                    power_source = "USB Power"
                    power_color = "hsl(140, 75%, 65%)"
                    alert_card = """
                    <div class="alert alert-success">
                        <span>🔌</span>
                        <div>
                            <strong>USB Power Connected</strong><br>
                            Perfect! Keep the device plugged in to ensure a successful onboarding process.
                        </div>
                    </div>
                    """
                else:
                    power_source = "Battery"
                    power_color = "hsl(45, 85%, 60%)"
                    alert_card = """
                    <div class="alert alert-warning">
                        <span>⚠️</span>
                        <div>
                            <strong>USB Power Disconnected!</strong><br>
                            Please plug the frame into USB power during setup to prevent it from shutting down.
                        </div>
                    </div>
                    """

                html = html_template.format(
                    dev_id=device_id.upper(),
                    mac=mac_str_clean.upper(),
                    battery_pct=bat_pct,
                    battery_color=bat_color,
                    power_source=power_source,
                    power_color=power_color,
                    alert_card=alert_card,
                    error_msg=error_msg,
                    ssid=ssid_val,
                    password=password_val,
                    server_ip=server_ip_val,
                    req_label=req_label,
                    req_attr=req_attr
                )
                conn.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
                conn.send(html)
                conn.close()
        except OSError:
            pass
            
    s.close()
    ap_portal_active = False
    ap.active(False)
    
    if config_saved:
        print("Rebooting device...")
        time.sleep_ms(500)
        machine.reset()

def run_bootstrap_sequence():
    print("Initializing bootstrap sequence...")
    unique_id = get_or_create_device_id()

    # Determine if an SD card is present (needed for warning image path choices)
    sd_present = False
    try:
        os.stat("/sd")
        sd_present = True
    except OSError:
        pass

    global wifi_cfg
    ssid = wifi_cfg.get("ssid", "")
    password = wifi_cfg.get("password", "")
    server_ip = wifi_cfg.get("server_ip", "")
    require_ip = wifi_cfg.get("require_server_ip", False)

    # --- Helper: word-wrap a message into lines ---
    def _wrap(message, max_chars=55):
        words = message.split(" ")
        lines, cur, cur_len = [], [], 0
        for w in words:
            need = len(w) + (1 if cur else 0)
            if cur_len + need <= max_chars:
                cur.append(w); cur_len += need
            else:
                lines.append(" ".join(cur)); cur = [w]; cur_len = len(w)
        if cur: lines.append(" ".join(cur))
        return lines

    # --- Helper: overlay message text on an existing 192KB bin ---
    def _overlay_on_bin(message, src_path, out_path):
        """Read a 192KB bin, paint a white band + black text over centre, write out."""
        try:
            with open(src_path, 'rb') as f:
                buf = bytearray(f.read())
            if len(buf) != 192000:
                return False
            lines = _wrap(message)
            char_h = 8
            total_h = len(lines) * char_h * 3
            y_bar_top = max(0, (480 - total_h) // 2 - 15)
            y_bar_bot = min(480, y_bar_top + total_h + 30)
            for y in range(y_bar_top, y_bar_bot):  # white band
                for xb in range(400):
                    buf[y * 400 + xb] = 0x11
            def set_px(x, y, col):
                if 0 <= x < 800 and 0 <= y < 480:
                    idx = y * 400 + x // 2
                    b = buf[idx]
                    buf[idx] = (b & 0x0F) | (col << 4) if x % 2 == 0 else (b & 0xF0) | col
            y_off = max(0, (480 - total_h) // 2)
            for line in lines:
                x_off = max(0, (800 - len(line) * 12) // 2)
                for ch in line:
                    glyph = FONT.get(ch.upper(), FONT[' '])
                    for ci in range(5):
                        cv = glyph[ci]
                        for ri in range(7):
                            if cv & (1 << ri):
                                for dx in range(2):
                                    for dy in range(2):
                                        set_px(x_off + ci*2+dx, y_off + ri*2+dy, 0)
                    x_off += 12
                y_off += char_h * 3
            with open(out_path, 'wb') as f:
                f.write(buf)
            return True
        except Exception as e:
            print("Overlay failed:", e)
            return False

    # --- Helper: paint using random-bin overlay, or fall back to white screen ---
    def _paint_message_smart(message):
        _orient = wifi_cfg.get('orientation', 'landscape')
        _osuf = '_p' if _orient.startswith('portrait') else '_l'
        out_path = ("/sd" if sd_present else "") + "/no_images" + _osuf + ".bin"
        overlaid = False
        if sd_present:
            try:
                bins = [f for f in os.listdir('/sd')
                        if f.endswith('.bin') and 'no_images' not in f and 'warning' not in f]
                if bins:
                    chosen = bins[random.getrandbits(8) % len(bins)]
                    print("Overlaying message on:", chosen)
                    overlaid = _overlay_on_bin(message, '/sd/' + chosen, out_path)
            except Exception as e:
                print("Bin overlay error:", e)
        if not overlaid:
            create_warning_image(message, out_path)
        try:
            epd = EPD_7in3f()
            epd.display_file(out_path, battery_level=None)
            try: os.remove(out_path)
            except Exception: pass
        except Exception as e:
            print("EPD paint failed:", e)

    # --- Helper: white-screen paint (for USB portal instructions) ---
    def _bootstrap_paint(message):
        _orient = wifi_cfg.get('orientation', 'landscape')
        _osuf = '_p' if _orient.startswith('portrait') else '_l'
        out_path = ("/sd" if sd_present else "") + "/no_images" + _osuf + ".bin"
        create_warning_image(message, out_path)
        try:
            epd = EPD_7in3f()
            epd.display_file(out_path, battery_level=None)
            try: os.remove(out_path)
            except Exception: pass
        except Exception as e:
            print("EPD paint failed:", e)

    wlan.active(True)
    connected = False
    if ssid:
        print("Connecting to Wi-Fi:", ssid)
        wlan.connect(ssid, password)
        t_start = time.time()
        while not wlan.isconnected() and time.time() - t_start < 10:
            time.sleep_ms(100)
        connected = wlan.isconnected()

    resolved_ip = None
    resolved_port = 8000

    if connected:
        print("Connected to Wi-Fi successfully!")
        if server_ip:
            print("Using manual server IP:", server_ip)
            resolved_ip = server_ip
            if ":" in resolved_ip:
                resolved_ip, port_str = resolved_ip.split(":")
                try: resolved_port = int(port_str)
                except ValueError: pass
        else:
            discovered = discover_server_mdns()
            if discovered:
                print("Discovered server:", discovered)
                host_port = discovered.split("//")[-1]
                resolved_ip = host_port
                if ":" in host_port:
                    resolved_ip, port_str = host_port.split(":")
                    try: resolved_port = int(port_str)
                    except ValueError: pass
            else:
                print("mDNS discovery failed.")
                require_ip = True

    if resolved_ip:
        bs_update_url = "http://{}:{}/api/update".format(resolved_ip, resolved_port)
        print("Downloading firmware update from:", bs_update_url)
        try:
            import urequests as requests
            res = requests.get(bs_update_url, timeout=15)
            if res.status_code == 200:
                zip_path = "/sd/update.zip" if sd_present else "update.zip"
                with open(zip_path, 'wb') as f:
                    chunk = bytearray(1024)
                    while True:
                        n = res.raw.readinto(chunk)
                        if not n: break
                        f.write(chunk if n == len(chunk) else chunk[:n])
                res.close()
                print("Downloaded update.zip. Extracting...")

                target_dir = "/sd" if sd_present else ""
                extract_zip(zip_path, target_dir)
                os.remove(zip_path)
                print("Firmware extracted.")

                mac_bytes = wlan.config('mac')
                import ubinascii
                dev_id = ubinascii.hexlify(mac_bytes[-4:]).decode()

                wifi_config_new = {
                    "ssid": ssid,
                    "password": password,
                    "device_id": dev_id,
                    "api_url": "http://{}:{}/api/wakeup".format(resolved_ip, resolved_port),
                    "daily_zip_url": "http://{}:{}/api/daily-zip".format(resolved_ip, resolved_port),
                    "update_url": "http://{}:{}/api/update".format(resolved_ip, resolved_port),
                    "orientation": "landscape",
                    "server_ip": resolved_ip + (":" + str(resolved_port) if resolved_port != 80 else "")
                }

                cfg_path = "/sd/wifi_config.json" if sd_present else "wifi_config.json"
                with open(cfg_path, 'w') as f:
                    json.dump(wifi_config_new, f)
                print("Saved wifi_config.json.")

                print("Bootstrap complete. Rebooting device...")
                time.sleep(1.0)
                machine.reset()
            else:
                print("Server error:", res.status_code)
                res.close()
                require_ip = True
        except Exception as e:
            print("Download failed:", e)
            require_ip = True
    # --- Step 3: No server found — Display setup screen and start AP portal ---
    show_setup_screen(unique_id)
    start_ap_portal(sleep_time, require_server_ip=require_ip)

def display_offline_image_once():
    current_orient = wifi_cfg.get('orientation', 'landscape')
    print("Displaying offline image for orientation:", current_orient)
    
    files = []
    try:
        with open('/sd/index.json', 'r') as f:
            files = json.load(f)
    except Exception:
        try:
            with open('/sd/list.json', 'r') as f:
                files = json.load(f)
        except Exception:
            pass
            
    if not files:
        try:
            files = [f for f in os.listdir('/sd') if f.endswith('.bin')]
        except Exception:
            pass
            
    if not files:
        print("No image bin files found on SD card!")
        # Create and display warning image
        _orient = wifi_cfg.get('orientation', 'landscape')
        _osuf = '_p' if _orient.startswith('portrait') else '_l'
        _warn_path = "/sd/no_images" + _osuf + ".bin"
        create_warning_image("No images found and picFrames server unavailable. Connect to power to change wireless settings.", _warn_path)
        disconnect_wifi_and_refresh(_warn_path)
        return

    # Filter files based on orientation
    if current_orient == 'landscape':
        filtered_files = [f for f in files if '_l.bin' in f or f.endswith('_l.bin')]
    else:
        filtered_files = [f for f in files if '_p.bin' in f or f.endswith('_p.bin')]
        
    if not filtered_files:
        print("No files matching orientation found, falling back to all files.")
        filtered_files = files
        
    current_displayed = ""
    try:
        with open('/sd/current_image.txt', 'r') as f:
            current_displayed = f.read().strip()
    except Exception:
        pass
        
    shuffle = False
    try:
        with open('/sd/config.json', 'r') as f:
            c = json.load(f)
            shuffle = c.get("shuffle", shuffle)
    except Exception:
        pass
        
    target_image = None
    if shuffle:
        target_image = filtered_files[random.getrandbits(12) % len(filtered_files)]
    else:
        try:
            idx = filtered_files.index(current_displayed)
            target_image = filtered_files[(idx + 1) % len(filtered_files)]
        except ValueError:
            target_image = filtered_files[0]
            
    if target_image:
        print("Selected offline image:", target_image)
        if target_image != current_displayed:
            disconnect_wifi_and_refresh(target_image)
        else:
            print("Target image already displayed.")

def run_offline_fallback():
    print("Falling back to local offline slideshow...")
    display_offline_image_once()
    
    offline_sleep = 900
    try:
        with open('/sd/config.json', 'r') as f:
            c = json.load(f)
            offline_sleep = c.get("timer", offline_sleep)
    except Exception:
        pass
        
    go_to_sleep(offline_sleep)

def handle_connection_failure():
    unique_id = get_or_create_device_id()
    print("Connection failed or server unreachable. Running AP Portal loop...")
    show_setup_screen(unique_id)
    # Start the AP portal. Require server IP if Wi-Fi connected but server unreachable
    start_ap_portal(sleep_time, require_server_ip=wlan.isconnected())
    print("AP Portal finished. Attempting to reconnect to settings Wi-Fi...")
    wlan.active(True)
    ssid = wifi_cfg.get("ssid", "")
    password = wifi_cfg.get("password", "")
    if ssid:
        wlan.connect(ssid, password)
        t_start = time.time()
        while not wlan.isconnected() and time.time() - t_start < 10:
            time.sleep_ms(100)

def toggle_orientation():
    print("Toggling orientation...")
    current_orient = wifi_cfg.get('orientation', 'landscape')
    
    orient_cycle = {
        'portrait': 'landscape',
        'landscape': 'portrait-upside-down',
        'portrait-upside-down': 'landscape-upside-down',
        'landscape-upside-down': 'portrait'
    }
    new_orient = orient_cycle.get(current_orient, 'landscape')
    wifi_cfg['orientation'] = new_orient
    
    try:
        with open('/sd/wifi_config.json', 'w') as f:
            json.dump(wifi_cfg, f)
        print("Orientation updated locally to SD config:", new_orient)
    except Exception as e:
        print("Failed to save local orientation to SD config:", e)
        
    try:
        with open('/wifi_config.json', 'w') as f:
            json.dump(wifi_cfg, f)
        print("Orientation updated locally to Flash config:", new_orient)
    except Exception as e:
        print("Failed to save local orientation to Flash config:", e)
        
    if ensure_wifi_connected():
        base_url = api_url.rsplit('/', 2)[0]
        orient_url = base_url + "/device_orientation"
        reset_url = base_url + "/api/wakeup/reset"
        
        server_orient = 'portrait' if 'portrait' in new_orient else 'landscape'
        try:
            print("Notifying server: {} -> {}".format(mac_str, server_orient))
            res = requests.post(orient_url, json={"mac": mac_str, "orientation": server_orient}, timeout=5)
            print("Server response:", res.text)
            res.close()
            
            print("Resetting server wakeup state...")
            res2 = requests.post(reset_url, timeout=5)
            print("Server response:", res2.text)
            res2.close()
        except Exception as e:
            print("Failed to notify server of orientation change:", e)
    else:
        print("Cannot update server (no Wi-Fi).")
        
    print("Rebooting device...")
    time.sleep_ms(500)
    machine.reset()

def advance_next_image():
    print("Advancing next image...")
    if ensure_wifi_connected():
        base_url = api_url.rsplit('/', 2)[0]
        next_url = base_url + "/api/wakeup/next"
        try:
            print("Notifying server to advance slideshow...")
            res = requests.post(next_url, timeout=5)
            print("Server response:", res.text)
            res.close()
        except Exception as e:
            print("Failed to notify server:", e)
    else:
        print("Cannot notify server (no Wi-Fi).")
        
    print("Rebooting device...")
    time.sleep_ms(500)
    machine.reset()

def wait_with_button_check(seconds):
    start = time.time()
    while time.time() - start < seconds:

        if boot_btn.value() == 0:
            time.sleep_ms(50)
            if boot_btn.value() == 0:
                while boot_btn.value() == 0:
                    time.sleep_ms(10)
                toggle_orientation()
                
        if key_btn.value() == 0:
            time.sleep_ms(50)
            if key_btn.value() == 0:
                while key_btn.value() == 0:
                    time.sleep_ms(10)
                advance_next_image()
                
        if pwr_btn.value() == 1:
            time.sleep_ms(50)
            if pwr_btn.value() == 1:
                while pwr_btn.value() == 1:
                    time.sleep_ms(10)
                print("PWR button pressed. Rebooting to force sync check-in...")
                machine.reset()
                
        time.sleep_ms(50)

# Check if orientation toggle or image skip was requested at boot
if boot_pressed_on_boot:
    toggle_orientation()

if key_pressed_on_boot:
    advance_next_image()

def disconnect_wifi_and_refresh(target_image):
    if wlan.isconnected():
        print("Disconnecting Wi-Fi to prevent power brownout during refresh...")
        wlan.active(False)
    
    bat_pct = None
    try:
        from axp import AXP2101
        axp_pmic = AXP2101()
        bat_pct = axp_pmic.get_battery_percentage()
        print("Current battery percentage:", bat_pct)
    except Exception as e:
        print("Failed to read battery percentage during refresh:", e)
        
    try:
        epd = EPD_7in3f()
        print("Writing to display:", target_image)
        img_path = target_image
        if not target_image.startswith("/"):
            img_path = "/sd/" + target_image
        epd.display_file(img_path, battery_level=bat_pct)
        print("Display updated successfully.")
        try:
            with open('/sd/current_image.txt', 'w') as f:
                f.write(target_image)
        except Exception as e:
            print("Failed to save current_image.txt:", e)
    except Exception as e:
        print("Display refresh failed:", e)

# Check if running as bootstrap loader (if /sd/main.py is missing)
sd_main_exists = False
try:
    os.stat('/sd/main.py')
    sd_main_exists = True
except OSError:
    pass

if not sd_main_exists:
    print("SD card empty/missing or running from internal Flash. Initiating bootstrap loader...")
    run_bootstrap_sequence()
    import sys
    sys.exit(0)

def get_first_appropriate_image():
    for path in ['/sd/index.json', '/sd/list.json']:
        try:
            with open(path, 'r') as f:
                img_list = json.load(f)
                if isinstance(img_list, list) and len(img_list) > 0:
                    img_name = img_list[0]
                    if img_name.endswith('.bin'):
                        try:
                            os.stat('/sd/' + img_name)
                            return img_name
                        except OSError:
                            pass
        except Exception:
            pass
    try:
        current_orient = wifi_cfg.get('orientation', 'landscape')
        suffix = '_l.bin' if current_orient == 'landscape' else '_p.bin'
        files = [f for f in os.listdir('/sd') if f.endswith(suffix)]
        if files:
            files.sort()
            return files[0]
    except Exception:
        pass
    # Fallback to internal Flash /images/ folder if SD card has no matching files
    try:
        current_orient = wifi_cfg.get('orientation', 'landscape')
        suffix = '_l.bin' if current_orient == 'landscape' else '_p.bin'
        files = [f for f in os.listdir('/images') if f.endswith(suffix)]
        if files:
            files.sort()
            return '/images/' + files[0]
    except Exception:
        pass
    return None

def run_startup_sync_sequence():
    global sleep_time
    print("Starting server check-in and update sequence...")
    dev_id = wifi_cfg.get("device_id", "picframe_node")
    
    # 1. Check for update
    try:
        payload = {"device_id": dev_id, "mac": mac_str, "version": FIRMWARE_VERSION}
        res = requests.post(api_url, json=payload, headers={"Content-Type": "application/json"}, timeout=5)
        response_text = res.text.strip()
        res.close()
        print("Startup check-in response:", response_text)
        
        if response_text.startswith("UPDATE"):
            print("Firmware update available! Downloading ZIP...")
            res = requests.get(update_url, timeout=10)
            zip_path = "/sd/update.zip"
            try:
                os.stat("/sd")
            except OSError:
                zip_path = "update.zip"
                
            with open(zip_path, 'wb') as f:
                chunk = bytearray(2048)
                while True:
                    n = res.raw.readinto(chunk)
                    if not n:
                        break
                    f.write(chunk if n == len(chunk) else chunk[:n])
            res.close()
            
            print("Extracting update to Flash...")
            extract_zip(zip_path, "")
            os.remove(zip_path)
            
            # Mirror wifi_config.json to Flash
            try:
                with open('/sd/wifi_config.json', 'r') as src:
                    cfg_data = json.load(src)
                with open('/wifi_config.json', 'w') as dst:
                    json.dump(cfg_data, dst)
                print("Mirrored wifi_config.json to internal Flash.")
            except Exception as e:
                print("Failed to mirror wifi_config.json:", e)
                
            print("Soft-resetting device to run updated code...")
            time.sleep_ms(500)
            machine.soft_reset()
    except Exception as e:
        print("Startup update check failed:", e)
        
    # 2. Pull daily-zip
    print("Requesting daily-zip from server...")
    try:
        url_with_mac = daily_zip_url + "?mac=" + mac_str
        res = requests.get(url_with_mac, timeout=10)
        zip_path = "/sd/daily.zip"
        with open(zip_path, 'wb') as f:
            chunk = bytearray(2048)
            while True:
                n = res.raw.readinto(chunk)
                if not n:
                    break
                f.write(chunk if n == len(chunk) else chunk[:n])
        res.close()
        print("Downloaded daily.zip successfully. Extracting to /sd...")
        
        extract_zip(zip_path, "/sd")
        os.remove(zip_path)
        print("Daily-zip sync completed successfully.")
        
        try:
            with open('/sd/config.json', 'r') as f:
                c = json.load(f)
                sleep_time = c.get("timer", sleep_time)
                print("Updated sleep_time to:", sleep_time)
        except Exception:
            pass
    except Exception as e:
        print("Daily-zip pull or extraction failed:", e)
        
    # 3. Display the first appropriate image
    first_img = get_first_appropriate_image()
    if first_img:
        print("First appropriate image to display:", first_img)
        disconnect_wifi_and_refresh(first_img)
    else:
        print("No appropriate images found after sync.")
        
    # 4. Go to deep sleep
    print("Startup sync complete. Entering deep sleep for:", sleep_time)
    go_to_sleep(sleep_time)

# Discover central server via mDNS if Wi-Fi connected
if wlan.isconnected():
    discovered_server = discover_server_mdns()
    if discovered_server:
        api_url = discovered_server + "/api/wakeup"
        daily_zip_url = discovered_server + "/api/daily-zip"
        update_url = discovered_server + "/api/update"
        print("Discovered server endpoint dynamically via mDNS:", discovered_server)
        
        # Run startup sync and sleep
        run_startup_sync_sequence()
    else:
        print("mDNS discovery failed. Handling server discovery failure.")
        handle_connection_failure()
else:
    print("No Wi-Fi connection. Handling connection failure.")
    handle_connection_failure()

poll_interval = 15
device_id = wifi_cfg.get("device_id", "picframe_node")

print("Polling server at:", api_url)

while True:
    wifi_ok = ensure_wifi_connected()
    if not wifi_ok:
        print("Wi-Fi down. Handling connection failure.")
        handle_connection_failure()
        continue

    # Poll wakeup API sending MAC address
    try:
        payload = {"device_id": device_id, "mac": mac_str, "version": FIRMWARE_VERSION}
        res = requests.post(api_url, json=payload, headers={"Content-Type": "application/json"}, timeout=5)
        response_text = res.text.strip()
        res.close()
        print("Wakeup response:", response_text)
    except Exception as e:
        print("HTTP request failed:", e)
        handle_connection_failure()
        continue

    # Parse response
    remaining = None
    parts = [p.strip() for p in response_text.split(" - ")]
    if len(parts) >= 2:
        status = parts[0]
        target_image = parts[1]
        if len(parts) >= 3:
            try:
                remaining = int(parts[2])
            except ValueError:
                pass
    else:
        status = response_text.strip()
        target_image = "None"

    if status == "DEBUG":
        poll_interval = 10
        print("[SERVER DEBUG MODE] Active. Wi-Fi kept alive, e-paper bypassed.")
        wait_with_button_check(poll_interval)
        continue

    if status == "UPDATE":
        print("Firmware update available! Downloading ZIP from:", update_url)
        try:
            res = requests.get(update_url, timeout=10)
            zip_path = "/sd/update.zip"
            try:
                os.stat("/sd")
            except OSError:
                zip_path = "update.zip"
            
            with open(zip_path, 'wb') as f:
                chunk = bytearray(2048)
                while True:
                    n = res.raw.readinto(chunk)
                    if not n:
                        break
                    f.write(chunk if n == len(chunk) else chunk[:n])
            res.close()
            print("Downloaded firmware update. Extracting...")
            extract_zip(zip_path, "")
            os.remove(zip_path)
            print("Firmware update extracted successfully! Soft-rebooting...")
            time.sleep(0.5)
            machine.soft_reset()
        except Exception as e:
            print("Firmware update failed:", e)
        continue

    # Sync trigger check
    force_redownload = "REDOWNLOAD" in response_text

    if target_image and target_image != "None" and target_image.endswith(".bin"):
        local_path = "/sd/" + target_image
        image_exists = False
        try:
            os.stat(local_path)
            image_exists = True
        except OSError:
            pass

        if not image_exists or force_redownload:
            print("Target image missing or sync triggered by REDOWNLOAD. Downloading daily-zip...")
            try:
                url_with_mac = daily_zip_url + "?mac=" + mac_str
                print("Downloading ZIP from:", url_with_mac)
                res = requests.get(url_with_mac, timeout=10)
                zip_path = "/sd/daily.zip"
                
                with open(zip_path, 'wb') as f:
                    chunk = bytearray(2048)
                    while True:
                        n = res.raw.readinto(chunk)
                        if not n:
                            break
                        f.write(chunk if n == len(chunk) else chunk[:n])
                res.close()
                print("Downloaded daily.zip successfully. Extracting...")
                
                extract_zip(zip_path, "/sd")
                os.remove(zip_path)
                print("Sync complete.")
                
                try:
                    with open('/sd/config.json', 'r') as f:
                        c = json.load(f)
                        sleep_time = c.get("timer", sleep_time)
                except Exception:
                    pass
            except Exception as e:
                print("Sync failed:", e)
                handle_connection_failure()
                continue

    if status == "WAIT":
        current_displayed = ""
        try:
            with open('/sd/current_image.txt', 'r') as f:
                current_displayed = f.read().strip()
        except OSError:
            pass
            
        if remaining is not None:
            print("Status: WAIT. Remaining sleep: {}s. Target: {}".format(remaining, target_image))
            if target_image and target_image != "None" and target_image.endswith(".bin"):
                if target_image != current_displayed:
                    print("Refreshing screen first...")
                    disconnect_wifi_and_refresh(target_image)
            
            if wlan.active():
                wlan.active(False)
            go_to_sleep(remaining)
        else:
            poll_interval = 15
            print("Status: WAIT (GATHERING). Polling every 15s...")
            wait_with_button_check(poll_interval)
            
    elif status == "READY":
        poll_interval = 1
        print("Status: READY. Fast polling (1s)...")
        wait_with_button_check(poll_interval)
        
    elif status == "CHANGE":
        print("Status: CHANGE. Commencing e-paper refresh...")
        if target_image and target_image != "None" and target_image.endswith(".bin"):
            disconnect_wifi_and_refresh(target_image)
        
        if wlan.active():
            wlan.active(False)
        go_to_sleep(sleep_time)
        
    else:
        print("Unknown status: {}. Handling connection failure.".format(status))
        handle_connection_failure()
