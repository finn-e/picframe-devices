import sys
import os
import time
import machine
import network
import socket
import json
import ubinascii
from unzip import extract_zip

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

    # --- Gate: only run network setup if USB power is present ---
    if not _is_usb_connected():
        mac_bytes = network.WLAN(network.STA_IF).config('mac')
        uid = ubinascii.hexlify(mac_bytes[-4:]).decode().upper()
        msg = (
            'Initial setup required. Please connect this frame to USB power, '
            'then connect to the "PicFrame-{}" Wi-Fi network to configure it.'.format(uid)
        )
        print("On battery in bootstrap mode. Painting message and sleeping.")
        bin_path = '/sd/no_images.bin' if sd_mounted else '/no_images.bin'
        _paint_message(msg, bin_path)
        print("Entering deep sleep for 24 hours...")
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
            
    # If we reached here, we need to stand up the AP Setup Portal.
    # First paint a screen message so the user knows what to do.
    mac_bytes = wlan.config('mac')
    ap_id = ubinascii.hexlify(mac_bytes[-4:]).decode().upper()
    ap_ssid = "PicFrame - " + ap_id
    if require_server_ip:
        portal_msg = (
            'Could not find PicFrames server. '
            'Connect to "{}" Wi-Fi, go to 192.168.4.1 and enter '
            'Wi-Fi credentials AND the server IP address.'.format(ap_ssid)
        )
    else:
        portal_msg = (
            'Connect to "{}" Wi-Fi on your phone or computer, '
            'then open 192.168.4.1 in your browser to configure this frame.'.format(ap_ssid)
        )
    bin_path = '/sd/no_images.bin' if sd_mounted else '/no_images.bin'
    _paint_message(portal_msg, bin_path)

    print("Starting AP portal...")
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=ap_ssid, authmode=network.AUTH_OPEN)
    print("AP SSID:", ap_ssid)
    print("AP IP:", ap.ifconfig()[0])
    

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(1)
    s.settimeout(2.0)
    
    html_template = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>PicFrame Bootstrap Setup</title>
    <style>
        body {{ font-family: sans-serif; background: #0f172a; color: #f1f3f9; padding: 20px; }}
        h2 {{ color: #38bdf8; }}
        .card {{ background: #1e293b; padding: 20px; border-radius: 12px; max-width: 400px; margin: 0 auto; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
        input[type=text], input[type=password] {{ width: 100%; padding: 10px; margin: 10px 0; box-sizing: border-box; background: #0f172a; color: white; border: 1px solid #334155; border-radius: 6px; }}
        input[type=submit] {{ background: #0ea5e9; color: white; border: none; padding: 12px; width: 100%; border-radius: 6px; font-weight: bold; cursor: pointer; }}
        input[type=submit]:hover {{ background: #0284c7; }}
        .error {{ color: #ef4444; background: #450a0a; padding: 10px; border-radius: 6px; margin-bottom: 15px; font-size: 0.9rem; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>📷 PicFrame Bootstrap</h2>
        {error_msg}
        <form method="POST" action="/save">
            <label>Wi-Fi SSID:</label>
            <input type="text" name="ssid" value="{ssid}" required>
            <label>Wi-Fi Password:</label>
            <input type="password" name="password" value="{password}">
            <label>PicFrames Server IP/DNS {req_label}:</label>
            <input type="text" name="server_ip" value="{server_ip}" {req_attr} placeholder="192.168.1.100:8000">
            <input type="submit" value="Save & Connect">
        </form>
    </div>
</body>
</html>"""

    error_msg = ""
    if require_server_ip:
        error_msg = '<div class="error">Connected to Wi-Fi but could not discover the PicFrames server via mDNS. Server IP/DNS is required.</div>'
        
    req_label = "(Required)" if require_server_ip else "(Optional)"
    req_attr = "required" if require_server_ip else ""
    
    html = html_template.format(
        error_msg=error_msg,
        ssid=ssid,
        password=password,
        server_ip=server_ip,
        req_label=req_label,
        req_attr=req_attr
    )
    
    config_saved = False
    while True:
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
                conn.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
                conn.send(html)
                conn.close()
        except OSError:
            pass
            
    s.close()
    ap.active(False)
    if config_saved:
        print("Rebooting to apply settings...")
        time.sleep_ms(500)
        machine.reset()
