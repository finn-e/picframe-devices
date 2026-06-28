#!/usr/bin/env python3
import serial
import time
import sys
import binascii
import os

# Dynamically pick the active port (since port numbers shift on serial crash)
if os.path.exists('/dev/ttyACM2'):
    port = '/dev/ttyACM2'
else:
    port = '/dev/ttyACM1'

print(f"Connecting to device on {port}...")

# Load main.py
with open('ESP32-S3-PhotoPainter/main.py', 'rb') as f:
    main_content = f.read()

def exec_raw_command(ser, cmd_str):
    ser.write(cmd_str.encode('utf-8') + b'\x04')
    response = b''
    start = time.time()
    while time.time() - start < 2.0:
        if ser.in_waiting:
            data = ser.read(ser.in_waiting)
            response += data
            if response.endswith(b'\x04>'):
                break
        time.sleep(0.01)
    return response

# Step 1: Capture Raw REPL
ser = None
while True:
    try:
        ser = serial.Serial(port, 115200, timeout=0.1)
        print(f"Port opened! Flooding {port} with Ctrl-C and entering Raw REPL (Ctrl-A)...")
        # Send Ctrl-C to interrupt, then Ctrl-A to enter raw REPL
        ser.write(b'\x03\x03\x03\x01')
        time.sleep(0.1)
        resp = ser.read_all()
        if b'raw REPL' in resp or b'>>>' in resp or resp.endswith(b'>'):
            # Confirm raw REPL connection
            ser.write(b'\x01')
            time.sleep(0.1)
            resp = ser.read_all()
            if b'raw REPL' in resp or resp.endswith(b'>'):
                print("Captured Raw REPL successfully!")
                break
        ser.close()
    except Exception:
        sys.stdout.write('.')
        sys.stdout.flush()
        time.sleep(0.1)

# Step 2: PMIC early stabilization command (in raw REPL)
init_cmd = (
    "import machine\n"
    "i2c = machine.SoftI2C(sda=machine.Pin(47), scl=machine.Pin(48), freq=100000)\n"
    "i2c.writeto_mem(0x34, 0x16, b'\\x05')\n"
    "val = i2c.readfrom_mem(0x34, 0x90, 1)[0]\n"
    "i2c.writeto_mem(0x34, 0x90, bytes([val & ~0x0E]))\n"
    "print('STABILIZED')\n"
)
resp = exec_raw_command(ser, init_cmd)
print("PMIC stabilization output:", resp.decode('utf-8', 'ignore'))

# Step 3: Write main.py chunk-by-chunk in hex
print("Writing stabilized main.py to Flash...")
exec_raw_command(ser, "import binascii")
exec_raw_command(ser, "with open('main.py', 'wb') as f: pass")
chunk_size = 256
for i in range(0, len(main_content), chunk_size):
    chunk = main_content[i:i+chunk_size]
    hex_str = binascii.hexlify(chunk).decode('ascii')
    cmd = f"with open('main.py', 'ab') as f: f.write(binascii.unhexlify('{hex_str}'))"
    r = exec_raw_command(ser, cmd)
    if b"Traceback" in r:
        print("Error writing main.py chunk:", r)
        sys.exit(1)

print("main.py written successfully!")

# Step 4: Reset board
print("Resetting board to load stabilized firmware...")
# Exit raw REPL
ser.write(b'\x02')
time.sleep(0.1)
ser.write(b"\r\nimport machine; machine.reset()\r\n")
ser.close()
print("Reset sent. Stabilization sequence complete!")
