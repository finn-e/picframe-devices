# ==========================================
# FILE VERSION: 3.0.0
# DESCRIPTION: Main slideshow loop for ESP32-S3-PhotoPainter.
#   Flow: check WiFi → check server → /api/update → /api/daily-config →
#         /api/daily-zip → /api/refresh → render → sleep
#   Falls back to AP captive portal when WiFi or server is unreachable.
# ==========================================
import time
import machine
import os
import json
import network
import ubinascii

# Shut down radios early to save power during boot
try:
    network.WLAN(network.STA_IF).active(False)
    network.WLAN(network.AP_IF).active(False)
except Exception:
    pass


def hard_reboot():
    print('Hard reboot...')
    try:
        network.WLAN(network.STA_IF).active(False)
        network.WLAN(network.AP_IF).active(False)
    except Exception:
        pass
    try:
        from axp import AXP2101
        AXP2101().reboot()
    except Exception:
        pass
    try:
        machine.deepsleep(100)
    except Exception:
        pass
    machine.reset()


print('--- PicFrame v3.0 starting ---')

# ── Buttons ───────────────────────────────────────────────────────────────────
boot_btn = machine.Pin(0, machine.Pin.IN, machine.Pin.PULL_UP)
key_btn  = machine.Pin(4, machine.Pin.IN, machine.Pin.PULL_UP)
pwr_btn  = machine.Pin(5, machine.Pin.IN, machine.Pin.PULL_DOWN)

time.sleep_ms(100)
boot_pressed = boot_btn.value() == 0
key_pressed  = key_btn.value()  == 0
if boot_pressed:
    print('BOOT held at startup')
    while boot_btn.value() == 0: time.sleep_ms(10)
if key_pressed:
    print('KEY held at startup')
    while key_btn.value() == 0: time.sleep_ms(10)

# ── MAC ───────────────────────────────────────────────────────────────────────
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
mac_bytes = wlan.config('mac')
mac_str   = ubinascii.hexlify(mac_bytes, ':').decode()
print('Device MAC:', mac_str)

# ── Config ────────────────────────────────────────────────────────────────────
import sys
sys.path.insert(0, '/sd')
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
            return {'ssid':'','password':'','server_url':'https://picframes-server.fly.dev',
                    'username':'','token':'','landscape_flipped':False,'portrait_flipped':False}
    def save_wifi_config(c):
        try:
            with open('/wifi_config.json','w') as f: json.dump(c,f)
        except Exception: pass
    def load_sd_config():
        try:
            with open('/sd/config.json') as f: return json.load(f)
        except Exception:
            return {'orientation':'landscape','sleep_interval':900,'image_index':0,
                    'daily_zip_version':'','images':[]}
    def save_sd_config(c):
        try:
            with open('/sd/config.json','w') as f: json.dump(c,f)
        except Exception: pass
    def merge_sd_config(a, b):
        m = dict(a); m.update({k:v for k,v in b.items() if k not in
            {'ssid','password','server_url','username','token','landscape_flipped','portrait_flipped'}}); return m

wifi_cfg = load_wifi_config()
sd_cfg   = load_sd_config()

HW_PROFILE = 'ESP32-S3-PhotoPainter'

# ── Helpers ───────────────────────────────────────────────────────────────────
def sd_mounted():
    try: os.stat('/sd'); return True
    except OSError: return False

def wipe_sd_images():
    try:
        for f in os.listdir('/sd'):
            if f.endswith('.py') or f in ('config.json',): continue
            try: os.remove('/sd/' + f)
            except Exception: pass
    except Exception as e:
        print('SD wipe error:', e)

def get_bat_pct():
    try:
        from axp import AXP2101
        return AXP2101().get_battery_percentage()
    except Exception:
        return None

def go_to_sleep(seconds):
    try:
        from axp import AXP2101
        axp = AXP2101()
        if axp.is_usb_connected():
            print('USB connected — simulating sleep for', seconds, 's')
            _wait_with_buttons(seconds)
            return
        axp.disable_power()
    except Exception as e:
        print('PMIC sleep prep error:', e)
    print('Deep sleeping for', seconds, 's')
    machine.deepsleep(seconds * 1000)

def _wait_with_buttons(seconds):
    end = time.time() + seconds
    while time.time() < end:
        _check_buttons()
        time.sleep_ms(50)

def _check_buttons():
    if boot_btn.value() == 0:
        time.sleep_ms(50)
        if boot_btn.value() == 0:
            while boot_btn.value() == 0: time.sleep_ms(10)
            action_toggle_orientation()
    if key_btn.value() == 0:
        time.sleep_ms(50)
        if key_btn.value() == 0:
            while key_btn.value() == 0: time.sleep_ms(10)
            action_key_skip()

def resolve_image_path(basename):
    orientation = sd_cfg.get('orientation', 'landscape')
    suffix = '_l.bin' if 'landscape' in orientation else '_p.bin'
    return '/sd/' + basename + suffix

# ── Display ───────────────────────────────────────────────────────────────────
def render_and_sleep(img_path, orientation, sleep_interval):
    try:
        from axp import AXP2101
        AXP2101().init()
    except Exception:
        pass
    try:
        network.WLAN(network.STA_IF).active(False)
    except Exception:
        pass
    bat_pct = get_bat_pct()
    try:
        from display_overlay import apply_battery_square, apply_branding_text, apply_caption_overlay, apply_debug_overlay
        buf = bytearray(192000)
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
        caption_mode = img_cfg.get('caption_mode', 'none')
        description  = img_cfg.get('description', '')

        apply_battery_square(buf, bat_pct)
        apply_branding_text(buf, bat_pct)
        apply_caption_overlay(buf, img_path, caption_mode, description, 'portrait' in orientation)

        tmp_path = '/tmp_render.bin'
        with open(tmp_path, 'wb') as f:
            f.write(buf)
        del buf

        from epd import EPD_7in3f
        EPD_7in3f().display_file(tmp_path, orientation=orientation)
        try: os.remove(tmp_path)
        except Exception: pass
        print('Display updated.')
    except Exception as e:
        print('Render failed:', e)
    go_to_sleep(sleep_interval)

def _draw_message_screen(lines, orientation='landscape'):
    """Draw text lines on the EPD. Uses a clean white buffer — no logo file."""
    try:
        from axp import AXP2101
        AXP2101().init()
    except Exception:
        pass
    try:
        # White (nibble 1) packed as 0x11
        buf = bytearray(b'\x11' * 192000)

        from display_overlay import _render_text_line, apply_battery_square
        scale  = 2
        line_h = 8 * scale + 6
        total_h = len(lines) * line_h
        y_start = (480 - total_h) // 2
        for i, line in enumerate(lines):
            _render_text_line(buf, line, y_start + i * line_h, scale=scale)

        apply_battery_square(buf, get_bat_pct())

        out_path = '/msg_screen.bin'
        with open(out_path, 'wb') as f: f.write(buf)
        del buf
        from epd import EPD_7in3f
        EPD_7in3f().display_file(out_path, orientation=orientation)
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
             placeholder="https://picframes-server.fly.dev"></div>
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
    s.bind(('', 80))
    s.listen(1)
    s.settimeout(0.2)

    while True:
        try:
            conn, addr = s.accept()
            req = conn.recv(2048).decode('utf-8', 'ignore')
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
                ssid_v      = p.get('ssid', '').strip()
                wifi_pass_v = p.get('wifi_pass', '').strip()
                server_url_v= p.get('server_url', '').strip() or 'https://picframes-server.fly.dev'
                username_v  = p.get('username', '').strip()
                token_v     = p.get('token', '').strip()
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
                    hard_reboot()
            else:
                html = SETUP_HTML.format(
                    dev_id=dev_id, mac=mac_str.upper(),
                    ssid=escape_html(wifi_cfg.get('ssid', '')),
                    wifi_pass=escape_html(wifi_cfg.get('password', '')),
                    server_url=escape_html(wifi_cfg.get('server_url', 'https://picframes-server.fly.dev')),
                    username=escape_html(wifi_cfg.get('username', '')),
                    err=('<div class="err">Cannot reach PicFrames server. Re-enter credentials to reconfigure.</div>'
                         if reason == 'unreachable' else ''),
                )
                conn.send('HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n')
                conn.send(html)
                conn.close()
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
             placeholder="https://picframes-server.fly.dev" required></div>
    <div class="ig"><label>Username</label>
      <input type="text" name="username" value="{username}"></div>
    <div class="ig"><label>Password</label>
      <input type="password" name="token" value=""
             placeholder="Leave blank to keep existing"></div>
    <input type="submit" value="Save &amp; Reboot">
  </form>
</div></body></html>"""

def start_sta_reconfigure_portal():
    """Web server on the existing STA WiFi connection for server reconfiguration."""
    global wifi_cfg
    import socket

    dev_id = mac_str.replace(':', '')[-8:].upper()
    ip = wlan.ifconfig()[0]

    # Set mDNS hostname so device is reachable as picframe-XXXX.local
    hostname = 'picframe-' + mac_str.replace(':', '')[-8:].lower()
    try:
        network.hostname(hostname)
        print('mDNS hostname:', hostname + '.local')
    except Exception as e:
        print('hostname set failed:', e)

    print('=== RECONFIGURE MODE ===')
    print('Connect to same WiFi network and visit:')
    print('  http://{}/'.format(ip))
    print('  http://{}.local/'.format(hostname))
    print('========================')

    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(1)
    s.settimeout(0.2)

    while True:
        try:
            conn, addr = s.accept()
            req = conn.recv(2048).decode('utf-8', 'ignore')
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
                server_url_v = p.get('server_url', '').strip() or wifi_cfg.get('server_url', '')
                username_v   = p.get('username', '').strip()
                token_v      = p.get('token', '').strip()
                wifi_cfg['server_url'] = server_url_v
                wifi_cfg['username']   = username_v
                if token_v:
                    wifi_cfg['token'] = token_v
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
                conn.send(html)
                conn.close()
        except OSError:
            pass

# ── Button actions ────────────────────────────────────────────────────────────
def action_toggle_orientation():
    print('BOOT: toggling orientation')
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
    print('KEY: requesting image skip')
    try:
        from api import call_refresh, sync_ntp
        sync_ntp()
        result = call_refresh(wifi_cfg.get('server_url',''), mac_str,
                              wifi_cfg.get('token',''), skip=True)
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

# ── Offline fallback ──────────────────────────────────────────────────────────
def run_offline_fallback():
    print('Offline — using SD cache.')
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
    go_to_sleep(sleep_int)

# ── Connected sequence ────────────────────────────────────────────────────────
def run_connected_sequence():
    from api import sync_ntp, call_update, call_daily_config, call_daily_zip, call_refresh
    from update import download_and_apply_update

    server_url = wifi_cfg.get('server_url', 'https://picframes-server.fly.dev')
    token      = wifi_cfg.get('token', '')
    update_ver = sd_cfg.get('update_version', '')

    sync_ntp()

    # /api/update
    try:
        zip_url = call_update(server_url, mac_str, token, HW_PROFILE, update_ver)
        if zip_url:
            print('Update available:', zip_url)
            if download_and_apply_update(zip_url):
                print('Update applied — rebooting.')
                time.sleep_ms(300)
                hard_reboot()
    except Exception as e:
        print('/api/update failed:', e)
        run_offline_fallback(); return

    # /api/daily-config
    try:
        dcfg = call_daily_config(server_url, mac_str, token)
        # Sync flip flags from server into wifi_config if they changed
        changed = False
        for key in ('landscape_flipped', 'portrait_flipped'):
            server_val = bool(dcfg.get(key, False))
            if wifi_cfg.get(key, False) != server_val:
                wifi_cfg[key] = server_val
                changed = True
        if changed:
            save_wifi_config(wifi_cfg)
            print('Flip flags updated from server.')
        merged = merge_sd_config(sd_cfg, dcfg)
        save_sd_config(merged)
        sd_cfg.update(merged)
    except Exception as e:
        print('/api/daily-config failed:', e)
        run_offline_fallback(); return

    # /api/daily-zip
    try:
        daily_ver = sd_cfg.get('daily_zip_version', '')
        new_zip   = call_daily_zip(server_url, mac_str, token, daily_ver, '/sd/daily.zip')
        if new_zip:
            from unzip import extract_zip
            wipe_sd_images()
            extract_zip('/sd/daily.zip', '/sd')
            try: os.remove('/sd/daily.zip')
            except Exception: pass
            if 'daily_zip_version' in dcfg:
                sd_cfg['daily_zip_version'] = dcfg['daily_zip_version']
            save_sd_config(sd_cfg)
    except Exception as e:
        print('/api/daily-zip failed:', e)
        run_offline_fallback(); return

    # /api/refresh
    try:
        result    = call_refresh(server_url, mac_str, token, skip=False)
        idx       = result.get('image_index', sd_cfg.get('image_index', 0))
        orient    = result.get('current_orientation', sd_cfg.get('orientation', 'landscape'))
        sleep_int = result.get('sleep_interval', sd_cfg.get('sleep_interval', 900))
        sd_cfg.update({'image_index': idx, 'orientation': orient, 'sleep_interval': sleep_int})
        save_sd_config(sd_cfg)
    except Exception as e:
        print('/api/refresh failed:', e)
        run_offline_fallback(); return

    # Render
    images = sd_cfg.get('images', [])
    if images and idx < len(images):
        img_path = resolve_image_path(images[idx])
        try:
            os.stat(img_path)
        except OSError:
            print('Image not on SD:', img_path)
            run_offline_fallback(); return
        render_and_sleep(img_path, orient, sleep_int)
    else:
        print('No images — sleeping.')
        go_to_sleep(sd_cfg.get('sleep_interval', 900))

# ── Entry point ───────────────────────────────────────────────────────────────
if boot_pressed:
    action_toggle_orientation()

if key_pressed:
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
    run_offline_fallback()

else:
    # Check server reachability before running the full sequence
    server_url = wifi_cfg.get('server_url', 'https://picframes-server.fly.dev')
    reachable = False
    try:
        import urequests
        r = urequests.get(server_url + '/api/update?hw=' + HW_PROFILE + '&version=0', timeout=8)
        r.close()
        reachable = True
    except Exception as e:
        print('Server unreachable:', e)

    if not reachable:
        ip = wlan.ifconfig()[0]
        hostname = 'picframe-' + mac_str.replace(':', '')[-8:].lower()
        orientation = sd_cfg.get('orientation', 'landscape')
        _draw_message_screen([
            'CANNOT REACH SERVER',
            server_url[:44],
            '',
            'TO RECONFIGURE VISIT:',
            'http://' + ip + '/',
            'http://' + hostname + '.local/',
        ], orientation)
        start_sta_reconfigure_portal()
    else:
        run_connected_sequence()
