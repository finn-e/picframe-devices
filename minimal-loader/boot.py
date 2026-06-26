import machine
import os
import sys
import time

print("--- Minimal Loader Booting ---")

# 1. Initialize PMIC to power up SD card slot
try:
    from axp import AXP2101
    axp = AXP2101()
    axp.init()
    print("PMIC initialized successfully.")
except Exception as e:
    print("PMIC initialization failed:", e)

# 2. Mount SD Card via 4-bit SDMMC Interface (with retries and delay)
sd_mounted = False
for attempt in range(5):
    try:
        sd = machine.SDCard(slot=1, width=4, sck=machine.Pin(39), cmd=machine.Pin(41), data=(machine.Pin(40), machine.Pin(1), machine.Pin(2), machine.Pin(38)))
        os.mount(sd, '/sd')
        print("SD card mounted successfully at /sd")
        sd_mounted = True
        break
    except Exception as e:
        print("SD mount attempt {} failed: {}".format(attempt + 1, e))
        time.sleep_ms(200)

# 3. Check if main app exists on SD card
main_exists = False
if sd_mounted:
    try:
        os.stat('/sd/main.py')
        main_exists = True
    except OSError:
        pass

if main_exists:
    print("Main app found on SD card. Delegating sys.path to /sd.")
    sys.path.append('/sd')
else:
    print("Main app not found on SD card. Proceeding to bootstrap mode...")
