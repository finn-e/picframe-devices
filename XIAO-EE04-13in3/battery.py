# ==========================================
# FILE VERSION: 1.2.0
# DESCRIPTION: Battery monitoring for XIAO ESP32-S3 Plus on EE04 board.
#   ADC on GPIO1 (A0); gate pin GPIO6 (A5/D5) must be HIGH before sampling.
#   No USB-connection detection is available on this board — is_usb_connected()
#   always returns False, causing go_to_sleep() to always perform a real deep
#   sleep even when USB power is present. This is the safe choice for a deployed
#   frame (never blocks deep sleep). If you need interactive testing over USB,
#   temporarily change is_usb_connected() to return True during development.
# ==========================================
import machine
import time

_ADC_PIN    = 1   # A0 — battery voltage divider output
_ENABLE_PIN = 6   # A5/D5 — must be HIGH before ADC read, LOW after

# Voltage-to-percentage mapping (li-ion linear approximation)
_V_MIN = 3.3   # 0%
_V_MAX = 4.2   # 100%

# Voltage divider scale factor from EE04 schematic (~100k / 620k divider)
_SCALE = 7.16


def get_battery_percentage():
    """
    Return battery charge as an integer 0-100, or None on error.
    Enables the ADC gate, samples GPIO1 via read_uv() (factory-calibrated),
    then disables the gate.

    Note: adc.read() + a fixed _VREF constant was previously used, but the
    ESP32-S3 ADC with ATTN_11DB has an actual usable ceiling of ~2.9V, not
    3.3V — causing all readings to be inflated and clamped to 100%.
    read_uv() uses factory eFuse calibration and avoids this entirely.
    """
    try:
        enable = machine.Pin(_ENABLE_PIN, machine.Pin.OUT)
        enable.value(1)
        time.sleep_ms(10)  # let the voltage settle

        adc = machine.ADC(machine.Pin(_ADC_PIN), atten=machine.ADC.ATTN_11DB)
        raw_uv = adc.read_uv()  # calibrated microvolts

        enable.value(0)

        voltage = raw_uv / 1_000_000 * _SCALE
        print('battery: raw_uv=%d voltage=%.3fV' % (raw_uv, voltage))
        pct = int((voltage - _V_MIN) / (_V_MAX - _V_MIN) * 100)
        return max(0, min(100, pct))
    except Exception as e:
        print('battery.get_battery_percentage error:', e)
        try:
            machine.Pin(_ENABLE_PIN, machine.Pin.OUT).value(0)
        except Exception:
            pass
        return None


def is_usb_connected():
    """
    Always returns False — the EE04 board has no USB-presence sense pin.
    As a result, go_to_sleep() will always perform a true deep sleep regardless
    of whether USB power is attached. See module docstring for details.
    """
    return False
