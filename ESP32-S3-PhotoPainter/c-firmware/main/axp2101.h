#ifndef AXP2101_H
#define AXP2101_H

#include <stdbool.h>

#define AXP2101_I2C_ADDR 0x34
#define AXP2101_SDA_PIN  47
#define AXP2101_SCL_PIN  48

bool axp2101_init(void);
void axp2101_disable_power(void);
bool axp2101_is_usb_connected(void);
bool axp2101_is_battery_connected(void);
int axp2101_get_battery_percentage(void);
void axp2101_power_off(void);
void axp2101_reboot(void);

#endif // AXP2101_H
