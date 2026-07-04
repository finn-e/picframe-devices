# ==========================================
# FILE VERSION: 1.0.0
# DESCRIPTION: Split config architecture for XIAO EE04 devices.
#   wifi_config.json  — internal flash, infrastructure + device identity
#   /images/config.json — internal flash (no SD card on EE04), runtime state
# ==========================================
import json

WIFI_CONFIG_PATH   = '/wifi_config.json'
SD_CONFIG_PATH     = '/images/config.json'   # "SD" misnomer kept for API compat

WIFI_KEYS = {
    'ssid', 'password', 'server_url', 'username', 'token',
    'landscape_flipped', 'portrait_flipped',
}

DEFAULT_WIFI_CONFIG = {
    'ssid':               '',
    'password':           '',
    'server_url':         'https://picframes.treee.house',
    'username':           '',
    'token':              '',
    'landscape_flipped':  False,
    'portrait_flipped':   False,
}

DEFAULT_SD_CONFIG = {
    'orientation':       'landscape',
    'sleep_interval':    900,
    'image_index':       0,
    'daily_zip_version': '',
    'images':            [],
}


def load_wifi_config():
    cfg = dict(DEFAULT_WIFI_CONFIG)
    try:
        with open(WIFI_CONFIG_PATH, 'r') as f:
            data = json.load(f)
        for k in WIFI_KEYS:
            if k in data:
                cfg[k] = data[k]
    except Exception as e:
        print('wifi_config load error:', e)
    return cfg


def save_wifi_config(cfg):
    to_save = {k: cfg[k] for k in WIFI_KEYS if k in cfg}
    try:
        with open(WIFI_CONFIG_PATH, 'w') as f:
            json.dump(to_save, f)
        return True
    except Exception as e:
        print('wifi_config save error:', e)
        return False


def load_sd_config():
    cfg = dict(DEFAULT_SD_CONFIG)
    try:
        with open(SD_CONFIG_PATH, 'r') as f:
            data = json.load(f)
        for k, v in data.items():
            if k not in WIFI_KEYS:
                cfg[k] = v
    except Exception as e:
        print('images config load error:', e)
    return cfg


def save_sd_config(cfg):
    to_save = {k: v for k, v in cfg.items() if k not in WIFI_KEYS}
    try:
        with open(SD_CONFIG_PATH, 'w') as f:
            json.dump(to_save, f)
        return True
    except Exception as e:
        print('images config save error:', e)
        return False


def merge_sd_config(existing, incoming):
    """Merge incoming dict into existing config, ignoring wifi keys.
    daily_zip_version is also excluded: adopting the server's version here
    would make the subsequent daily-zip request report "already current"
    (304) before the zip was ever downloaded. It is saved explicitly after
    a successful download + extraction instead."""
    merged = dict(existing)
    for k, v in incoming.items():
        if k not in WIFI_KEYS and k != 'daily_zip_version':
            merged[k] = v
    return merged
