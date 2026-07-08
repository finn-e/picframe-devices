# ==========================================
# FILE VERSION: 2.4.0
# DESCRIPTION: Bootloader — mounts SD, connects WiFi, registers device,
#              then hands off to main.py. No AP portal here.
# ==========================================
import machine
import os
import network
import json
import time

print('--- Frame bootup ---')

HW_PROFILE = 'Waveshare-PhotoPainter-7in3'
RESOLUTION  = '800x480'

# ── Safety wait (10 s) — hold BOOT to skip ────────────────────────────────────
_boot_pin = machine.Pin(0, machine.Pin.IN, machine.Pin.PULL_UP)
for _i in range(10, 0, -1):
    if _boot_pin.value() == 0:
        print('BOOT held — skipping safety wait')
        break
    print('Safety wait: {}s (hold BOOT to skip)'.format(_i))
    time.sleep(1)
del _boot_pin, _i

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

        # ── Register / refresh device token ───────────────────────────────────
        mac_bytes = wlan.config('mac')
        mac_str   = ubinascii.hexlify(mac_bytes, ':').decode()

        server_url     = wifi_cfg.get('server_url', 'https://picframes.treee.house')
        username       = wifi_cfg.get('username', '')
        token          = wifi_cfg.get('token', '')
        admin_password = wifi_cfg.get('admin_password', '')

        try:
            import urequests
            # On first boot token is empty — authenticate with admin password instead
            used_token = bool(token)
            auth = token if token else admin_password
            body = json.dumps({'mac': mac_str, 'username': username, 'password': auth,
                               'hw_profile': HW_PROFILE, 'resolution': RESOLUTION})
            res  = urequests.post(
                server_url + '/api/register',
                data=body,
                headers={'Content-Type': 'application/json'},
                timeout=10,
            )
            status = res.status_code
            data   = json.loads(res.text)
            res.close()
            if status == 200 and 'error' not in data:
                new_token = data.get('token', '')
                if new_token and new_token != token:
                    wifi_cfg['token'] = new_token
                    save_wifi_config(wifi_cfg)
                    print('Device token saved.')
                else:
                    print('Registration ok, token unchanged.')
            elif used_token and admin_password:
                # Token was stale — retry once with the stored user password
                body2 = json.dumps({'mac': mac_str, 'username': username,
                                    'password': admin_password,
                                    'hw_profile': HW_PROFILE, 'resolution': RESOLUTION})
                res2  = urequests.post(
                    server_url + '/api/register',
                    data=body2,
                    headers={'Content-Type': 'application/json'},
                    timeout=10,
                )
                status2 = res2.status_code
                data2   = json.loads(res2.text)
                res2.close()
                if status2 == 200 and 'error' not in data2:
                    new_token = data2.get('token', '')
                    if new_token:
                        wifi_cfg['token'] = new_token
                        save_wifi_config(wifi_cfg)
                        print('Device token refreshed via credentials.')
                    else:
                        print('Registration ok (credentials), token unchanged.')
                else:
                    err = data2.get('error', 'unknown')
                    print('/api/register rejected:', status2, err)
            else:
                err = data.get('error', 'unknown')
                print('/api/register rejected:', status, err)
            # Final fallback: re-pair window (server grants token if window open)
            if status != 200 or 'error' in data:
                try:
                    body3 = json.dumps({'mac': mac_str, 'username': username, 'password': '',
                                        'hw_profile': HW_PROFILE, 'resolution': RESOLUTION})
                    res3  = urequests.post(
                        server_url + '/api/register',
                        data=body3,
                        headers={'Content-Type': 'application/json'},
                        timeout=10,
                    )
                    status3 = res3.status_code
                    data3   = json.loads(res3.text)
                    res3.close()
                    if status3 == 200 and 'error' not in data3:
                        new_token = data3.get('token', '')
                        if new_token:
                            wifi_cfg['token'] = new_token
                            save_wifi_config(wifi_cfg)
                            print('Device token re-issued via re-pair window.')
                    else:
                        err3 = data3.get('error', 'unknown')
                        print('/api/register rejected (re-pair):', status3, err3)
                except Exception as e3:
                    print('/api/register re-pair attempt failed:', e3)
        except Exception as e:
            print('/api/register failed (continuing with existing token):', e)
    else:
        print('WiFi connection failed — main.py will handle offline/setup.')
