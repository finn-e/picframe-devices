import sys
import os
import time
import serial

# Monkey-patch serial.Serial to ignore DTR/RTS updates which cause Protocol Error [Errno 71] on ESP32-S3 USB
def no_op(self):
    pass
serial.Serial._update_rts_state = no_op
serial.Serial._update_dtr_state = no_op

from mpremote.main import main

port = '/dev/ttyACM0'
board_dir = 'XIAO-EE04-7in3'
# Merge file sets: generic/ first, then the board dir (board wins on collision).
files_to_copy = {}  # filename -> local path
for src_dir in ('generic', board_dir):
    for f in sorted(os.listdir(src_dir)):
        if f.endswith('.py') or f.endswith('.bin'):
            files_to_copy[f] = os.path.join(src_dir, f)

# Wait for port to stabilize
print("Waiting for serial port...", flush=True)
time.sleep(0.5)

# Dynamic Breakout: Wait for boot output, then send Ctrl-C
try:
    print("Opening serial port for dynamic breakout...", flush=True)
    # Using raw serial without monkey-patch for the breakout phase
    from serial import Serial as RawSerial
    ser = RawSerial(port, 115200, timeout=0.1)
    
    # Send initial Ctrl-C in case it's already booting
    ser.write(b'\x03')
    
    start = time.time()
    interrupted = False
    print("Listening for bootloader/wait messages...", flush=True)
    while time.time() - start < 12.0:
        if ser.in_waiting:
            data = ser.read(ser.in_waiting)
            text = data.decode('utf-8', 'ignore')
            sys.stdout.write(text)
            sys.stdout.flush()
            # Send Ctrl-C to interrupt
            ser.write(b'\x03')
            interrupted = True
        else:
            if interrupted:
                # Test if we are in REPL
                ser.write(b'\r\n')
                time.sleep(0.2)
                if ser.in_waiting:
                    resp = ser.read(ser.in_waiting)
                    if b'>>>' in resp or b'raw REPL' in resp:
                        print("\nSuccessfully interrupted and reached REPL!")
                        break
            time.sleep(0.1)
    ser.close()
    time.sleep(0.5)
except Exception as e:
    print("Breakout failed/ignored:", e)

# Build arguments for mpremote resume (so it does not auto soft-reset)
args_copy = ["mpremote", "resume", "fs", "cp"]
for filename in sorted(files_to_copy):
    args_copy.append(files_to_copy[filename])
args_copy.append(":/")

print("Executing patched mpremote transfer...", flush=True)

def run_mpremote(args_list):
    old_argv = sys.argv
    sys.argv = args_list
    try:
        main()
    except SystemExit as e:
        if e.code != 0:
            raise RuntimeError(f"mpremote failed with code {e.code}")
    finally:
        sys.argv = old_argv

try:
    run_mpremote(args_copy)
    print("\nFiles copied successfully! Resetting board...", flush=True)
    time.sleep(0.5)
    run_mpremote(["mpremote", "resume", "soft-reset"])
    print("\nDeployment completed successfully!")
except Exception as e:
    print(f"\nDeployment failed: {e}")
    sys.exit(1)
