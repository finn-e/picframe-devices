# ==========================================
# FILE VERSION: 1.0.0
# DESCRIPTION: Software update handler for XIAO EE04 devices.
#   Downloads GitHub release ZIP to /images/, extracts, syncs newer files to Flash.
# ==========================================
import os
import urequests as requests
from unzip import extract_zip

FILES_TO_SYNC = ['boot.py', 'main.py', 'epd.py', 'battery.py', 'unzip.py',
                 'config.py', 'api.py', 'display_overlay.py', 'update.py']

def get_file_version(path):
    try:
        with open(path, 'r') as f:
            for _ in range(15):
                line = f.readline()
                if not line:
                    break
                if 'FILE VERSION:' in line:
                    parts = line.split('FILE VERSION:')
                    if len(parts) > 1:
                        return parts[1].strip().split('#')[0].strip()
    except Exception:
        pass
    return None

def parse_version(ver_str):
    if not ver_str:
        return (0, 0, 0)
    try:
        return tuple(int(x) for x in ver_str.split('.')[:3])
    except Exception:
        return (0, 0, 0)

def copy_file(src, dst):
    with open(src, 'rb') as s:
        with open(dst, 'wb') as d:
            buf = bytearray(1024)
            while True:
                n = s.readinto(buf)
                if not n:
                    break
                d.write(buf if n == len(buf) else buf[:n])

def clear_images_py_files():
    try:
        for filename in os.listdir('/images'):
            if filename.endswith('.py'):
                try:
                    os.remove('/images/' + filename)
                except Exception:
                    pass
    except Exception as e:
        print('Error clearing old .py files from /images:', e)

def download_and_apply_update(zip_url, zip_dest='/images/update.zip'):
    """
    Downloads ZIP from zip_url, extracts to /images/, syncs newer files to Flash.
    Returns True if any flash files were updated (soft reset recommended).
    """
    print('Downloading update from:', zip_url)
    res = requests.get(zip_url, timeout=30)
    with open(zip_dest, 'wb') as f:
        chunk = bytearray(4096)
        while True:
            n = res.raw.readinto(chunk)
            if not n:
                break
            f.write(chunk if n == len(chunk) else chunk[:n])
    res.close()
    print('Download complete. Clearing old .py files from /images...')
    clear_images_py_files()
    print('Extracting...')
    extract_zip(zip_dest, '/images')
    try:
        os.remove(zip_dest)
    except Exception:
        pass
    flash_updated = False
    for filename in FILES_TO_SYNC:
        src_path   = '/images/' + filename
        flash_path = '/' + filename
        try:
            os.stat(src_path)
        except OSError:
            continue
        ver_src   = get_file_version(src_path)
        ver_flash = get_file_version(flash_path)
        print('Checking:', filename, '| new:', ver_src, '| flash:', ver_flash)
        if parse_version(ver_src) > parse_version(ver_flash):
            print('Upgrading', filename, 'to', ver_src)
            copy_file(src_path, flash_path)
            flash_updated = True
    return flash_updated
