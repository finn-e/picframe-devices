import subprocess
import os
import sys
import time
import serial

port = '/dev/ttyACM0'
src_dir = 'XIAO-EE04-7in3'
files_to_copy = [f for f in os.listdir(src_dir) if f.endswith('.py') or f.endswith('.bin')]

mpremote_path = "/home/fin/.local/bin/mpremote"

# Set permissions
try:
    subprocess.run(["sudo", "chmod", "a+rw", port], check=True)
except Exception as e:
    print("Chmod failed:", e)

# Breakout sequence: send Ctrl-C multiple times to break the boot.py safety wait
try:
    print("Sending keyboard interrupts to break safety wait and drop to REPL...", flush=True)
    ser = serial.Serial(port, 115200, timeout=0.5)
    for _ in range(10):
        ser.write(b'\x03')
        time.sleep(0.1)
    ser.close()
    time.sleep(0.5)
except Exception as e:
    print("Breakout failed:", e)

print("Building single mpremote resume command to deploy all files...", flush=True)
# Note: we use "resume" instead of "connect /dev/ttyACM0" so it does not auto soft-reset the device on connection.
cmd = [mpremote_path, "resume"]
for filename in files_to_copy:
    local_path = os.path.join(src_dir, filename)
    cmd += ["fs", "cp", local_path, f":{filename}"]
cmd += ["soft-reset"]

print("Executing deployment...", flush=True)
success = False
for attempt in range(1, 4):
    try:
        subprocess.run(cmd, check=True)
        success = True
        break
    except subprocess.CalledProcessError as e:
        print(f"Failed to execute deployment on attempt {attempt}: {e}", flush=True)
        time.sleep(1.0)
        # Try breaking out again before retry
        try:
            ser = serial.Serial(port, 115200, timeout=0.5)
            for _ in range(10):
                ser.write(b'\x03')
                time.sleep(0.1)
            ser.close()
            time.sleep(0.5)
        except:
            pass

if success:
    print("Deployment completely successful!")
else:
    print("Critical error: Failed to copy files.")
    sys.exit(1)
