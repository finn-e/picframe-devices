import sys
import os
import time
import machine
import network
import socket
import json
import ubinascii
from unzip import extract_zip

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

# Check if SD card is mounted
sd_mounted = False
try:
    os.stat('/sd')
    sd_mounted = True
except OSError:
    pass

# Check if main app exists on SD card
sd_main_exists = False
if sd_mounted:
    try:
        os.stat('/sd/main.py')
        sd_main_exists = True
    except OSError:
        pass

if sd_main_exists:
    print("Booting main app from SD card...")
    if '/sd' not in sys.path:
        sys.path.append('/sd')
    # Run the main app
    exec(open('/sd/main.py').read(), globals())
else:
    # Run bootstrap logic
    print("Running bootstrap logic...")

    FONT = {
        ' ': [0,0,0,0,0],
        'A': [0x7E,0x11,0x11,0x11,0x7E],'B': [0x7F,0x49,0x49,0x49,0x36],
        'C': [0x3E,0x41,0x41,0x41,0x22],'D': [0x7F,0x41,0x41,0x22,0x1C],
        'E': [0x7F,0x49,0x49,0x49,0x41],'F': [0x7F,0x09,0x09,0x09,0x01],
        'G': [0x3E,0x41,0x49,0x49,0x7A],'H': [0x7F,0x08,0x08,0x08,0x7F],
        'I': [0x00,0x41,0x7F,0x41,0x00],'J': [0x20,0x40,0x41,0x3F,0x01],
        'K': [0x7F,0x08,0x14,0x22,0x41],'L': [0x7F,0x40,0x40,0x40,0x40],
        'M': [0x7F,0x02,0x0C,0x02,0x7F],'N': [0x7F,0x04,0x08,0x10,0x7F],
        'O': [0x3E,0x41,0x41,0x41,0x3E],'P': [0x7F,0x09,0x09,0x09,0x06],
        'Q': [0x3E,0x41,0x51,0x21,0x5E],'R': [0x7F,0x09,0x19,0x29,0x46],
        'S': [0x46,0x49,0x49,0x49,0x31],'T': [0x01,0x01,0x7F,0x01,0x01],
        'U': [0x3F,0x40,0x40,0x40,0x3F],'V': [0x1F,0x20,0x40,0x20,0x1F],
        'W': [0x3F,0x40,0x38,0x40,0x3F],'X': [0x63,0x14,0x08,0x14,0x63],
        'Y': [0x07,0x08,0x70,0x08,0x07],'Z': [0x61,0x51,0x49,0x45,0x43],
        '0': [0x3E,0x51,0x49,0x45,0x3E],'1': [0x00,0x42,0x7F,0x40,0x00],
        '2': [0x42,0x61,0x51,0x49,0x46],'3': [0x21,0x41,0x45,0x4B,0x31],
        '4': [0x18,0x14,0x12,0x7F,0x10],'5': [0x27,0x45,0x45,0x45,0x39],
        '6': [0x3C,0x4A,0x49,0x49,0x30],'7': [0x01,0x71,0x09,0x05,0x03],
        '8': [0x36,0x49,0x49,0x49,0x36],'9': [0x06,0x49,0x49,0x29,0x1E],
        '.': [0x00,0x60,0x60,0x00,0x00],',': [0x00,0x50,0x30,0x00,0x00],
        ':': [0x00,0x36,0x36,0x00,0x00],'-': [0x08,0x08,0x08,0x08,0x08],
        '/': [0x20,0x10,0x08,0x04,0x02],'!': [0x00,0x00,0x5F,0x00,0x00],
        '"': [0x00,0x07,0x00,0x07,0x00],'(': [0x00,0x1C,0x22,0x41,0x00],
        ')': [0x00,0x41,0x22,0x1C,0x00],'_': [0x40,0x40,0x40,0x40,0x40],
    }

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

    def show_setup_screen(device_id):
        print("Showing setup screen on display...")
        buf = bytearray(192000)
        logo_loaded = False
        for path in ['/picframes_logo.bin', 'picframes_logo.bin', '/sd/picframes_logo.bin']:
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
                
        text_lines = [
            "PLEASE CONNECT POWER SUPPLY",
            "IF NOT CONNECTED.",
            "",
            "ACCESS 'PICFRAME-{}'".format(device_id.upper()),
            "WIFI TO SETUP THE DEVICE."
        ]
        
        overlay_portrait_text(buf, text_lines)
        
        target_path = '/sd/no_images.bin' if sd_mounted else '/no_images.bin'
        try:
            with open(target_path, 'wb') as f:
                f.write(buf)
            print("Setup screen bin written to:", target_path)
        except Exception as e:
            print("Failed to write setup screen bin:", e)
            
        try:
            from epd import EPD_7in3f
            epd = EPD_7in3f()
            epd.display_file(target_path)
            print("Display updated with setup screen.")
        except Exception as e:
            print("Failed to refresh EPD:", e)

    # Helper: check USB/VBUS power via AXP2101 PMIC
    def _is_usb_connected():
        try:
            from axp import AXP2101
            axp_pmic = AXP2101()
            return axp_pmic.is_usb_connected()
        except Exception:
            return True  # safe default: assume USB

    # Helper: paint a message to the EPD
    def _paint_message(message, bin_path):
        try:
            # Build a minimal white 800x480 4bpp frame with text
            width, height = 800, 480
            row_bytes = 400  # 800 pixels / 2 (4bpp packed)
            buf = bytearray(width * height // 2)
            for i in range(len(buf)):
                buf[i] = 0x11  # white (color 1 = white)

            FONT = {
                ' ': [0,0,0,0,0],
                'A': [0x7E,0x11,0x11,0x11,0x7E],'B': [0x7F,0x49,0x49,0x49,0x36],
                'C': [0x3E,0x41,0x41,0x41,0x22],'D': [0x7F,0x41,0x41,0x22,0x1C],
                'E': [0x7F,0x49,0x49,0x49,0x41],'F': [0x7F,0x09,0x09,0x09,0x01],
                'G': [0x3E,0x41,0x49,0x49,0x7A],'H': [0x7F,0x08,0x08,0x08,0x7F],
                'I': [0x00,0x41,0x7F,0x41,0x00],'J': [0x20,0x40,0x41,0x3F,0x01],
                'K': [0x7F,0x08,0x14,0x22,0x41],'L': [0x7F,0x40,0x40,0x40,0x40],
                'M': [0x7F,0x02,0x0C,0x02,0x7F],'N': [0x7F,0x04,0x08,0x10,0x7F],
                'O': [0x3E,0x41,0x41,0x41,0x3E],'P': [0x7F,0x09,0x09,0x09,0x06],
                'Q': [0x3E,0x41,0x51,0x21,0x5E],'R': [0x7F,0x09,0x19,0x29,0x46],
                'S': [0x46,0x49,0x49,0x49,0x31],'T': [0x01,0x01,0x7F,0x01,0x01],
                'U': [0x3F,0x40,0x40,0x40,0x3F],'V': [0x1F,0x20,0x40,0x20,0x1F],
                'W': [0x3F,0x40,0x38,0x40,0x3F],'X': [0x63,0x14,0x08,0x14,0x63],
                'Y': [0x07,0x08,0x70,0x08,0x07],'Z': [0x61,0x51,0x49,0x45,0x43],
                '0': [0x3E,0x51,0x49,0x45,0x3E],'1': [0x00,0x42,0x7F,0x40,0x00],
                '2': [0x42,0x61,0x51,0x49,0x46],'3': [0x21,0x41,0x45,0x4B,0x31],
                '4': [0x18,0x14,0x12,0x7F,0x10],'5': [0x27,0x45,0x45,0x45,0x39],
                '6': [0x3C,0x4A,0x49,0x49,0x30],'7': [0x01,0x71,0x09,0x05,0x03],
                '8': [0x36,0x49,0x49,0x49,0x36],'9': [0x06,0x49,0x49,0x29,0x1E],
                '.': [0x00,0x60,0x60,0x00,0x00],',': [0x00,0x50,0x30,0x00,0x00],
                ':': [0x00,0x36,0x36,0x00,0x00],'-': [0x08,0x08,0x08,0x08,0x08],
                '/': [0x20,0x10,0x08,0x04,0x02],'!': [0x00,0x00,0x5F,0x00,0x00],
                '"': [0x00,0x07,0x00,0x07,0x00],'(': [0x00,0x1C,0x22,0x41,0x00],
                ')': [0x00,0x41,0x22,0x1C,0x00],'_': [0x40,0x40,0x40,0x40,0x40],
            }

            def set_pixel(x, y, color):
                if x < 0 or x >= width or y < 0 or y >= height:
                    return
                idx = (y * width + x) // 2
                curr = buf[idx]
                if x % 2 == 0:
                    buf[idx] = (curr & 0x0F) | (color << 4)
                else:
                    buf[idx] = (curr & 0xF0) | color

            # Word-wrap message
            words = message.split(' ')
            lines = []
            cur = []
            cur_len = 0
            for w in words:
                if cur_len + len(w) + (1 if cur else 0) <= 52:
                    cur.append(w)
                    cur_len += len(w) + (1 if cur else 0)
                else:
                    lines.append(' '.join(cur))
                    cur = [w]
                    cur_len = len(w)
            if cur:
                lines.append(' '.join(cur))

            char_w, char_h = 6, 8
            total_h = len(lines) * char_h * 3
            y_off = max(0, (height - total_h) // 2)
            for line in lines:
                x_off = max(0, (width - len(line) * char_w * 2) // 2)
                for ch in line:
                    glyph = FONT.get(ch.upper(), FONT[' '])
                    for ci in range(5):
                        cv = glyph[ci]
                        for ri in range(7):
                            if cv & (1 << ri):
                                for dx in range(2):
                                    for dy in range(2):
                                        set_pixel(x_off + ci * 2 + dx, y_off + ri * 2 + dy, 0)
                    x_off += char_w * 2
                y_off += char_h * 3

            with open(bin_path, 'wb') as f:
                f.write(buf)
            print("Warning image written to:", bin_path)

            from epd import EPD_7in3f
            epd = EPD_7in3f()
            epd.display_file(bin_path, battery_level=None)
            try: os.remove(bin_path)
            except Exception: pass
        except Exception as e:
            print("Paint message failed:", e)

    # Also add overlay-on-bin capability for battery mode
    def _overlay_on_bin(message, src_path, out_path):
        try:
            with open(src_path, 'rb') as f:
                buf = bytearray(f.read())
            if len(buf) != 192000:
                return False
            words = message.split(' ')
            lines, cur, cur_len = [], [], 0
            for w in words:
                need = len(w) + (1 if cur else 0)
                if cur_len + need <= 55: cur.append(w); cur_len += need
                else: lines.append(' '.join(cur)); cur = [w]; cur_len = len(w)
            if cur: lines.append(' '.join(cur))
            char_h, char_w = 8, 6
            total_h = len(lines) * char_h * 3
            y_top = max(0, (480 - total_h) // 2 - 15)
            y_bot = min(480, y_top + total_h + 30)
            FLOCAL = {
                ' ':(0,0,0,0,0),'A':(0x7E,0x11,0x11,0x11,0x7E),'B':(0x7F,0x49,0x49,0x49,0x36),
                'C':(0x3E,0x41,0x41,0x41,0x22),'D':(0x7F,0x41,0x41,0x22,0x1C),
                'E':(0x7F,0x49,0x49,0x49,0x41),'F':(0x7F,0x09,0x09,0x09,0x01),
                'G':(0x3E,0x41,0x49,0x49,0x7A),'H':(0x7F,0x08,0x08,0x08,0x7F),
                'I':(0x00,0x41,0x7F,0x41,0x00),'J':(0x20,0x40,0x41,0x3F,0x01),
                'K':(0x7F,0x08,0x14,0x22,0x41),'L':(0x7F,0x40,0x40,0x40,0x40),
                'M':(0x7F,0x02,0x0C,0x02,0x7F),'N':(0x7F,0x04,0x08,0x10,0x7F),
                'O':(0x3E,0x41,0x41,0x41,0x3E),'P':(0x7F,0x09,0x09,0x09,0x06),
                'Q':(0x3E,0x41,0x51,0x21,0x5E),'R':(0x7F,0x09,0x19,0x29,0x46),
                'S':(0x46,0x49,0x49,0x49,0x31),'T':(0x01,0x01,0x7F,0x01,0x01),
                'U':(0x3F,0x40,0x40,0x40,0x3F),'V':(0x1F,0x20,0x40,0x20,0x1F),
                'W':(0x3F,0x40,0x38,0x40,0x3F),'X':(0x63,0x14,0x08,0x14,0x63),
                'Y':(0x07,0x08,0x70,0x08,0x07),'Z':(0x61,0x51,0x49,0x45,0x43),
                '0':(0x3E,0x51,0x49,0x45,0x3E),'1':(0x00,0x42,0x7F,0x40,0x00),
                '2':(0x42,0x61,0x51,0x49,0x46),'3':(0x21,0x41,0x45,0x4B,0x31),
                '4':(0x18,0x14,0x12,0x7F,0x10),'5':(0x27,0x45,0x45,0x45,0x39),
                '6':(0x3C,0x4A,0x49,0x49,0x30),'7':(0x01,0x71,0x09,0x05,0x03),
                '8':(0x36,0x49,0x49,0x49,0x36),'9':(0x06,0x49,0x49,0x29,0x1E),
                '.':(0,0x60,0x60,0,0),',':(0,0x50,0x30,0,0),':':(0,0x24,0x24,0,0),
                '-':(8,8,8,8,8),'/':(0x20,0x10,8,4,2),'!':(0,0,0x5F,0,0),
                '"':(0,7,0,7,0),'(':(0,0x1C,0x22,0x41,0),')':(0,0x41,0x22,0x1C,0),
            }
            for y in range(y_top, y_bot):  # white band
                for xb in range(400): buf[y * 400 + xb] = 0x11
            def set_px(x, y, col):
                if 0 <= x < 800 and 0 <= y < 480:
                    idx = y * 400 + x // 2; b = buf[idx]
                    buf[idx] = (b & 0x0F)|(col<<4) if x%2==0 else (b & 0xF0)|col
            y_off = max(0, (480 - total_h) // 2)
            for line in lines:
                x_off = max(0, (800 - len(line) * 12) // 2)
                for ch in line:
                    g = FLOCAL.get(ch.upper(), FLOCAL[' '])
                    for ci in range(5):
                        cv = g[ci]
                        for ri in range(7):
                            if cv & (1 << ri):
                                for dx in range(2):
                                    for dy in range(2): set_px(x_off+ci*2+dx, y_off+ri*2+dy, 0)
                    x_off += 12
                y_off += char_h * 3
            with open(out_path, 'wb') as f: f.write(buf)
            return True
        except Exception as e:
            print('Overlay failed:', e); return False

    def _smart_paint_then_off(message):
        """Overlay message on random bin (or white screen), display, then power off."""
        out = '/sd/no_images.bin' if sd_mounted else '/no_images.bin'
        done = False
        if sd_mounted:
            try:
                bins = [f for f in os.listdir('/sd')
                        if f.endswith('.bin') and 'no_images' not in f and 'warning' not in f]
                if bins:
                    import urandom
                    chosen = bins[urandom.getrandbits(8) % len(bins)]
                    print('Overlaying on:', chosen)
                    done = _overlay_on_bin(message, '/sd/' + chosen, out)
            except Exception as e:
                print('Bin list error:', e)
        if not done:
            _paint_message(message, out)
        wlan.active(False)
        try:
            from axp import AXP2101
            AXP2101().disable_power()
        except Exception: pass
        machine.deepsleep(24 * 3600 * 1000)


    config = {}
    try:
        with open('bootstrap_config.json', 'r') as f:
            config = json.load(f)
    except Exception:
        pass
        
    ssid = config.get("ssid", "")
    password = config.get("password", "")
    server_ip = config.get("server_ip", "")
    require_server_ip = config.get("require_server_ip", False)
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    connected = False
    if ssid:
        print("Connecting to Wi-Fi:", ssid)
        wlan.connect(ssid, password)
        start_time = time.time()
        while not wlan.isconnected() and time.time() - start_time < 10:
            time.sleep_ms(100)
        connected = wlan.isconnected()
        
    # Helper to decode URL parameters
    def decode_url(s):
        res = []
        i = 0
        while i < len(s):
            if s[i] == '%' and i + 2 < len(s):
                try:
                    res.append(chr(int(s[i+1:i+3], 16)))
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
        
    # Helper for mDNS discovery
    def discover_server_mdns():
        print("mDNS discovery...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        packet = b'\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x0b_picframes\x04_tcp\x05local\x00\x00\x0c\x80\x01'
        for _ in range(3):
            try:
                sock.sendto(packet, ('224.0.0.251', 5353))
                start_t = time.time()
                while time.time() - start_t < 2.0:
                    data, addr = sock.recvfrom(1024)
                    if b'_picframes' in data:
                        port = 8000
                        idx = data.find(b'\x00\x21\x00\x01')
                        if idx == -1:
                            idx = data.find(b'\x00\x21\x80\x01')
                        if idx != -1 and idx + 16 <= len(data):
                            port = (data[idx+14] << 8) | data[idx+15]
                        sock.close()
                        return addr[0], port
            except Exception:
                pass
        sock.close()
        return None
        
    resolved_ip = None
    resolved_port = 8000
    
    if connected:
        print("Connected to Wi-Fi successfully!")
        if server_ip:
            print("Using manually configured server:", server_ip)
            resolved_ip = server_ip
            if ":" in resolved_ip:
                resolved_ip, port_str = resolved_ip.split(":")
                try: resolved_port = int(port_str)
                except ValueError: pass
        else:
            res = discover_server_mdns()
            if res:
                resolved_ip, resolved_port = res
                print("Discovered server via mDNS:", resolved_ip)
            else:
                print("mDNS discovery failed.")
                require_server_ip = True
                
    if resolved_ip:
        # Download firmware files from server
        update_url = "http://{}:{}/api/update".format(resolved_ip, resolved_port)
        print("Downloading firmware from:", update_url)
        
        try:
            import urequests as requests
            res = requests.get(update_url, timeout=15)
            if res.status_code == 200:
                zip_path = "/sd/update.zip" if sd_mounted else "/update.zip"
                with open(zip_path, 'wb') as f:
                    chunk = bytearray(1024)
                    while True:
                        n = res.raw.readinto(chunk)
                        if not n: break
                        f.write(chunk if n == len(chunk) else chunk[:n])
                res.close()
                print("Downloaded update.zip. Extracting...")
                
                target_dir = "/sd" if sd_mounted else ""
                extract_zip(zip_path, target_dir)
                os.remove(zip_path)
                print("Firmware extracted successfully.")
                
                # Create default wifi_config.json
                mac_bytes = wlan.config('mac')
                dev_id = ubinascii.hexlify(mac_bytes[-4:]).decode()
                
                wifi_config = {
                    "ssid": ssid,
                    "password": password,
                    "device_id": dev_id,
                    "api_url": "http://{}:{}/api/wakeup".format(resolved_ip, resolved_port),
                    "daily_zip_url": "http://{}:{}/api/daily-zip".format(resolved_ip, resolved_port),
                    "update_url": "http://{}:{}/api/update".format(resolved_ip, resolved_port),
                    "orientation": "landscape"
                }
                
                cfg_path = "/sd/wifi_config.json" if sd_mounted else "/wifi_config.json"
                with open(cfg_path, 'w') as f:
                    json.dump(wifi_config, f)
                print("Saved wifi_config.json.")
                
                # Delete temporary bootstrap config
                try: os.remove('bootstrap_config.json')
                except Exception: pass
                
                print("Bootstrap complete. Rebooting...")
                time.sleep(1.0)
                machine.reset()
            else:
                print("Server returned status:", res.status_code)
                res.close()
        except Exception as e:
            print("Failed to download firmware:", e)
            
    # If we reached here, no server was found or download failed. Display setup screen and start AP portal.
    mac_bytes = wlan.config('mac')
    ap_id = ubinascii.hexlify(mac_bytes[-4:]).decode().upper()
    ap_ssid = "PicFrame - " + ap_id

    show_setup_screen(ap_id)

    print("Starting AP portal...")
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=ap_ssid, authmode=network.AUTH_OPEN)
    print("AP SSID:", ap_ssid)
    print("AP IP:", ap.ifconfig()[0])
    
    # Start the DNS responder thread
    ap_portal_active = True
    try:
        import _thread
        _thread.start_new_thread(dns_server_thread, ())
    except Exception as e:
        print("Failed to start DNS thread:", e)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(1)
    s.settimeout(2.0)
    
    mac_bytes = wlan.config('mac')
    import ubinascii
    mac_str_clean = ubinascii.hexlify(mac_bytes, ':').decode()
    dev_id = ubinascii.hexlify(mac_bytes[-4:]).decode().upper()
    
    html_template = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>PicFrame Onboarding</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Outfit', sans-serif;
            background: radial-gradient(circle at center, hsl(220, 30%, 12%), hsl(220, 35%, 6%));
            color: hsl(220, 20%, 94%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }
        .card {
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            padding: 32px;
            border-radius: 20px;
            width: 100%;
            max-width: 440px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
            animation: fadeIn 0.6s ease-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        h2 {
            font-weight: 700;
            font-size: 1.8rem;
            margin-bottom: 8px;
            background: linear-gradient(135deg, hsl(190, 100%, 55%), hsl(260, 90%, 65%));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: center;
        }
        .subtitle {
            text-align: center;
            font-size: 0.9rem;
            color: hsl(220, 15%, 60%);
            margin-bottom: 24px;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            font-size: 0.85rem;
            font-family: monospace;
            background: rgba(0,0,0,0.2);
            padding: 8px 12px;
            border-radius: 8px;
            margin-bottom: 8px;
            color: hsl(200, 100%, 75%);
        }
        .status-card {
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background: rgba(0,0,0,0.15);
        }
        .status-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 0.9rem;
        }
        .status-label {
            color: hsl(220, 10%, 70%);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-value {
            font-weight: 500;
        }
        .battery-container {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .battery-outer {
            width: 50px;
            height: 22px;
            border: 2px solid hsl(220, 15%, 60%);
            border-radius: 4px;
            padding: 2px;
            position: relative;
        }
        .battery-outer::after {
            content: '';
            position: absolute;
            right: -5px;
            top: 5px;
            width: 3px;
            height: 8px;
            background: hsl(220, 15%, 60%);
            border-radius: 0 2px 2px 0;
        }
        .battery-inner {
            height: 100%;
            border-radius: 2px;
            width: {battery_pct}%;
            background: {battery_color};
            transition: width 0.3s ease;
        }
        .alert {
            border-radius: 12px;
            padding: 14px;
            font-size: 0.85rem;
            line-height: 1.4;
            margin-bottom: 20px;
            display: flex;
            align-items: flex-start;
            gap: 10px;
        }
        .alert-warning {
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: hsl(0, 85%, 70%);
        }
        .alert-success {
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: hsl(140, 75%, 70%);
        }
        label {
            display: block;
            font-size: 0.85rem;
            color: hsl(220, 15%, 70%);
            margin-bottom: 6px;
            font-weight: 500;
        }
        .input-group {
            margin-bottom: 18px;
            position: relative;
        }
        input[type=text], input[type=password] {
            width: 100%;
            padding: 12px 14px;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 10px;
            color: #ffffff;
            font-size: 0.95rem;
            transition: all 0.25s ease;
        }
        input[type=text]:focus, input[type=password]:focus {
            outline: none;
            border-color: hsl(190, 100%, 55%);
            box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.15);
            background: rgba(15, 23, 42, 0.8);
        }
        input[type=submit] {
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
        }
        input[type=submit]:hover {
            background: linear-gradient(135deg, hsl(190, 100%, 50%), hsl(260, 90%, 60%));
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(56, 189, 248, 0.3);
        }
        input[type=submit]:active {
            transform: translateY(1px);
        }
        .error-box {
            color: hsl(0, 85%, 65%);
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.2);
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            font-size: 0.85rem;
            text-align: center;
        }
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
    
    config_saved = False
    while True:
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
                        params[k] = decode_url(v)
                        
                ssid_new = params.get("ssid", "").strip()
                pass_new = params.get("password", "").strip()
                ip_new = params.get("server_ip", "").strip()
                
                if ssid_new:
                    # Save to bootstrap config
                    new_config = {
                        "ssid": ssid_new,
                        "password": pass_new,
                        "server_ip": ip_new,
                        "require_server_ip": require_server_ip
                    }
                    with open('bootstrap_config.json', 'w') as f:
                        json.dump(new_config, f)
                    
                    conn.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
                    conn.send("<html><body><h3>Credentials saved! Retrying connection...</h3></body></html>")
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
                    dev_id=dev_id.upper(),
                    mac=mac_str_clean.upper(),
                    battery_pct=bat_pct,
                    battery_color=bat_color,
                    power_source=power_source,
                    power_color=power_color,
                    alert_card=alert_card,
                    error_msg=error_msg,
                    ssid=ssid,
                    password=password,
                    server_ip=server_ip,
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
        print("Rebooting to apply settings...")
        time.sleep_ms(500)
        machine.reset()
