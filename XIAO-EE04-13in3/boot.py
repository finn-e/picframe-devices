# ==========================================
# FILE VERSION: 1.2.0
# DESCRIPTION: Bootloader for XIAO EE04 devices — no SD card, no PMIC.
#   Ensures /images/ directory exists, connects WiFi, registers device token.
# ==========================================
import machine
import os
import network
import json
import time

print('--- EE04 Frame bootup ---')

HW_PROFILE = 'Seeed-EE04-Spectra6-13in3'
RESOLUTION  = '1600x1200'

# ── Safety wait (10 s) — hold KEY1 (GPIO2) to skip ───────────────────────────
_boot_pin = machine.Pin(2, machine.Pin.IN, machine.Pin.PULL_UP)
for _i in range(10, 0, -1):
    if _boot_pin.value() == 0:
        print('KEY1 held — skipping safety wait')
        break
    print('Safety wait: {}s (hold KEY1 to skip)'.format(_i))
    time.sleep(1)
del _boot_pin, _i

# ── Ensure /images/ directory exists ──────────────────────────────────────────
try:
    os.stat('/images')
except OSError:
    try:
        os.mkdir('/images')
        print('/images directory created.')
    except Exception as e:
        print('Failed to create /images directory:', e)

# ── WiFi config ───────────────────────────────────────────────────────────────
try:
    from config import load_wifi_config, save_wifi_config
except Exception as e:
    print('Config module failed:', e)
    def load_wifi_config():
        try:
            with open('/wifi_config.json') as f:
                return json.load(f)
        except Exception:
            return {}
    def save_wifi_config(cfg):
        try:
            with open('/wifi_config.json', 'w') as f:
                json.dump(cfg, f)
        except Exception:
            pass

wifi_cfg = load_wifi_config()
ssid     = wifi_cfg.get('ssid', '')
password = wifi_cfg.get('password', '')

if not ssid:
    print('No WiFi credentials — main.py will handle setup.')
else:
    import ubinascii
    network.WLAN(network.AP_IF).active(False)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to WiFi:', ssid)
        for _attempt in range(3):
            try:
                wlan.connect(ssid, password)
            except OSError as e:
                # Radio can be left in a bad internal state (e.g. after AP
                # mode or soft reboot); reset the interface and retry.
                print('WiFi connect error:', e)
                wlan.active(False)
                time.sleep_ms(500)
                wlan.active(True)
                time.sleep_ms(200)
                continue
            start = time.time()
            while not wlan.isconnected() and time.time() - start < 15:
                time.sleep_ms(200)
            if wlan.isconnected():
                break

    if wlan.isconnected():
        print('WiFi connected:', wlan.ifconfig())

        mac_bytes = wlan.config('mac')
        mac_str   = ubinascii.hexlify(mac_bytes, ':').decode()

        server_url     = wifi_cfg.get('server_url', 'https://picframes.treee.house')
        username       = wifi_cfg.get('username', '')
        token          = wifi_cfg.get('token', '')
        admin_password = wifi_cfg.get('admin_password', '')

        try:
            import urequests
            auth = token if token else admin_password
            body = json.dumps({'mac': mac_str, 'username': username, 'password': auth,
                               'hw_profile': HW_PROFILE, 'resolution': RESOLUTION})
            res  = urequests.post(
                server_url + '/api/register',
                data=body,
                headers={'Content-Type': 'application/json'},
                timeout=10,
            )
            data = json.loads(res.text)
            res.close()
            new_token = data.get('token', '')
            if new_token and new_token != token:
                wifi_cfg['token'] = new_token
                save_wifi_config(wifi_cfg)
                print('Device token saved.')
            else:
                print('Registration ok, token unchanged.')
        except Exception as e:
            print('/api/register failed (continuing with existing token):', e)
    else:
        print('WiFi connection failed — main.py will handle offline/setup.')
