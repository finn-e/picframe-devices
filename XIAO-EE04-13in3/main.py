# ==========================================
# FILE VERSION: 1.8.0
# DESCRIPTION: Main slideshow loop for XIAO EE04 + 13.3" Spectra 6 (dual-controller).
#   Panel: 1200 × 1600 px physical (portrait native).
#   Image pipeline resolution: EPD_WIDTH=1200, EPD_HEIGHT=1600.
#   NOTE: The server currently generates 800×480 images; 13.3" images require a
#         separate server pipeline (not yet implemented). This device will work
#         correctly once the server is extended to produce 1200×1600 bin files.
#   Buttons: KEY1(GPIO2)=check-in, KEY2(GPIO3)=orientation, KEY3(GPIO5)=skip.
# ==========================================
import time
import machine
import gc
import os
import json
import network
import ubinascii

try:
    network.WLAN(network.AP_IF).active(False)
except Exception:
    pass

# Panel geometry constants (used by render pipeline)
EPD_WIDTH  = 1200
EPD_HEIGHT = 1600
EPD_BUF_SIZE = EPD_WIDTH * EPD_HEIGHT // 2   # 960 000 bytes


def hard_reboot():
    print('Hard reboot via WDT...')
    try:
        network.WLAN(network.STA_IF).active(False)
        network.WLAN(network.AP_IF).active(False)
    except Exception:
        pass
    try:
        from machine import WDT
        WDT(timeout=500)
        while True:
            pass
    except Exception:
        pass
    machine.reset()


def soft_reboot():
    print('Soft reboot...')
    try:
        network.WLAN(network.STA_IF).active(False)
        network.WLAN(network.AP_IF).active(False)
    except Exception:
        pass
    import machine
    machine.soft_reset()


print('--- PicFrame EE04-13in3 v1.0 starting ---')

# ── Buttons (all active-low, PULL_UP) ────────────────────────────────────────
key1_btn = machine.Pin(2, machine.Pin.IN, machine.Pin.PULL_UP)
key2_btn = machine.Pin(3, machine.Pin.IN, machine.Pin.PULL_UP)
key3_btn = machine.Pin(5, machine.Pin.IN, machine.Pin.PULL_UP)

# ── Deep-sleep wake-cause routing ────────────────────────────────────────────
# KEY1 (GPIO2) wakes via ext0 → run full server check-in.
# KEY2 (GPIO3) wakes via ext1 → toggle orientation.
# KEY3 (GPIO5) has no deep-sleep wake source (see go_to_sleep); skip works
# while awake (startup press or USB-simulated sleep).
# A wake press is usually released before main.py samples the pins, so we
# route on machine.wake_reason() rather than on the live pin level alone.
wake_key1 = False
wake_key2 = False
try:
    _wr = machine.wake_reason()
    if _wr == machine.EXT0_WAKE:
        print('Woken by KEY1 (ext0) — will run full check-in')
        wake_key1 = True
    elif _wr == machine.EXT1_WAKE:
        print('Woken by KEY2 (ext1) — will toggle orientation')
        wake_key2 = True
except Exception as e:
    print('wake_reason check failed:', e)

time.sleep_ms(100)
key1_pressed = wake_key1 or key1_btn.value() == 0
key2_pressed = wake_key2 or key2_btn.value() == 0
key3_pressed = key3_btn.value() == 0
if key1_pressed:
    print('KEY1 held at startup')
    while key1_btn.value() == 0: time.sleep_ms(10)
if key2_pressed:
    print('KEY2 held at startup')
    while key2_btn.value() == 0: time.sleep_ms(10)
if key3_pressed:
    print('KEY3 held at startup')
    while key3_btn.value() == 0: time.sleep_ms(10)

# ── MAC ───────────────────────────────────────────────────────────────────────
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
mac_bytes = wlan.config('mac')
mac_str   = ubinascii.hexlify(mac_bytes, ':').decode()
print('Device MAC:', mac_str)

# ── Config ────────────────────────────────────────────────────────────────────
import sys
sys.path.insert(0, '/images')
sys.path.insert(1, '/')

try:
    from config import (
        load_wifi_config, save_wifi_config,
        load_sd_config, save_sd_config, merge_sd_config,
    )
except Exception as e:
    print('Config module failed:', e)
    def load_wifi_config():
        try:
            with open('/wifi_config.json') as f: return json.load(f)
        except Exception:
            return {'ssid':'','password':'','server_url':'https://picframes.treee.house',
                    'username':'','token':'','landscape_flipped':False,'portrait_flipped':False}
    def save_wifi_config(c):
        try:
            with open('/wifi_config.json','w') as f: json.dump(c,f)
        except Exception: pass
    def load_sd_config():
        try:
            with open('/images/config.json') as f: return json.load(f)
        except Exception:
            return {'orientation':'landscape','sleep_interval':900,'image_index':0,
                    'daily_zip_version':'','images':[]}
    def save_sd_config(c):
        try:
            with open('/images/config.json','w') as f: json.dump(c,f)
        except Exception: pass
    def merge_sd_config(a, b):
        m = dict(a); m.update({k:v for k,v in b.items() if k not in
            {'ssid','password','server_url','username','token',
             'landscape_flipped','portrait_flipped'}}); return m

wifi_cfg = load_wifi_config()
sd_cfg   = load_sd_config()

HW_PROFILE = 'Seeed-EE04-Spectra6-13in3'
RESOLUTION  = '1600x1200'

# ── Failure reason ────────────────────────────────────────────────────────────
fail_reason = ''

# ── Helpers ───────────────────────────────────────────────────────────────────
def wipe_images():
    try:
        for f in os.listdir('/images'):
            if not f.endswith('.bin'): continue
            try: os.remove('/images/' + f)
            except Exception: pass
    except Exception as e:
        print('Image wipe error:', e)

def get_bat_pct():
    try:
        from battery import get_battery_percentage, is_usb_connected
        pct = get_battery_percentage()
        if pct is not None and pct < 20 and is_usb_connected():
            return 20
        return pct
    except Exception:
        return None

def go_to_sleep(seconds):
    if sd_cfg.get('debug'):
        print('DEBUG mode — using light sleep (time.sleep + reset) for', seconds, 's')
        try:
            time.sleep(seconds)
        except Exception:
            pass
        machine.reset()
        return
    try:
        from battery import is_usb_connected
        if is_usb_connected():
            print('USB connected — simulating sleep for', seconds, 's')
            _wait_with_buttons(seconds)
            return
    except Exception as e:
        print('battery check error:', e)

    print('Deep sleeping for', seconds, 's')
    # See XIAO-EE04-7in3/main.py for wake-pin rationale.
    try:
        import esp32
        machine.wake_on_ext0(pin=machine.Pin(2, machine.Pin.IN, machine.Pin.PULL_UP), level=0)
        esp32.wake_on_ext1(pins=(machine.Pin(3, machine.Pin.IN, machine.Pin.PULL_UP),),
                           level=esp32.WAKEUP_ALL_LOW)
    except Exception as e:
        print('Wake pin setup failed:', e)
    machine.deepsleep(seconds * 1000)

def _wait_with_buttons(seconds):
    end = time.time() + seconds
    while time.time() < end:
        _check_buttons()
        time.sleep_ms(50)

def _check_buttons():
    if key1_btn.value() == 0:
        time.sleep_ms(50)
        if key1_btn.value() == 0:
            while key1_btn.value() == 0: time.sleep_ms(10)
            action_pwr_checkin()
    if key2_btn.value() == 0:
        time.sleep_ms(50)
        if key2_btn.value() == 0:
            while key2_btn.value() == 0: time.sleep_ms(10)
            action_toggle_orientation()
    if key3_btn.value() == 0:
        time.sleep_ms(50)
        if key3_btn.value() == 0:
            while key3_btn.value() == 0: time.sleep_ms(10)
            action_key_skip()

def resolve_image_path(basename):
    orientation = sd_cfg.get('orientation', 'landscape')
    suffix = '_l.bin' if 'landscape' in orientation else '_p.bin'
    return '/images/' + basename + suffix

# ── Display ───────────────────────────────────────────────────────────────────
def render_and_sleep(img_path, orientation, sleep_interval):
    global fail_reason
    try:
        network.WLAN(network.STA_IF).active(False)
    except Exception:
        pass
    bat_pct = get_bat_pct()
    try:
        from display_overlay import apply_battery_square, apply_caption_overlay, apply_debug_overlay

        # 960 000-byte buffer — requires PSRAM (8 MB available on XIAO ESP32-S3 Plus)
        gc.collect()
        buf = bytearray(EPD_BUF_SIZE)
        with open(img_path, 'rb') as f:
            f.readinto(buf)

        base_name = img_path.split('/')[-1]
        if base_name.endswith('.bin'):
            base_name = base_name[:-4]
        for suffix in ['_l', '_p']:
            if base_name.endswith(suffix):
                base_name = base_name[:-len(suffix)]
                break

        img_cfg      = sd_cfg.get('enabled', {}).get(base_name, {})
        caption_mode = img_cfg.get('caption_mode', 'title')
        description  = img_cfg.get('description', '')

        apply_battery_square(buf, bat_pct)
        apply_caption_overlay(buf, img_path, caption_mode, description, 'portrait' in orientation, bat_pct)
        if fail_reason:
            from display_overlay import apply_status_overlay
            apply_status_overlay(buf, fail_reason)

        if sd_cfg.get('debug'):
            orient_upper = orientation.upper()
            flip_str = ''
            if sd_cfg.get('landscape_flipped') or sd_cfg.get('flip_l'):
                flip_str += ' L-FLIP'
            if sd_cfg.get('portrait_flipped') or sd_cfg.get('flip_p'):
                flip_str += ' P-FLIP'
            checkin_str = 'CHECKIN:?'
            try:
                last_ci = sd_cfg.get('last_checkin')
                if last_ci:
                    mins = int((time.time() - last_ci) / 60)
                    checkin_str = 'CHECKIN:{}M AGO'.format(mins)
            except Exception:
                pass
            b_val = bat_pct if bat_pct is not None else 100
            debug_lines = [
                'MAC:' + mac_str,
                'FW:' + (sd_cfg.get('update_version') or 'unknown'),
                checkin_str,
                'BATT:{}%'.format(b_val),
                orient_upper + (flip_str or ''),
                'IMG:' + base_name,
            ]
            apply_debug_overlay(buf, debug_lines)

        tmp_path = '/tmp_render.bin'
        with open(tmp_path, 'wb') as f:
            f.write(buf)
        del buf
        gc.collect()

        from epd import EPD_13in3e
        EPD_13in3e().display_file(tmp_path, orientation=orientation)
        try: os.remove(tmp_path)
        except Exception: pass
        print('Display updated.')
    except Exception as e:
        print('Render failed:', e)
        fail_reason = ('RENDER FAILED: ' + str(e))[:78]
    go_to_sleep(sleep_interval)

def _draw_message_screen(lines, orientation='landscape'):
    """Draw text lines in the bottom quarter over the logo background."""
    try:
        gc.collect()
        logo_file = '/picframes_logo_l.bin' if 'landscape' in orientation else '/picframes_logo_p.bin'
        try:
            with open(logo_file, 'rb') as f:
                buf = bytearray(f.read())
        except Exception:
            buf = bytearray(b'\x11' * EPD_BUF_SIZE)
        from display_overlay import _render_text_line, apply_battery_square
        scale  = 2
        line_h = 8 * scale + 6
        total_h = len(lines) * line_h
        text_zone_top = EPD_HEIGHT * 3 // 4
        y_start = text_zone_top + (EPD_HEIGHT // 4 - total_h) // 2
        for i, line in enumerate(lines):
            _render_text_line(buf, line, y_start + i * line_h, scale=scale)
        apply_battery_square(buf, get_bat_pct())
        out_path = '/msg_screen.bin'
        with open(out_path, 'wb') as f: f.write(buf)
        del buf
        gc.collect()
        from epd import EPD_13in3e
        EPD_13in3e().display_file(out_path, orientation=orientation)
        try: os.remove(out_path)
        except Exception: pass
    except Exception as e:
        print('Message screen error:', e)

# ── AP Captive Portal ─────────────────────────────────────────────────────────
def re_url_decode(s):
    res, i = [], 0
    while i < len(s):
        if s[i] == '%' and i + 2 < len(s):
            try: res.append(chr(int(s[i+1:i+3], 16))); i += 3
            except ValueError: res.append(s[i]); i += 1
        elif s[i] == '+': res.append(' '); i += 1
        else: res.append(s[i]); i += 1
    return ''.join(res)

def escape_html(val):
    return str(val).replace('&','&amp;').replace('"','&quot;')

def recv_http_request(conn):
    # Read the full request: headers, then body per Content-Length. A single
    # recv() often misses the POST body (it arrives in a later TCP segment).
    conn.settimeout(4)
    data = b''
    while b'\r\n\r\n' not in data and len(data) < 8192:
        chunk = conn.recv(1024)
        if not chunk:
            break
        data += chunk
    head, _, body = data.partition(b'\r\n\r\n')
    clen = 0
    for line in head.split(b'\r\n'):
        if line.lower().startswith(b'content-length:'):
            try:
                clen = int(line.split(b':', 1)[1])
            except ValueError:
                pass
    while len(body) < clen:
        chunk = conn.recv(1024)
        if not chunk:
            break
        body += chunk
    return (head + b'\r\n\r\n' + body).decode('utf-8', 'ignore')



ap_active = False

def dns_thread():
    global ap_active
    import socket
    udps = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udps.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udps.settimeout(1.0)
    bound = False
    for i in range(5):
        try: udps.bind(('', 53)); bound = True; break
        except Exception as e: print('DNS bind attempt {} failed:'.format(i+1), e); time.sleep_ms(200)
    if not bound:
        udps.close(); return
    while ap_active:
        try:
            data, addr = udps.recvfrom(512)
            if data and len(data) >= 12:
                tx_id = data[0:2]; idx = 12
                while idx < len(data):
                    l = data[idx]
                    if l == 0: idx += 1; break
                    idx += 1 + l
                if idx + 4 <= len(data):
                    question = data[12:idx+4]; qtype = data[idx:idx+2]
                    if qtype == b'\x00\x01':
                        resp = (tx_id + b'\x81\x80' + data[4:6] + b'\x00\x01\x00\x00\x00\x00' +
                                question + b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\xc0\xa8\x04\x01')
                    else:
                        resp = tx_id + b'\x81\x80' + data[4:6] + b'\x00\x00\x00\x00\x00\x00' + question
                    udps.sendto(resp, addr)
        except OSError: pass
    udps.close()

SETUP_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>PicFrame Setup</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;
          display:flex;align-items:center;justify-content:center;padding:20px}}
    .card{{background:rgba(30,41,59,.8);border:1px solid rgba(255,255,255,.08);padding:32px;
           border-radius:20px;width:100%;max-width:440px}}
    h2{{font-weight:700;font-size:1.7rem;margin-bottom:6px;
        background:linear-gradient(135deg,hsl(190,100%,55%),hsl(260,90%,65%));
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;text-align:center}}
    .sub{{text-align:center;color:#64748b;font-size:.85rem;margin-bottom:20px}}
    .err{{color:hsl(0,85%,65%);background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.2);
          padding:10px;border-radius:8px;margin-bottom:14px;font-size:.82rem;text-align:center}}
    label{{display:block;font-size:.82rem;color:#94a3b8;margin-bottom:4px;font-weight:500}}
    .ig{{margin-bottom:14px}}
    input[type=text],input[type=password]{{width:100%;padding:10px 12px;
      background:rgba(15,23,42,.6);border:1px solid rgba(255,255,255,.1);
      border-radius:8px;color:#fff;font-size:.92rem}}
    input[type=submit]{{width:100%;padding:12px;border:none;border-radius:9px;
      background:linear-gradient(135deg,hsl(190,100%,45%),hsl(260,90%,55%));
      color:#fff;font-size:.97rem;font-weight:600;cursor:pointer;margin-top:4px}}
    .notice{{background:rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.3);
             border-radius:10px;padding:12px;font-size:.82rem;margin-bottom:20px;
             color:#a5b4fc;line-height:1.5}}
  </style>
</head>
<body><div class="card">
  <h2>PicFrame Setup</h2>
  <div class="sub">Device ID: {dev_id} &nbsp;|&nbsp; MAC: {mac}</div>
  {err}
  <div class="notice">&#x24D8; Enter your Wi-Fi credentials and PicFrames server details.</div>
  <form method="POST" action="/save">
    <div class="ig"><label>Wi-Fi Network (SSID)</label>
      <input type="text" name="ssid" value="{ssid}" required></div>
    <div class="ig"><label>Wi-Fi Password</label>
      <input type="password" name="wifi_pass" value="{wifi_pass}"></div>
    <div class="ig"><label>PicFrames Server URL</label>
      <input type="text" name="server_url" value="{server_url}"
             placeholder="https://picframes.treee.house"></div>
    <div class="ig"><label>Username</label>
      <input type="text" name="username" value="{username}"></div>
    <div class="ig"><label>Password</label>
      <input type="password" name="token" value=""></div>
    <input type="submit" value="Save &amp; Connect">
  </form>
</div></body></html>"""

def start_ap_and_portal(reason='setup'):
    global ap_active, wifi_cfg
    dev_id  = mac_str.replace(':', '')[-8:].upper()
    ap_ssid = 'PicFrame-' + mac_str.replace(':', '')
    # Shut down the STA interface — a failed/scanning STA destabilizes the AP.
    network.WLAN(network.STA_IF).active(False)
    time.sleep_ms(200)
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=ap_ssid, authmode=network.AUTH_OPEN)
    for _ in range(30):
        if ap.active(): break
        time.sleep_ms(100)
    print('AP started:', ap_ssid)
    ap_active = True
    try:
        import _thread
        _thread.start_new_thread(dns_thread, ())
    except Exception as e:
        print('DNS thread failed:', e)
    import socket
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80)); s.listen(1); s.settimeout(0.2)
    while True:
        try:
            conn, addr = s.accept()
            req = recv_http_request(conn)
            lines = req.split('\r\n')
            first = lines[0].split(' ') if lines else []
            method = first[0] if first else ''
            path   = first[1] if len(first) > 1 else '/'
            host = ''
            for line in lines:
                if line.lower().startswith('host:'):
                    host = line.split(':', 1)[1].strip(); break
            is_portal = ('192.168.4.1' in host or 'picframe.setup' in host.lower())
            if not is_portal:
                conn.send('HTTP/1.1 302 Found\r\nLocation: http://192.168.4.1/\r\n'
                          'Cache-Control: no-cache\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                conn.close(); continue
            if method == 'POST' and '/save' in path:
                body = req.split('\r\n\r\n', 1)[-1]
                p = {}
                for kv in body.split('&'):
                    if '=' in kv:
                        k, v = kv.split('=', 1)
                        p[k] = re_url_decode(v)
                ssid_v       = p.get('ssid', '').strip()
                wifi_pass_v  = p.get('wifi_pass', '').strip()
                server_url_v = p.get('server_url', '').strip() or 'https://picframes.treee.house'
                username_v   = p.get('username', '').strip()
                token_v      = p.get('token', '').strip()
                if ssid_v:
                    wifi_cfg['ssid']       = ssid_v
                    wifi_cfg['password']   = wifi_pass_v
                    wifi_cfg['server_url'] = server_url_v
                    wifi_cfg['username']   = username_v
                    if token_v:
                        wifi_cfg['token'] = token_v
                    save_wifi_config(wifi_cfg)
                    resp_body = '<html><body><h2>Saved! Rebooting...</h2></body></html>'
                    conn.send('HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\n'
                              'Connection: close\r\n\r\n{}'.format(len(resp_body), resp_body).encode())
                    time.sleep_ms(2000)
                    conn.close(); s.close()
                    ap_active = False; ap.active(False)
                    time.sleep_ms(500)
                    soft_reboot()
            else:
                html = SETUP_HTML.format(
                    dev_id=dev_id, mac=mac_str.upper(),
                    ssid=escape_html(wifi_cfg.get('ssid', '')),
                    wifi_pass=escape_html(wifi_cfg.get('password', '')),
                    server_url=escape_html(wifi_cfg.get('server_url', 'https://picframes.treee.house')),
                    username=escape_html(wifi_cfg.get('username', '')),
                    err=('<div class="err">Cannot reach PicFrames server. Re-enter credentials to reconfigure.</div>'
                         if reason == 'unreachable' else
                         '<div class="err">Could not connect to Wi-Fi. Check the network name and password.</div>'
                         if reason == 'wifi_failed' else ''),
                )
                conn.send('HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n')
                conn.send(html); conn.close()
        except OSError:
            pass

RECONFIG_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>PicFrame Reconfigure</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;
          display:flex;align-items:center;justify-content:center;padding:20px}}
    .card{{background:rgba(30,41,59,.8);border:1px solid rgba(255,255,255,.08);padding:32px;
           border-radius:20px;width:100%;max-width:440px}}
    h2{{font-weight:700;font-size:1.7rem;margin-bottom:6px;
        background:linear-gradient(135deg,hsl(190,100%,55%),hsl(260,90%,65%));
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;text-align:center}}
    .sub{{text-align:center;color:#64748b;font-size:.85rem;margin-bottom:20px}}
    label{{display:block;font-size:.82rem;color:#94a3b8;margin-bottom:4px;font-weight:500}}
    .ig{{margin-bottom:14px}}
    input[type=text],input[type=password]{{width:100%;padding:10px 12px;
      background:rgba(15,23,42,.6);border:1px solid rgba(255,255,255,.1);
      border-radius:8px;color:#fff;font-size:.92rem}}
    input[type=submit]{{width:100%;padding:12px;border:none;border-radius:9px;
      background:linear-gradient(135deg,hsl(190,100%,45%),hsl(260,90%,55%));
      color:#fff;font-size:.97rem;font-weight:600;cursor:pointer;margin-top:4px}}
    .notice{{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);
             border-radius:10px;padding:12px;font-size:.82rem;margin-bottom:20px;
             color:#fca5a5;line-height:1.5}}
  </style>
</head>
<body><div class="card">
  <h2>PicFrame</h2>
  <div class="sub">Device: {dev_id} &nbsp;|&nbsp; IP: {ip}</div>
  <div class="notice">&#x26A0; Cannot reach the PicFrames server. Update your server details below.</div>
  <form method="POST" action="/save">
    <div class="ig"><label>PicFrames Server URL</label>
      <input type="text" name="server_url" value="{server_url}"
             placeholder="https://picframes.treee.house" required></div>
    <div class="ig"><label>Username</label>
      <input type="text" name="username" value="{username}"></div>
    <div class="ig"><label>Password</label>
      <input type="password" name="token" value=""
             placeholder="Leave blank to keep existing"></div>
    <input type="submit" value="Save &amp; Reboot">
  </form>
</div></body></html>"""

def start_sta_reconfigure_portal():
    global wifi_cfg
    import socket
    dev_id   = mac_str.replace(':', '')[-8:].upper()
    ip       = wlan.ifconfig()[0]
    hostname = 'picframe-' + mac_str.replace(':', '')[-8:].lower()
    try:
        network.hostname(hostname)
        print('mDNS hostname:', hostname + '.local')
    except Exception as e:
        print('hostname set failed:', e)
    print('=== RECONFIGURE MODE — visit http://{}/ ==='.format(ip))
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80)); s.listen(1); s.settimeout(0.2)
    while True:
        try:
            conn, addr = s.accept()
            req = recv_http_request(conn)
            lines = req.split('\r\n')
            first = lines[0].split(' ') if lines else []
            method = first[0] if first else ''
            path   = first[1] if len(first) > 1 else '/'
            if method == 'POST' and '/save' in path:
                body = req.split('\r\n\r\n', 1)[-1]
                p = {}
                for kv in body.split('&'):
                    if '=' in kv:
                        k, v = kv.split('=', 1)
                        p[k] = re_url_decode(v)
                wifi_cfg['server_url'] = p.get('server_url', '').strip() or wifi_cfg.get('server_url', '')
                wifi_cfg['username']   = p.get('username', '').strip()
                if p.get('token', '').strip():
                    wifi_cfg['token'] = p['token'].strip()
                save_wifi_config(wifi_cfg)
                resp_body = '<html><body><h2>Saved! Rebooting...</h2></body></html>'
                conn.send(('HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\n'
                            'Connection: close\r\n\r\n{}'.format(len(resp_body), resp_body)).encode())
                time.sleep_ms(2000)
                conn.close(); s.close()
                time.sleep_ms(500)
                hard_reboot()
            else:
                html = RECONFIG_HTML.format(
                    dev_id=dev_id, ip=ip,
                    server_url=escape_html(wifi_cfg.get('server_url', '')),
                    username=escape_html(wifi_cfg.get('username', '')),
                )
                conn.send('HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n')
                conn.send(html); conn.close()
        except OSError:
            pass

# ── Button actions ────────────────────────────────────────────────────────────
def action_toggle_orientation():
    print('KEY2: toggling orientation')
    cur = sd_cfg.get('orientation', 'landscape')
    cycle = {
        'landscape': 'portrait',
        'portrait': 'landscape-upside-down',
        'landscape-upside-down': 'portrait-upside-down',
        'portrait-upside-down': 'landscape',
    }
    new_orient = cycle.get(cur, 'landscape')
    sd_cfg['orientation'] = new_orient
    save_sd_config(sd_cfg)
    server_orient = 'portrait' if 'portrait' in new_orient else 'landscape'
    try:
        from api import call_change_orientation
        call_change_orientation(wifi_cfg.get('server_url',''), mac_str,
                                wifi_cfg.get('token',''), server_orient)
    except Exception as e:
        print('change-orientation failed:', e)
    print('Orientation ->', new_orient, '— rebooting')
    time.sleep_ms(300)
    hard_reboot()

def action_key_skip():
    print('KEY3: requesting image skip')
    try:
        from api import call_refresh, sync_ntp
        sync_ntp()
        result = call_refresh(wifi_cfg.get('server_url',''), mac_str,
                              wifi_cfg.get('token',''), skip=True, battery=get_bat_pct())
        idx       = result.get('image_index', sd_cfg.get('image_index', 0))
        orient    = result.get('current_orientation', sd_cfg.get('orientation', 'landscape'))
        sleep_int = result.get('sleep_interval', sd_cfg.get('sleep_interval', 900))
        sd_cfg.update({'image_index': idx, 'orientation': orient, 'sleep_interval': sleep_int})
        save_sd_config(sd_cfg)
        images = sd_cfg.get('images', [])
        if images and idx < len(images):
            render_and_sleep(resolve_image_path(images[idx]), orient, sleep_int)
        else:
            go_to_sleep(sleep_int)
    except Exception as e:
        print('Key skip failed:', e)
        go_to_sleep(sd_cfg.get('sleep_interval', 900))

def action_pwr_checkin():
    print('KEY1: forced full server check-in')
    sd_cfg['daily_zip_version'] = ''
    save_sd_config(sd_cfg)
    if not wlan.isconnected():
        ssid_v = wifi_cfg.get('ssid', '')
        pwd_v  = wifi_cfg.get('password', '')
        if ssid_v:
            wlan.active(True)
            if not wlan.isconnected():
                wlan.connect(ssid_v, pwd_v)
                deadline = time.time() + 20
                while not wlan.isconnected() and time.time() < deadline:
                    time.sleep_ms(300)
    if wlan.isconnected():
        run_connected_sequence()
    else:
        print('WiFi unavailable — offline fallback')
        run_offline_fallback()

# ── Offline fallback ──────────────────────────────────────────────────────────
def run_offline_fallback():
    print('Offline — using /images/ cache.')
    images    = sd_cfg.get('images', [])
    idx       = sd_cfg.get('image_index', 0)
    orient    = sd_cfg.get('orientation', 'landscape')
    sleep_int = sd_cfg.get('sleep_interval', 900)
    if images and idx < len(images):
        img_path = resolve_image_path(images[idx])
        try:
            os.stat(img_path)
            render_and_sleep(img_path, orient, sleep_int)
            return
        except OSError:
            pass
    print('No cached image.')
    # Draw diagnostic screen regardless of connectivity
    try:
        server_host = wifi_cfg.get('server_url', 'https://picframes.treee.house')
        for prefix in ('https://', 'http://'):
            if server_host.startswith(prefix):
                server_host = server_host[len(prefix):]
        reason_lines = []
        if fail_reason:
            reason_lines = ['', 'REASON:', fail_reason[:76]]
        _draw_message_screen([
            'NO IMAGES CACHED',
            '',
            'TO ADD PICS VISIT:',
            server_host[:44],
        ] + reason_lines, orient)
    except Exception as e:
        print('Offline screen draw failed:', e)
    if not (wlan.active() and wlan.isconnected()):
        # WiFi creds are set but the connection failed and there is nothing
        # cached to show — reopen the setup AP so credentials can be fixed.
        try:
            _draw_message_screen([
                'WIFI CONNECTION FAILED',
                'SSID: ' + wifi_cfg.get('ssid', '')[:40],
                '',
                'TO RECONFIGURE CONNECT TO WI-FI:',
                'PicFrame-' + mac_str.replace(':', ''),
                'THEN VISIT: picframe.setup',
                'OR: 192.168.4.1',
            ], orient)
        except Exception as e:
            print('Offline screen draw failed:', e)
        start_ap_and_portal(reason='wifi_failed')
        return
    go_to_sleep(sleep_int)

# ── Connected sequence ────────────────────────────────────────────────────────
def run_connected_sequence():
    global fail_reason
    from api import sync_ntp, call_update, call_daily_config, call_daily_zip, call_refresh
    from update import download_and_apply_update

    server_url = wifi_cfg.get('server_url', 'https://picframes.treee.house')
    token      = wifi_cfg.get('token', '')
    update_ver = sd_cfg.get('update_version', '')

    sync_ntp()

    try:
        zip_url = call_update(server_url, mac_str, token, HW_PROFILE, update_ver,
                              fw_version=update_ver)
        if zip_url:
            print('Update available:', zip_url)
            if download_and_apply_update(zip_url):
                print('Update applied — rebooting.')
                try:
                    parsed_ver = zip_url.split('/')[-2].lstrip('v')
                    sd_cfg['update_version'] = parsed_ver
                    save_sd_config(sd_cfg)
                    print('Persisted update_version:', parsed_ver)
                except Exception as ve:
                    print('Failed to persist update_version:', ve)
                time.sleep_ms(300)
                hard_reboot()
    except Exception as e:
        print('/api/update failed:', e)
        fail_reason = ('UPDATE CHECK FAILED: ' + str(e))[:78]
        run_offline_fallback(); return

    try:
        dcfg = call_daily_config(server_url, mac_str, token, fw_version=sd_cfg.get('update_version', ''))
        changed = False
        for key in ('landscape_flipped', 'portrait_flipped'):
            server_val = bool(dcfg.get(key, False))
            if wifi_cfg.get(key, False) != server_val:
                wifi_cfg[key] = server_val
                changed = True
        if changed:
            save_wifi_config(wifi_cfg)
        if 'debug' in dcfg:
            sd_cfg['debug'] = bool(dcfg['debug'])
        sd_cfg['last_checkin'] = time.time()
        merged = merge_sd_config(sd_cfg, dcfg)
        save_sd_config(merged)
        sd_cfg.update(merged)
    except Exception as e:
        print('/api/daily-config failed:', e)
        es = str(e)
        if '403' in es:
            fail_reason = 'CONFIG HTTP 403 - TOKEN REJECTED?'
        else:
            fail_reason = ('CONFIG FAILED: ' + es)[:78]
        run_offline_fallback(); return

    try:
        daily_ver = sd_cfg.get('daily_zip_version', '')
        new_zip   = call_daily_zip(server_url, mac_str, token, daily_ver, '/images/daily.zip')
        if new_zip:
            from unzip import extract_zip
            wipe_images()
            extract_zip('/images/daily.zip', '/images')
            try: os.remove('/images/daily.zip')
            except Exception: pass
            if 'daily_zip_version' in dcfg:
                sd_cfg['daily_zip_version'] = dcfg['daily_zip_version']
            save_sd_config(sd_cfg)
    except Exception as e:
        print('/api/daily-zip failed:', e)
        fail_reason = ('ZIP FAILED: ' + str(e))[:78]
        run_offline_fallback(); return

    try:
        result    = call_refresh(server_url, mac_str, token, skip=True, battery=get_bat_pct())
        idx       = result.get('image_index', sd_cfg.get('image_index', 0))
        orient    = result.get('current_orientation', sd_cfg.get('orientation', 'landscape'))
        sleep_int = result.get('sleep_interval', sd_cfg.get('sleep_interval', 900))
        sd_cfg.update({'image_index': idx, 'orientation': orient, 'sleep_interval': sleep_int})
        save_sd_config(sd_cfg)
    except Exception as e:
        print('/api/refresh failed:', e)
        fail_reason = ('REFRESH FAILED: ' + str(e))[:78]
        run_offline_fallback(); return

    images = sd_cfg.get('images', [])
    if images and idx < len(images):
        img_path = resolve_image_path(images[idx])
        try:
            os.stat(img_path)
        except OSError:
            print('Image not in /images:', img_path)
            fail_reason = 'IMAGE FILE MISSING'
            run_offline_fallback(); return
        render_and_sleep(img_path, orient, sleep_int)
    else:
        print('No images — sleeping.')
        fail_reason = 'PLAYLIST EMPTY'
        go_to_sleep(sd_cfg.get('sleep_interval', 900))

# ── Entry point ───────────────────────────────────────────────────────────────
if key1_pressed:
    action_pwr_checkin()

if key2_pressed:
    action_toggle_orientation()

if key3_pressed:
    action_key_skip()

ssid = wifi_cfg.get('ssid', '')

if not ssid:
    print('No WiFi credentials — starting AP.')
    orientation = sd_cfg.get('orientation', 'landscape')
    _draw_message_screen([
        'PICFRAME SETUP',
        '',
        'CONNECT TO WI-FI:',
        'PicFrame-' + mac_str.replace(':', ''),
        '',
        'THEN VISIT:',
        'http://192.168.4.1/',
    ], orientation)
    start_ap_and_portal(reason='setup')

elif not wlan.isconnected():
    print('WiFi not connected — offline fallback.')
    fail_reason = 'WIFI FAILED: ' + wifi_cfg.get('ssid', 'NO SSID')
    run_offline_fallback()

else:
    server_url = wifi_cfg.get('server_url', 'https://picframes.treee.house')
    reachable = False
    auth_failed = False
    try:
        import urequests
        r = urequests.get(server_url + '/api/update?hw=' + HW_PROFILE + '&version=0', timeout=8)
        status = r.status_code
        r.close()
        if status == 403 or status == 401:
            auth_failed = True
        else:
            reachable = True
    except Exception as e:
        print('Server unreachable:', e)
        fail_reason = ('SERVER UNREACHABLE: ' + str(e))[:78]

    if auth_failed and not fail_reason:
        fail_reason = 'AUTH FAILED: INVALID USERNAME/PASSWORD'
    if not reachable or auth_failed:
        ip       = wlan.ifconfig()[0]
        hostname = 'picframe-' + mac_str.replace(':', '')[-8:].lower()
        orientation = sd_cfg.get('orientation', 'landscape')
        msg = 'INVALID USERNAME/PASSWORD' if auth_failed else 'CANNOT REACH SERVER'
        _draw_message_screen([
            msg,
            server_url[:44],
            '',
            'TO RECONFIGURE VISIT:',
            'http://' + ip + '/',
            'http://' + hostname + '.local/',
        ], orientation)
        start_sta_reconfigure_portal()
    else:
        run_connected_sequence()
