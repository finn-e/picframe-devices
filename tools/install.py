#!/usr/bin/env python3
# ==========================================
# FILE VERSION: 2.0.0
# DESCRIPTION: Cross-platform installer. Fetches latest GitHub release
#              for the given hardware profile and flashes via mpremote.
# Usage: python install.py --hw ESP32-S3-PhotoPainter --port /dev/ttyACM0
# ==========================================
import argparse, sys, os, subprocess, tempfile, zipfile, json
from urllib import request as urllib_request

GITHUB_REPO = 'finn-e/picframe-devices'
API_BASE = f'https://api.github.com/repos/{GITHUB_REPO}'

def get_latest_asset(hw):
    with urllib_request.urlopen(f'{API_BASE}/releases') as r:
        releases = json.loads(r.read())
    for rel in releases:
        for asset in rel.get('assets', []):
            if hw.lower() in asset['name'].lower() and asset['name'].endswith('.zip'):
                return rel['tag_name'], asset['browser_download_url']
    raise RuntimeError(f'No release found for: {hw}')

def download(url, dest):
    print(f'Downloading: {url}')
    urllib_request.urlretrieve(url, dest)

def flash(zip_path, port):
    print(f'Flashing to {port}...')
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        for root, _, files in os.walk(tmp):
            for fname in files:
                if fname.endswith('.py'):
                    fpath = os.path.join(root, fname)
                    print(f'  Uploading {fname}')
                    subprocess.run(['mpremote','connect',port,'cp',fpath,':/' + fname], check=True)
    print('Done!')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--hw',   default='ESP32-S3-PhotoPainter')
    p.add_argument('--port', default='/dev/ttyACM0')
    args = p.parse_args()
    ver, url = get_latest_asset(args.hw)
    print(f'Latest: {ver}')
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as f:
        zpath = f.name
    try:
        download(url, zpath)
        flash(zpath, args.port)
    finally:
        os.unlink(zpath)

if __name__ == '__main__':
    main()
