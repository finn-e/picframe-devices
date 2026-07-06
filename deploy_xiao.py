import subprocess
import os
import sys
import time
import hashlib
import serial

port = '/dev/ttyACM0'
board_dir = 'XIAO-EE04-7in3'
generic_dir = 'generic'

# Merge file sets: generic/ first, then the board dir (board wins on collision).
files_to_copy = {}  # filename -> local path
for src_dir in (generic_dir, board_dir):
    for f in sorted(os.listdir(src_dir)):
        if f.endswith('.py') or f.endswith('.bin'):
            files_to_copy[f] = os.path.join(src_dir, f)

mpremote_path = "/home/fin/.local/bin/mpremote"

def local_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def send_breakout():
    """Send Ctrl-C repeatedly to break the boot.py safety wait and drop to REPL."""
    try:
        ser = serial.Serial(port, 115200, timeout=0.5)
        for _ in range(10):
            ser.write(b'\x03')
            time.sleep(0.1)
        ser.close()
        time.sleep(0.5)
    except Exception as e:
        print("Breakout failed:", e)

# Set permissions
try:
    subprocess.run(["sudo", "chmod", "a+rw", port], check=True)
except Exception as e:
    print("Chmod failed:", e)

print("Sending keyboard interrupts to break safety wait and drop to REPL...", flush=True)
send_breakout()

# Device-side sha256 script: prints "<filename> <hexdigest|MISSING>" per file.
_verify_snippet = (
    "import hashlib, binascii\n"
    "for fn in [{names}]:\n"
    "    try:\n"
    "        h = hashlib.sha256()\n"
    "        with open('/' + fn, 'rb') as f:\n"
    "            while True:\n"
    "                b = f.read(1024)\n"
    "                if not b: break\n"
    "                h.update(b)\n"
    "        print(fn, binascii.hexlify(h.digest()).decode())\n"
    "    except Exception:\n"
    "        print(fn, 'MISSING')\n"
)

def device_sha256(filenames):
    """Return {filename: hexdigest-or-'MISSING'} computed on the device."""
    names = ", ".join("'%s'" % n for n in filenames)
    out = subprocess.run(
        [mpremote_path, "connect", port, "exec", _verify_snippet.format(names=names)],
        check=True, capture_output=True, text=True,
    ).stdout
    result = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2:
            result[parts[0]] = parts[1]
    return result

print("Deploying merged file set (generic/ + %s, board wins collisions)..." % board_dir, flush=True)
pending = dict(files_to_copy)
success = False
for attempt in range(1, 4):
    try:
        # Note: explicit "connect <port>" (not "resume") — resume intermittently
        # reports "no device found".
        cmd = [mpremote_path, "connect", port]
        for filename in sorted(pending):
            cmd += ["fs", "cp", pending[filename], f":{filename}"]
        subprocess.run(cmd, check=True)

        # sha256-verify every copied file against the local copy (a truncated
        # copy once shipped and caused an on-device SyntaxError).
        print("Verifying sha256 of copied files...", flush=True)
        remote = device_sha256(sorted(pending))
        bad = {fn for fn, path in pending.items()
               if remote.get(fn) != local_sha256(path)}
        for fn in sorted(bad):
            print(f"  MISMATCH: {fn} (device: {remote.get(fn, 'no output')})", flush=True)
        if not bad:
            success = True
            break
        pending = {fn: files_to_copy[fn] for fn in bad}
        print(f"Retrying {len(pending)} file(s)...", flush=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to execute deployment on attempt {attempt}: {e}", flush=True)
        time.sleep(1.0)
        send_breakout()

if success:
    print("All files copied and sha256-verified. Soft-resetting...", flush=True)
    subprocess.run([mpremote_path, "connect", port, "soft-reset"], check=True)
    print("Deployment completely successful!")
else:
    print("Critical error: Failed to copy/verify files.")
    sys.exit(1)
