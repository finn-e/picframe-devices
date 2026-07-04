import subprocess
import time

port = '/dev/ttyACM0'
firmware = 'tools/seeed_xiao_esp32s3_micropython.bin'
esptool_path = "/home/fin/.local/bin/esptool"

print("Flashing MicroPython firmware...", flush=True)
subprocess.run([esptool_path, "--port", port, "write_flash", "0", firmware], check=True)

print("Firmware flashed successfully!", flush=True)
print("Please press the physical RESET button once to boot into MicroPython.", flush=True)
