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
    
    # Load bootstrap config
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
            
    # If we reached here, we need to stand up the AP Setup Portal
    print("Starting AP portal...")
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    mac_bytes = wlan.config('mac')
    ap_ssid = "PicFrame - " + ubinascii.hexlify(mac_bytes[-4:]).decode().upper()
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
