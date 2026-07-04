# ==========================================
# FILE VERSION: 1.0.0
# DESCRIPTION: Hardware driver for the Seeed EE04 + 7.3" Spectra 6 e-Paper display.
#   Same Spectra 6 panel family as Waveshare 7.3" (ED2208); pin assignments and
#   power-gating adapted for the XIAO EE04 board.
# ==========================================
import machine
import time

# ── Pin assignments (XIAO ESP32-S3 Plus on EE04) ──────────────────────────────
# Source: Seeed_GFX EPaper_Board_Pins_Setups.h, USE_XIAO_EPAPER_DISPLAY_BOARD_EE04
EPD_SCK_PIN  = 7    # D8
EPD_MOSI_PIN = 9    # D10
EPD_CS_PIN   = 44   # D7
EPD_DC_PIN   = 10   # D16
EPD_RST_PIN  = 38   # D11
EPD_BUSY_PIN = 4    # D3  — active LOW (low = busy, high = ready)

# TPS22916 load-switch enable (confirmed from Seeed_GFX EPaper_Board_Pins_Setups.h)
EPD_POWER_PIN = 43  # D6 / TFT_ENABLE — drive HIGH to power panel, LOW for sleep

EPD_WIDTH  = 800
EPD_HEIGHT = 480


class EPD_7in3f:
    def __init__(self):
        # Power on the panel via TPS22916 load switch
        self._power = machine.Pin(EPD_POWER_PIN, machine.Pin.OUT)
        self._power.value(1)
        time.sleep_ms(50)

        self.dc   = machine.Pin(EPD_DC_PIN,   machine.Pin.OUT)
        self.cs   = machine.Pin(EPD_CS_PIN,   machine.Pin.OUT)
        self.rst  = machine.Pin(EPD_RST_PIN,  machine.Pin.OUT)
        self.busy = machine.Pin(EPD_BUSY_PIN, machine.Pin.IN, machine.Pin.PULL_UP)

        self.spi = machine.SPI(1, baudrate=10_000_000, polarity=0, phase=0,
                               sck=machine.Pin(EPD_SCK_PIN),
                               mosi=machine.Pin(EPD_MOSI_PIN))

        self.cs.value(1)
        self.dc.value(0)
        self.rst.value(1)
        self.has_timeout = False

    # ── Low-level SPI helpers ─────────────────────────────────────────────────

    def reset(self):
        self.rst.value(1); time.sleep_ms(50)
        self.rst.value(0); time.sleep_ms(20)
        self.rst.value(1); time.sleep_ms(50)

    def read_busy(self, timeout_ms=3000):
        """Wait until BUSY goes High (panel ready), with timeout."""
        if getattr(self, 'has_timeout', False):
            return
        time.sleep_ms(200)
        start = time.ticks_ms()
        while self.busy.value() == 0:
            time.sleep_ms(10)
            if time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
                print('EPD busy timeout ({}s)!'.format(timeout_ms // 1000))
                self.has_timeout = True
                break

    def send_command(self, cmd):
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes([cmd]))
        self.cs.value(1)

    def send_data(self, data):
        self.dc.value(1)
        self.cs.value(0)
        if isinstance(data, int):
            self.spi.write(bytes([data]))
        else:
            self.spi.write(data)
        self.cs.value(1)

    # ── Panel initialisation ──────────────────────────────────────────────────

    def init(self):
        """Spectra 6 init sequence — identical to Waveshare 7.3" ED2208."""
        self.reset()
        self.read_busy()
        time.sleep_ms(50)

        self.send_command(0xAA)  # CMDH
        self.send_data(bytes([0x49, 0x55, 0x20, 0x08, 0x09, 0x18]))

        self.send_command(0x01)
        self.send_data(0x3F)

        self.send_command(0x00)
        self.send_data(bytes([0x5F, 0x69]))

        self.send_command(0x03)
        self.send_data(bytes([0x00, 0x54, 0x00, 0x44]))

        self.send_command(0x05)
        self.send_data(bytes([0x40, 0x1F, 0x1F, 0x2C]))

        self.send_command(0x06)
        self.send_data(bytes([0x6F, 0x1F, 0x17, 0x49]))

        self.send_command(0x08)
        self.send_data(bytes([0x6F, 0x1F, 0x1F, 0x22]))

        self.send_command(0x30)
        self.send_data(0x03)

        self.send_command(0x50)
        self.send_data(0x3F)

        self.send_command(0x60)
        self.send_data(bytes([0x02, 0x00]))

        self.send_command(0x61)
        self.send_data(bytes([0x03, 0x20, 0x01, 0xE0]))  # 800 × 480

        self.send_command(0x84)
        self.send_data(0x01)

        self.send_command(0xE3)
        self.send_data(0x2F)

        self.send_command(0x04)  # PWR_ON
        self.read_busy()

    def turn_on_display(self):
        self.send_command(0x04)  # POWER_ON
        self.read_busy()

        self.send_command(0x06)
        self.send_data(bytes([0x6F, 0x1F, 0x17, 0x49]))

        self.send_command(0x12)  # DISPLAY_REFRESH
        self.send_data(0x00)
        self.read_busy(30000)

        self.send_command(0x02)  # POWER_OFF
        self.send_data(0x00)
        self.read_busy()

    # ── Public interface ──────────────────────────────────────────────────────

    def display_file(self, filepath, battery_level=None, orientation=None):
        """
        Stream a 192 000-byte 4bpp RAW bitstream to the panel.
        Handles 180° rotation the same way as the Waveshare driver.
        Cuts panel power via TPS22916 after display refresh and deep-sleep.
        """
        self.init()
        self.send_command(0x10)  # Write RAM

        self.dc.value(1)
        self.cs.value(0)

        if orientation is None:
            orientation = 'landscape'
            for path in ['/images/config.json', '/wifi_config.json']:
                try:
                    import json
                    with open(path, 'r') as f:
                        cfg = json.load(f)
                        orientation = cfg.get('orientation', 'landscape')
                        break
                except Exception:
                    pass

        rotate_180 = 'upside-down' not in orientation

        if rotate_180:
            chunk_size = 4000
            num_chunks = 48
            chunk = bytearray(chunk_size)
            with open(filepath, 'rb') as f:
                for chunk_idx in range(num_chunks - 1, -1, -1):
                    f.seek(chunk_idx * chunk_size)
                    f.readinto(chunk)
                    for j in range(chunk_size // 2):
                        b1 = chunk[j]
                        b2 = chunk[chunk_size - 1 - j]
                        chunk[j]               = ((b2 & 0x0F) << 4) | (b2 >> 4)
                        chunk[chunk_size-1-j]  = ((b1 & 0x0F) << 4) | (b1 >> 4)
                    self.spi.write(chunk)
        else:
            chunk = bytearray(4096)
            with open(filepath, 'rb') as f:
                while True:
                    n = f.readinto(chunk)
                    if not n:
                        break
                    self.spi.write(chunk if n == len(chunk) else memoryview(chunk)[:n])

        self.cs.value(1)
        self.turn_on_display()

        # Panel controller deep-sleep
        self.send_command(0x07)  # Deep Sleep
        self.send_data(0xA5)

        # Cut panel power via TPS22916
        self._power.value(0)
