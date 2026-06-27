#!/usr/bin/env python3
import os
import re
import sys
import time
import urllib.request
import subprocess
import shutil

PORT_CANDIDATES = ['/dev/ttyACM0', '/dev/ttyACM1', '/dev/ttyUSB0', '/dev/ttyUSB1']
DOWNLOAD_PAGE = "https://micropython.org/download/ESP32_GENERIC_S3/"
FIRMWARE_LOCAL = "latest_micropython.bin"

def find_tool(name):
    """Find a CLI tool: check venv first, then system PATH."""
    venv_path = os.path.join(".", "venv", "bin", name)
    if os.path.exists(venv_path):
        return venv_path
    found = shutil.which(name)
    if found:
        return found
    return None

ESPTOOL = find_tool("esptool") or find_tool("esptool.py")
MPREMOTE = find_tool("mpremote")

if not ESPTOOL:
    print("ERROR: esptool not found. Install with: pip install esptool")
    sys.exit(1)
if not MPREMOTE:
    print("ERROR: mpremote not found. Install with: pip install mpremote")
    sys.exit(1)

def download_latest_firmware():
    print("==================================================")
    print("Step 1: Scraping latest MicroPython firmware URL")
    print("==================================================")
    try:
        print(f"Fetching downloads page: {DOWNLOAD_PAGE}")
        req = urllib.request.Request(
            DOWNLOAD_PAGE, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
    except Exception as e:
        print(f"Failed to fetch download page: {e}")
        sys.exit(1)

    # Search for all SPIRAM_OCT bin links
    pattern = r'href="(/resources/firmware/ESP32_GENERIC_S3-SPIRAM_OCT-[^"]+\.bin)"'
    matches = re.findall(pattern, html)
    if not matches:
        print("Error: Could not find any ESP32_GENERIC_S3-SPIRAM_OCT firmware link in HTML.")
        sys.exit(1)

    # The first release link is typically the latest stable release.
    # Let's filter out previews unless no stable releases are found.
    stable_links = [m for m in matches if "preview" not in m]
    latest_path = stable_links[0] if stable_links else matches[0]
    download_url = "https://micropython.org" + latest_path
    
    print(f"Latest firmware found: {download_url}")
    print("Downloading...")
    
    try:
        urllib.request.urlretrieve(download_url, FIRMWARE_LOCAL)
        print(f"Downloaded successfully and saved as: {FIRMWARE_LOCAL}")
    except Exception as e:
        print(f"Failed to download firmware file: {e}")
        sys.exit(1)

def detect_device_port():
    print("\n==================================================")
    print("Step 2: Detecting ESP32-S3 Serial/JTAG Port")
    print("==================================================")
    print("Waiting for port to appear... (Hold BOOT, press RESET if needed)")
    
    detected_port = None
    while not detected_port:
        for port in PORT_CANDIDATES:
            if os.path.exists(port):
                detected_port = port
                break
        if not detected_port:
            print(".", end="", flush=True)
            time.sleep(0.5)
            
    print(f"\nDetected device at port: {detected_port}")
    print("Waiting 1s for connection to stabilize...")
    time.sleep(1.0)
    return detected_port

def flash_firmware(port):
    print("\n==================================================")
    print("Step 3: Erasing and Flashing MicroPython")
    print("==================================================")
    
    # 1. Erase flash
    print("Erasing flash memory...")
    erase_cmd = [ESPTOOL, "-p", port, "-b", "115200", "erase_flash"]
    try:
        subprocess.run(erase_cmd, check=True)
        print("Flash successfully erased.")
    except subprocess.CalledProcessError as e:
        print(f"Erase flash failed: {e}")
        sys.exit(1)
        
    # 2. Write firmware
    print("Writing firmware...")
    flash_cmd = [
        ESPTOOL, "-p", port, "-b", "115200",
        "--before", "default-reset", "--after", "hard-reset", "write-flash",
        "--flash-mode", "dio", "--flash-size", "16MB", "--flash-freq", "80m",
        "0x0", FIRMWARE_LOCAL
    ]
    try:
        subprocess.run(flash_cmd, check=True)
        print("Firmware written successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Write flash failed: {e}")
        sys.exit(1)

def deploy_files(port):
    print("\n==================================================")
    print("Step 4: Deploying Files to Flash")
    print("==================================================")
    print("Waiting 15s for MicroPython filesystem initialization...")
    time.sleep(15.0)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    full_app_dirs = [
        script_dir,
        os.path.join(script_dir, "..", "picframe-waveshare-ESP32-S3-PhotoPainter"),
        os.path.join(script_dir, "picframe-waveshare-ESP32-S3-PhotoPainter")
    ]
    
    source_dir = None
    for d in full_app_dirs:
        if os.path.exists(os.path.join(d, "epd.py")) and os.path.exists(os.path.join(d, "main.py")):
            source_dir = d
            break
            
    files_to_copy = []
    if source_dir:
        print(f"Detected full application files in: {source_dir}")
        files_to_copy = [
            (os.path.join(source_dir, "boot.py"), ":boot.py"),
            (os.path.join(source_dir, "main.py"), ":main.py"),
            (os.path.join(source_dir, "axp.py"), ":axp.py"),
            (os.path.join(source_dir, "epd.py"), ":epd.py"),
            (os.path.join(source_dir, "unzip.py"), ":unzip.py"),
            (os.path.join(source_dir, "picframes_logo_p.bin"), ":images/picframes_logo_p.bin"),
            (os.path.join(source_dir, "picframes_logo_l.bin"), ":images/picframes_logo_l.bin")
        ]
    else:
        minimal_dir = os.path.join(script_dir, "minimal-loader")
        if not os.path.exists(minimal_dir):
            minimal_dir = os.path.join(script_dir, "..", "hardware-debugging", "minimal-loader")
            
        print(f"Full application files not found. Falling back to minimal loader in: {minimal_dir}")
        files_to_copy = [
            (os.path.join(minimal_dir, "boot.py"), ":boot.py"),
            (os.path.join(minimal_dir, "main.py"), ":main.py"),
            (os.path.join(minimal_dir, "axp.py"), ":axp.py"),
            (os.path.join(minimal_dir, "unzip.py"), ":unzip.py"),
            (os.path.join(minimal_dir, "picframes_logo_p.bin"), ":images/picframes_logo_p.bin"),
            (os.path.join(minimal_dir, "picframes_logo_l.bin"), ":images/picframes_logo_l.bin")
        ]
        
    # Ensure /images directory exists on internal Flash
    print("Creating /images directory on internal Flash...")
    mkdir_cmd = [MPREMOTE, "connect", port, "exec", "import os; os.mkdir('/images') if 'images' not in os.listdir('/') else None"]
    try:
        subprocess.run(mkdir_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    for src, dst in files_to_copy:
        if not os.path.exists(src):
            print(f"Warning: Source file {src} does not exist. Skipping.")
            continue
            
        print(f"Deploying {os.path.basename(src)} -> {dst}...")
        cp_cmd = [MPREMOTE, "connect", port, "fs", "cp", src, dst]
        
        success = False
        for attempt in range(3):
            try:
                subprocess.run(cp_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                success = True
                break
            except subprocess.CalledProcessError:
                time.sleep(1.0)
                
        if not success:
            print(f"Error: Failed to copy {src} to internal Flash.")
            sys.exit(1)
            
    print("Files deployed successfully.")
    
    print("\n==================================================")
    print("Step 5: Resetting the Device")
    print("==================================================")
    reboot_cmd = [MPREMOTE, "connect", port, "soft-reset"]
    try:
        subprocess.run(reboot_cmd, check=True, stdout=subprocess.DEVNULL)
        print("Reset triggered successfully. System is now running!")
    except subprocess.CalledProcessError:
        print("Failed to trigger soft-reset. Please press the physical RESET button on the board.")

if __name__ == "__main__":
    deploy_only = "--deploy-only" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--deploy-only"]
    
    if len(args) > 0:
        port = args[0]
        print(f"Using explicitly specified port: {port}")
    else:
        port = detect_device_port()
        
    if not deploy_only:
        download_latest_firmware()
        flash_firmware(port)
        
    deploy_files(port)
    print("\nAll tasks completed successfully!")
