# ==========================================
# FILE VERSION: 1.0.0
# DESCRIPTION: Hardware driver for Seeed EE04 + 13.3" Spectra 6 dual-controller panel.
#   Panel: 1200 px wide × 1600 px tall (physical, portrait native).
#   Dual SPI controllers share RST/BUSY; each owns a separate CS line.
#   CS_M (GPIO44) drives left half (cols 0-599).
#   CS_S (GPIO41) drives right half (cols 600-1199).
#   Source: Seeed_GFX Setup510 + stephanebhiri/esp32-eink-spectra6-display C++ driver.
# ==========================================
import machine
import time
import gc

# ── Pin assignments ────────────────────────────────────────────────────────────
# All confirmed from Seeed_GFX User_Setups/Setup510_Seeed_XIAO_EPaper_13inch3_colorful.h
EPD_SCK_PIN  = 7    # D8
EPD_MOSI_PIN = 9    # D10
EPD_CS_M_PIN = 44   # D7  — Master / left half (cols 0-599)
EPD_CS_S_PIN = 41   # TFT_CS1 confirmed in Setup510
EPD_DC_PIN   = 10   # D16
EPD_RST_PIN  = 38   # D11 — shared between both controllers
EPD_BUSY_PIN = 4    # D3  — shared; active LOW (low = busy, high = ready)

# TPS22916 load-switch enable (confirmed: TFT_ENABLE=43 for EE04 in EPaper_Board_Pins_Setups.h)
EPD_POWER_PIN = 43  # D6 — drive HIGH to power panel, LOW for sleep

# Physical panel dimensions
EPD_WIDTH  = 1200   # horizontal pixels
EPD_HEIGHT = 1600   # vertical pixels

# Bytes per half-line: 600 px / 2 px-per-byte = 300 bytes
_HALF_LINE_BYTES = EPD_WIDTH // 4   # 300


class EPD_13in3e:
    """
    Driver for 13.3" Spectra 6 dual-controller e-Paper.
    The 960 000-byte .bin image is laid out as:
      bytes 0 .. 479 999   → left half data (CS_M), row-major, 4bpp packed
      bytes 480 000 .. 959 999 → right half data (CS_S), row-major, 4bpp packed
    """

    def __init__(self):
        # Power on panel via TPS22916 load switch
        self._power = machine.Pin(EPD_POWER_PIN, machine.Pin.OUT)
        self._power.value(1)
        time.sleep_ms(50)

        self.dc    = machine.Pin(EPD_DC_PIN,   machine.Pin.OUT)
        self.cs_m  = machine.Pin(EPD_CS_M_PIN, machine.Pin.OUT)
        self.cs_s  = machine.Pin(EPD_CS_S_PIN, machine.Pin.OUT)
        self.rst   = machine.Pin(EPD_RST_PIN,  machine.Pin.OUT)
        self.busy  = machine.Pin(EPD_BUSY_PIN, machine.Pin.IN, machine.Pin.PULL_UP)

        self.spi = machine.SPI(1, baudrate=10_000_000, polarity=0, phase=0,
                               sck=machine.Pin(EPD_SCK_PIN),
                               mosi=machine.Pin(EPD_MOSI_PIN))

        self._cs_all(1)
        self.dc.value(0)
        self.rst.value(1)
        self.has_timeout = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cs_all(self, val):
        self.cs_m.value(val)
        self.cs_s.value(val)

    def _reset(self):
        """Double-reset sequence required for dual-controller init (Waveshare spec)."""
        self.rst.value(1); time.sleep_ms(30)
        self.rst.value(0); time.sleep_ms(30)
        self.rst.value(1); time.sleep_ms(30)
        self.rst.value(0); time.sleep_ms(30)  # second cycle
        self.rst.value(1); time.sleep_ms(30)

    def _wait_busy(self, timeout_ms=30000):
        if getattr(self, 'has_timeout', False):
            return
        time.sleep_ms(20)
        start = time.ticks_ms()
        while self.busy.value() == 0:
            time.sleep_ms(10)
            if time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
                print('EPD 13in3 busy timeout ({}s)!'.format(timeout_ms // 1000))
                self.has_timeout = True
                break

    def _cmd(self, cmd):
        """Send command byte to whichever CS lines are currently pulled low."""
        self.dc.value(0)
        self.spi.write(bytes([cmd]))

    def _data(self, data):
        self.dc.value(1)
        if isinstance(data, int):
            self.spi.write(bytes([data]))
        else:
            self.spi.write(data)

    def _both(self, cmd, data=None):
        """Send command (and optional data) to both controllers."""
        self._cs_all(0)
        self._cmd(cmd)
        if data is not None:
            self._data(data)
        self._cs_all(1)

    def _master(self, cmd, data=None):
        """Send command (and optional data) to Master (CS_M) only."""
        self.cs_m.value(0)
        self._cmd(cmd)
        if data is not None:
            self._data(data)
        self._cs_all(1)

    # ── Initialisation ────────────────────────────────────────────────────────

    def init(self):
        """
        Dual-controller init sequence derived from stephanebhiri C++ driver and
        Seeed_GFX Setup510. Commands are the same as the 7.3" Spectra 6 family
        with panel-size and voltage-tuning differences.
        """
        self._reset()

        # AN_TM (0x74) — analog timing; Master only (per C++ reference)
        self._master(0x74, bytes([0xC0, 0x1C, 0x1C, 0xCC, 0xCC, 0xCC, 0x15, 0x15, 0x55]))

        # CMD66 / CMDH (0xF0) — panel header; both controllers
        self._both(0xF0, bytes([0x49, 0x55, 0x13, 0x5D, 0x05, 0x10]))

        # PSR (0x00) — panel setting; both
        self._both(0x00, bytes([0xDF, 0x69]))

        # CDI (0x50) — VCOM and data interval; both
        self._both(0x50, bytes([0xF7]))

        # TCON (0x60) — gate/source non-overlap; both
        self._both(0x60, bytes([0x03, 0x03]))

        # AGID (0x86); both
        self._both(0x86, bytes([0x10]))

        # PWS (0xE3); both
        self._both(0xE3, bytes([0x22]))

        # CCSET (0xE0); both
        self._both(0xE0, bytes([0x01]))

        # TRES (0x61) — resolution 1200×1600; both
        self._both(0x61, bytes([0x04, 0xB0, 0x06, 0x40]))

        # PWR (0x01) — power settings; Master only
        self._master(0x01, bytes([0x0F, 0x00, 0x28, 0x2C, 0x28, 0x38]))

        # EN_BUF (0xB6); Master only
        self._master(0xB6, bytes([0x07]))

        # BTST_P (0x06) — booster positive; Master only
        self._master(0x06, bytes([0xE8, 0x28]))

        # BOOST_VDDP_EN (0xB7); Master only
        self._master(0xB7, bytes([0x01]))

        # BTST_N (0x05) — booster negative; Master only
        self._master(0x05, bytes([0xE8, 0x28]))

        # BUCK_BOOST_VDDN (0xB0); Master only
        self._master(0xB0, bytes([0x01]))

        # TFT_VCOM_POWER (0xB1); Master only
        self._master(0xB1, bytes([0x02]))

    def _turn_on_display(self):
        """PON → DRF (refresh) → POF sequence; both controllers."""
        # PON (0x04)
        self._both(0x04)
        self._wait_busy()

        time.sleep_ms(50)

        # DRF (0x12) — display refresh
        self._both(0x12, bytes([0x00]))
        self._wait_busy(60000)

        # POF (0x02) — power off (per C++ driver: no busy wait after POF)
        self._both(0x02, bytes([0x00]))

    # ── Frame streaming helpers ───────────────────────────────────────────────

    def _begin_frame(self, cs_pin):
        cs_pin.value(0)
        self._cmd(0x10)      # DTM — start RAM write
        self.dc.value(1)     # switch to data phase

    def _end_frame(self):
        self._cs_all(1)
        self.dc.value(0)

    # ── Public interface ──────────────────────────────────────────────────────

    def display_file(self, filepath, battery_level=None, orientation=None):
        """
        Stream a 960 000-byte 4bpp RAW bitstream file to the panel.
        File layout expected:
          bytes [0, 480000)   → CS_M (left half: cols 0-599, rows 0-1599, row-major)
          bytes [480000, 960000) → CS_S (right half: cols 600-1199, rows 0-1599)

        NOTE: 180-degree rotation is not implemented for this driver.
        The server pipeline will need to pre-rotate images if needed.
        """
        self.init()

        chunk = bytearray(4096)

        # ── Left half (CS_M) ─────────────────────────────────────────────────
        self._begin_frame(self.cs_m)
        with open(filepath, 'rb') as f:
            bytes_left = EPD_HEIGHT * _HALF_LINE_BYTES  # 480 000
            while bytes_left > 0:
                to_read = min(len(chunk), bytes_left)
                n = f.readinto(memoryview(chunk)[:to_read])
                if not n:
                    break
                self.spi.write(memoryview(chunk)[:n])
                bytes_left -= n
        self._end_frame()

        # ── Right half (CS_S) ────────────────────────────────────────────────
        self.cs_s.value(0)
        self._cmd(0x10)
        self.dc.value(1)
        with open(filepath, 'rb') as f:
            f.seek(EPD_HEIGHT * _HALF_LINE_BYTES)  # skip left half
            while True:
                n = f.readinto(chunk)
                if not n:
                    break
                self.spi.write(chunk if n == len(chunk) else memoryview(chunk)[:n])
        self._end_frame()

        self._turn_on_display()

        # Panel controller deep-sleep
        self._both(0x07, bytes([0xA5]))  # Deep Sleep command

        # Cut panel power via TPS22916
        self._power.value(0)
