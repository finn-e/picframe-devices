# picframe-devices

Open-source MicroPython firmware for the **PicFrames** e-ink photo frame ecosystem.

Current hardware target: **Waveshare ESP32-S3-PhotoPainter** (7.3" 6-color Spectra display)

## Repository Structure

```
picframe-devices/
├── generic/                    # Hardware-agnostic shared modules
│   ├── api.py                  # PicFrames server API client
│   ├── config.py               # Flash/SD config architecture
│   ├── display_overlay.py      # Battery indicator, branding overlays
│   └── update.py               # OTA update handler
├── ESP32-S3-PhotoPainter/      # Platform-specific firmware
│   ├── axp.py                  # AXP2101 PMIC driver
│   ├── boot.py                 # Bootloader (SD mount, PMIC init)
│   ├── epd.py                  # E-paper display driver
│   ├── main.py                 # Main application loop
│   └── unzip.py                # ZIP extractor for OTA
├── tools/
│   ├── convert_assets.py       # Image → 4-binary-permutation converter
│   └── install.py              # Cross-platform firmware installer
└── .github/workflows/
    └── release.yml             # Automated release packaging
```

## Config Architecture

**Internal Flash (`/config.json`)** — infrastructure parameters only:
| Key | Description |
|-----|-------------|
| `wifi_ssid` | WiFi network name |
| `wifi_pass` | WiFi password |
| `server_url` | PicFrames server URL |
| `username` | Account username |
| `token` | Auth token (starts as password, replaced by Base62 device token after registration) |
| `update_version` | Current firmware version string |
| `landscape_flipped` | 180° flip flag for landscape mode |
| `portrait_flipped` | 180° flip flag for portrait mode |

**SD Card (`/sd/config.json`)** — runtime presentation state:
| Key | Description |
|-----|-------------|
| `orientation` | Current orientation (`landscape`, `portrait`, etc.) |
| `sleep_interval` | Deep sleep duration in seconds |
| `image_index` | Current image index in playlist |
| `daily_zip_version` | Base62 version string of last downloaded asset zip |
| `images` | Array of image basenames (without orientation suffix) |

## Boot Flow

```
Boot
├── SD mount → if missing: show setup screen (Flash only) + start AP
├── Read Flash config
│   └── if no WiFi: bootstrap AP portal
└── Connect WiFi
    ├── if failed: offline fallback (SD cached image → sleep)
    └── Connected:
        ├── NTP sync
        ├── GET /update   → if newer: download ZIP, sync Flash, reboot
        ├── GET /daily-config → deep merge into SD config
        ├── GET /daily-zip → if newer: wipe SD images, extract new ZIP
        ├── POST /refresh → get image_index + orientation + sleep_interval
        └── Render image (battery overlay + branding) → deep sleep
```

## Hardware Buttons

| Button | Action |
|--------|--------|
| **BOOT** (GPIO 0) | Cycle orientation (landscape ↔ portrait + flipped variants). Writes to SD config. Notifies `/change-orientation`. |
| **KEY** (GPIO 4) | Skip to next image. Calls `/refresh` with `skip=true`. |
| **PWR** (GPIO 5) | Force reboot. |

Hold **BOOT** or **KEY** at power-on to trigger orientation toggle or image skip immediately.

## Asset Converter

The `tools/convert_assets.py` script converts source images into all 4 deployment permutations:

```bash
pip install pillow numpy
python tools/convert_assets.py \
  --landscape path/to/landscape.jpg \
  --portrait  path/to/portrait.jpg \
  --name      myphoto \
  --output    ./output
```

Outputs:
- `myphoto_l_u.bin` — Landscape, Unflipped
- `myphoto_l_f.bin` — Landscape, Flipped (180°)
- `myphoto_p_u.bin` — Portrait, Unflipped
- `myphoto_p_f.bin` — Portrait, Flipped (180°)

## Installer

```bash
python tools/install.py --hw ESP32-S3-PhotoPainter --port /dev/ttyACM0
```

Fetches the latest GitHub release for the specified hardware profile and flashes it via `mpremote`.

## Initial Device Setup

1. Flash MicroPython firmware to the device.
2. Copy files from `ESP32-S3-PhotoPainter/` and `generic/` to the device root using `mpremote` or the installer.
3. Power on — device shows setup screen and broadcasts `PicFrame-<MAC>` WiFi AP.
4. Connect to the AP and navigate to `http://192.168.4.1/`.
5. Enter WiFi credentials, server URL, username, and password.
6. Device registers and begins normal operation.

## License

MIT
