# picframe-devices

Open-source MicroPython firmware for the **PicFrames** e-ink photo frame ecosystem.

Hardware targets:

| Directory | Board | Panel | Notes |
|-----------|-------|-------|-------|
| `ESP32-S3-PhotoPainter/` | Waveshare ESP32-S3-PhotoPainter | 7.3" 6-color Spectra, 800×480 | SD card + AXP2101 PMIC |
| `XIAO-EE04-7in3/` | Seeed XIAO ESP32-S3 | 7.3" Spectra 6, 800×480 | No SD, no PMIC — images cached in `/images/` on internal flash |
| `XIAO-EE04-13in3/` | Seeed XIAO ESP32-S3 | 13.3" Spectra 6, 1200×1600 dual-controller | Server-side 1200×1600 asset pipeline not implemented yet |

## Repository Structure

```
picframe-devices/
├── generic/                    # Hardware-agnostic shared modules
│   ├── api.py                  # PicFrames server API client
│   ├── config.py               # Flash/SD config architecture
│   ├── display_overlay.py      # Battery indicator, branding overlays
│   └── update.py               # OTA update handler
├── ESP32-S3-PhotoPainter/      # Board-specific firmware (see table above;
├── XIAO-EE04-7in3/             #   each dir carries its own boot.py, main.py,
├── XIAO-EE04-13in3/            #   epd.py, api.py, config.py, unzip.py)
├── deploy_xiao.py              # USB deploy of XIAO-EE04-7in3/ via mpremote
├── tools/
│   ├── convert_assets.py       # Image → 4-binary-permutation converter
│   ├── install.py              # Cross-platform firmware installer
│   └── *.bin                   # MicroPython firmware images per board
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
boot.py
├── Read Flash config
│   └── if no WiFi creds: main.py starts the AP captive portal
├── Connect WiFi (retries with radio reset — recovers from
│   "Wifi Internal State Error" left by AP mode / soft reboots)
└── POST /api/register (username + user password, or existing device token)
    └── stores the returned device token in Flash config

main.py
├── WiFi failed?
│   ├── cached image available → render it, sleep (transient outage)
│   └── nothing cached → re-open the setup AP with an error banner
├── Server unreachable / 401/403 → on-screen message + reconfigure portal
└── Connected:
    ├── NTP sync
    ├── GET /api/update      → if newer firmware: download ZIP, apply, reboot
    ├── GET /api/daily-config → merge into SD//images/ config
    ├── GET /api/daily-zip   → if newer: wipe cached images, extract new ZIP
    ├── POST /api/refresh    → image_index + orientation + sleep_interval
    └── Render image (battery overlay + branding) → deep sleep
```

All device API calls send `X-Device-Mac` and `X-Device-Token` headers; the
token is issued by `/api/register` and stored in Flash config. Non-200
responses are raised as errors (falling back to the offline/reconfigure path).
The captive portal reads the full HTTP request (Content-Length aware) and
disables the STA interface while the AP runs, so weak/flaky setup APs and
truncated passwords are fixed as of 2026-07-04.

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
4. Connect to the AP and navigate to `http://picframe.setup/`.
5. Enter WiFi credentials, server URL, username, and password.
6. Device registers and begins normal operation.

## Development and Releases

Releases are built automatically when commits are pushed to the `trunk` branch. The version number and CHANGELOG are generated automatically from commit messages using [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/#specification) and the `paulhatch/semantic-version` GitHub Action.

### Commit Message Guidelines:
All commit messages must follow the Conventional Commits specification:
* **Fixes (triggers Patch version increment):**
  `fix: resolve E-Paper display busy timeout lockup`
* **Features (triggers Minor version increment):**
  `feat: add picframe.setup DNS alias for captive portal`
* **Breaking Changes (triggers Major version increment):**
  `feat!: overhaul OTA update flow to wipe old SD scripts`
  or containing `BREAKING CHANGE:` in the footer.

## License

MIT
