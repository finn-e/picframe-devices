import subprocess
import os
import sys
import time

port = '/dev/ttyACM0'
src_dir = 'latest_release/ESP32-S3-PhotoPainter'
files_to_copy = [f for f in os.listdir(src_dir) if f.endswith('.py') or f.endswith('.bin')]

# Wait for port to stabilize
print("Waiting 1 second for USB serial port...", flush=True)
time.sleep(1.0)

# Set permissions
try:
    subprocess.run(["sudo", "chmod", "a+rw", port], check=True)
except Exception as e:
    print("Chmod failed:", e)

mpremote_path = "/home/fin/.local/bin/mpremote"

# Breakout sequence
import serial
try:
    print("Sending keyboard interrupts to break blocking loops...", flush=True)
    ser = serial.Serial(port, 115200, timeout=0.5)
    for _ in range(5):
        ser.write(b'\x03')
        time.sleep(0.1)
    ser.close()
    time.sleep(0.5)
except Exception as e:
    print("Breakout failed (might already be interrupted):", e)

print("Deploying all files using individual mpremote commands to internal flash...")
for filename in files_to_copy:
    local_path = os.path.join(src_dir, filename)
    cmd = [mpremote_path, "connect", port, "fs", "cp", local_path, f":{filename}"]
    print(f"Copying {filename} to Flash...", flush=True)
    
    success = False
    for attempt in range(1, 4):
        try:
            subprocess.run(cmd, check=True)
            success = True
            break
        except subprocess.CalledProcessError as e:
            print(f"Failed to copy {filename} on attempt {attempt}: {e}", flush=True)
            time.sleep(1.0)
            
    if not success:
        print(f"Critical error: Failed to copy {filename} after 3 attempts.")
        sys.exit(1)

# Reset board
print("Resetting board...")
try:
    subprocess.run([mpremote_path, "connect", port, "soft-reset"], check=True)
    print("Deployment successful!")
except Exception as e:
    print("Soft-reset command failed, trying hard reset...", flush=True)
    # Fallback to esptool to reset
    subprocess.run(["/home/fin/.local/bin/esptool", "--port", port, "--before", "default-reset", "--after", "hard-reset", "read_mac"], capture_output=True)
