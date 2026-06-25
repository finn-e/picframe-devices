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

FIRMWARE_VERSION = "0.1.4"

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

def start_ap_portal(timeout_seconds):
    device_id = get_or_create_device_id()
    ap_ssid = "PicFrame - " + device_id
    print("Starting Setup Access Point Portal: SSID = '{}'".format(ap_ssid))
    
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=ap_ssid, authmode=network.AUTH_OPEN)
    
    print("AP started. IP Config:", ap.ifconfig())
    
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(1)
    s.settimeout(2.0)
    
    mac_bytes = wlan.config('mac')
    import ubinascii
    mac_str_clean = ubinascii.hexlify(mac_bytes, ':').decode()
    
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>PicFrame Wi-Fi Setup</title>
    <style>
        body { font-family: sans-serif; background: #0f172a; color: #f1f3f9; padding: 20px; }
        h2 { color: #38bdf8; }
        .card { background: #1e293b; padding: 20px; border-radius: 12px; max-width: 400px; margin: 0 auto; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        input[type=text], input[type=password] { width: 100%; padding: 10px; margin: 10px 0; box-sizing: border-box; background: #0f172a; color: white; border: 1px solid #334155; border-radius: 6px; }
        input[type=submit] { background: #0ea5e9; color: white; border: none; padding: 12px; width: 100%; border-radius: 6px; font-weight: bold; cursor: pointer; }
        input[type=submit]:hover { background: #0284c7; }
    </style>
</head>
<body>
    <div class="card">
        <h2>📷 PicFrame Wi-Fi Config</h2>
        <p style="font-family: monospace; font-size: 0.9rem; color: #38bdf8;">Device ID: {}</p>
        <p style="font-family: monospace; font-size: 0.9rem; color: #38bdf8;">MAC: {}</p>
        <p>Enter the credentials to connect your frame to your local Wi-Fi:</p>
        <form method="POST" action="/save">
            <label>SSID (Network Name):</label>
            <input type="text" name="ssid" placeholder="MyHomeWiFi" required>
            <label>Password:</label>
            <input type="password" name="password" placeholder="••••••••" required>
            <input type="submit" value="Save & Connect">
        </form>
    </div>
</body>
</html>""".format(device_id.upper(), mac_str_clean.upper())

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
            request = conn.recv(1024).decode('utf-8')
            if not request:
                conn.close()
                continue
                
            if "POST /save" in request:
                body = request.split("\r\n\r\n")[-1]
                params = {}
                for param in body.split("&"):
                    if "=" in param:
                        k, v = param.split("=")
                        params[k] = re_url_decode(v)
                        
                ssid = params.get("ssid")
                password = params.get("password")
                
                if ssid:
                    print("Testing Wi-Fi connection to:", ssid)
                    # Attempt connection on STA interface
                    wlan.active(True)
                    wlan.connect(ssid, password or "")
                    
                    connect_success = False
                    test_start = time.time()
                    while time.time() - test_start < 10:
                        if wlan.isconnected():
                            connect_success = True
                            break
                        time.sleep_ms(100)
                        
                    # Always save credentials and reboot (as per A3 logic)
                    wifi_cfg["ssid"] = ssid
                    wifi_cfg["password"] = password or ""
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
                conn.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
                conn.send(html)
                conn.close()
        except OSError:
            pass
            
    s.close()
    ap.active(False)
    
    if config_saved:
        print("Rebooting device...")
        time.sleep_ms(500)
        machine.reset()

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
        create_warning_image("No images found and picFrames server unavailable. Connect to power to change wireless settings.", "/sd/no_images.bin")
        disconnect_wifi_and_refresh("no_images.bin")
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
    if is_usb_connected():
        print("Connection failed and USB power detected. Running AP Portal loop...")
        display_offline_image_once()
        # Keep AP portal open for sleep_time
        start_ap_portal(sleep_time)
        print("AP Portal finished. Attempting to reconnect to settings Wi-Fi...")
        wlan.active(True)
        ssid = wifi_cfg.get("ssid", "")
        password = wifi_cfg.get("password", "")
        if ssid:
            wlan.connect(ssid, password)
            t_start = time.time()
            while not wlan.isconnected() and time.time() - t_start < 10:
                time.sleep_ms(100)
    else:
        print("Connection failed and running on battery.")
        # If no Wi-Fi credentials configured at all (A1)
        if not wifi_cfg.get("ssid"):
            msg = 'Please connect power. Once power is connected, access the "PicFrame-{}" WiFi to set wireless configuration and manual PicFrames-server IP/DNS (The latter only needed if mDNS disabled).'.format(unique_id)
            print("No Wi-Fi credentials on battery. Displaying warning:", msg)
            create_warning_image(msg, "/sd/no_images.bin")
            disconnect_wifi_and_refresh("no_images.bin")
            go_to_sleep(sleep_time)
        else:
            # We have credentials but failed to connect (A2 or offline playback)
            # Check if there are local orientation-matching images
            has_offline_images = False
            current_orient = wifi_cfg.get('orientation', 'landscape')
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
            if files:
                if current_orient == 'landscape':
                    filtered = [f for f in files if '_l.bin' in f or f.endswith('_l.bin')]
                else:
                    filtered = [f for f in files if '_p.bin' in f or f.endswith('_p.bin')]
                if filtered:
                    has_offline_images = True
            
            if has_offline_images:
                print("Local offline images found. Playing slideshow...")
                run_offline_fallback()
            else:
                # No local offline images matching or at all on SD card (A2)
                msg = 'Please connect power supply. Once power is connected, access "PicFrame-{}" WiFi to setup the device.'.format(unique_id)
                print("No offline images on battery. Displaying setup warning:", msg)
                create_warning_image(msg, "/sd/no_images.bin")
                disconnect_wifi_and_refresh("no_images.bin")
                go_to_sleep(sleep_time)

def toggle_orientation():
    print("Toggling orientation...")
    current_orient = wifi_cfg.get('orientation', 'landscape')
    new_orient = 'portrait' if current_orient == 'landscape' else 'landscape'
    wifi_cfg['orientation'] = new_orient
    
    try:
        with open('/sd/wifi_config.json', 'w') as f:
            json.dump(wifi_cfg, f)
        print("Orientation updated locally to:", new_orient)
    except Exception as e:
        print("Failed to save local orientation:", e)
        
    if ensure_wifi_connected():
        base_url = api_url.rsplit('/', 2)[0]
        orient_url = base_url + "/device_orientation"
        reset_url = base_url + "/api/wakeup/reset"
        
        try:
            print("Notifying server: {} -> {}".format(mac_str, new_orient))
            res = requests.post(orient_url, json={"mac": mac_str, "orientation": new_orient}, timeout=5)
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
        if not is_usb_connected():
            elapsed = time.time() - start_awake
            if elapsed > SAFETY_TIMEOUT:
                print("Safety timeout (45s) exceeded inside wait. Sleeping.")
                go_to_sleep(sleep_time)
            
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
        epd.display_file("/sd/" + target_image, battery_level=bat_pct)
        print("Display updated successfully.")
        try:
            with open('/sd/current_image.txt', 'w') as f:
                f.write(target_image)
        except Exception as e:
            print("Failed to save current_image.txt:", e)
    except Exception as e:
        print("Display refresh failed:", e)

# Check for critically low battery on bootup (if on battery)
if not is_usb_connected():
    try:
        from axp import AXP2101
        axp_pmic = AXP2101()
        bat_pct = axp_pmic.get_battery_percentage()
        print("Boot-time battery check percentage:", bat_pct)
        if bat_pct <= 10:
            print("Battery critically low ({}%). Entering shutdown deep sleep...".format(bat_pct))
            msg = "Battery critically low ({}%). Please connect power supply to charge the device.".format(bat_pct)
            create_warning_image(msg, "/sd/no_images.bin")
            disconnect_wifi_and_refresh("no_images.bin")
            go_to_sleep(3600 * 24)
    except Exception as e:
        print("Failed to perform boot battery check:", e)

# Discover central server via mDNS if Wi-Fi connected
if wlan.isconnected():
    discovered_server = discover_server_mdns()
    if discovered_server:
        api_url = discovered_server + "/api/wakeup"
        daily_zip_url = discovered_server + "/api/daily-zip"
        update_url = discovered_server + "/api/update"
        print("Discovered server endpoint dynamically via mDNS:", discovered_server)
else:
    print("No Wi-Fi connection. Handling connection failure.")
    handle_connection_failure()

poll_interval = 15
device_id = wifi_cfg.get("device_id", "picframe_node")

print("Polling server at:", api_url)

while True:
    if not is_usb_connected():
        elapsed = time.time() - start_awake
        if elapsed > SAFETY_TIMEOUT:
            print("Safety timeout (45s) exceeded! Entering deep sleep to protect battery.")
            if wlan.active():
                wlan.active(False)
            go_to_sleep(sleep_time)

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
