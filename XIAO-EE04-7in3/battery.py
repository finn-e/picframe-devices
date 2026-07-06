# ==========================================
# FILE VERSION: 1.1.0
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

# Scale factor from schematic voltage divider (matches wiki formula)
_SCALE  = 7.16
_VREF   = 3.3
_ADC_FS = 4096  # 12-bit ADC


def get_battery_percentage():
    """
    Return battery charge as an integer 0-100, or None on error.
    Enables the ADC gate, samples GPIO1, then disables the gate.
    """
    try:
        enable = machine.Pin(_ENABLE_PIN, machine.Pin.OUT)
        enable.value(1)
        time.sleep_ms(10)  # let the voltage settle

        adc = machine.ADC(machine.Pin(_ADC_PIN), atten=machine.ADC.ATTN_11DB)
        raw = adc.read()

        enable.value(0)

        voltage = (raw / _ADC_FS) * _VREF * _SCALE
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
