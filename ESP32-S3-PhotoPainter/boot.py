# ==========================================
# FILE VERSION: 2.0.0
# DESCRIPTION: Bootloader — mounts SD, connects WiFi, registers device,
#              then hands off to main.py. No AP portal here.
# ==========================================
import machine
import os
import network
import json
import time

print('--- Frame bootup ---')

# ── PMIC ──────────────────────────────────────────────────────────────────────
try:
    print('Initializing AXP2101 PMIC...')
    from axp import AXP2101
    AXP2101().init()
    print('PMIC initialized.')
except Exception as e:
    print('PMIC initialization failed:', e)

# ── SD card ───────────────────────────────────────────────────────────────────
sd_mounted = False
for attempt in range(5):
    try:
        sd = machine.SDCard(
            slot=1, width=4, sck=machine.Pin(39), cmd=machine.Pin(41),
            data=(machine.Pin(40), machine.Pin(1), machine.Pin(2), machine.Pin(38))
        )
        os.mount(sd, '/sd')
        print('SD card mounted at /sd')
        sd_mounted = True
        break
    except Exception as e:
        print('SD mount attempt {} failed: {}'.format(attempt + 1, e))
        time.sleep_ms(200)

if not sd_mounted:
    print('SD mount failed — continuing without SD.')

# ── WiFi config ───────────────────────────────────────────────────────────────
try:
    from config import load_wifi_config, save_wifi_config
except Exception as e:
    print('Config module failed:', e)
    # Minimal fallback so boot doesn't crash
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
    # ── Connect WiFi ──────────────────────────────────────────────────────────
    import ubinascii
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to WiFi:', ssid)
        wlan.connect(ssid, password)
        start = time.time()
        while not wlan.isconnected() and time.time() - start < 15:
            time.sleep_ms(200)

    if wlan.isconnected():
        print('WiFi connected:', wlan.ifconfig())

        # ── Register / refresh device token ───────────────────────────────────
        mac_bytes = wlan.config('mac')
        mac_str   = ubinascii.hexlify(mac_bytes, ':').decode()

        server_url = wifi_cfg.get('server_url', 'https://picframes-server.fly.dev')
        username   = wifi_cfg.get('username', '')
        token      = wifi_cfg.get('token', '')

        try:
            import urequests
            body = json.dumps({'mac': mac_str, 'username': username, 'password': token})
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
