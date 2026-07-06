# ==========================================
# FILE VERSION: 2.0.0
# DESCRIPTION: Software update handler. Downloads GitHub release ZIP,
#              extracts to /images/, copies ALL .py files to Flash unconditionally
#              (per-file version gating retired 2026-07-06).
# ==========================================
import os
import urequests as requests
from unzip import extract_zip

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
    Downloads ZIP from zip_url, extracts to /images/, copies every .py file
    from the update to Flash unconditionally.
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
    # Old .py files were cleared before extraction, so every .py present
    # came from the update ZIP. Copy them all to Flash.
    flash_updated = False
    for filename in sorted(os.listdir('/images')):
        if not filename.endswith('.py'):
            continue
        src_path = '/images/' + filename
        print('Syncing:', filename, '| version:', get_file_version(src_path))
        copy_file(src_path, '/' + filename)
        flash_updated = True
    return flash_updated
