#include "axp2101.h"
#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "AXP2101";

#define I2C_MASTER_NUM             I2C_NUM_0
#define I2C_MASTER_FREQ_HZ         100000
#define I2C_MASTER_TX_BUF_DISABLE  0
#define I2C_MASTER_RX_BUF_DISABLE  0
#define ACK_CHECK_EN               true

static bool i2c_initialized = false;

static esp_err_t axp_read_reg(uint8_t reg, uint8_t *val) {
    return i2c_master_write_read_device(I2C_MASTER_NUM, AXP2101_I2C_ADDR, &reg, 1, val, 1, pdMS_TO_TICKS(100));
}

static esp_err_t axp_write_reg(uint8_t reg, uint8_t val) {
    uint8_t write_buf[2] = {reg, val};
    return i2c_master_write_to_device(I2C_MASTER_NUM, AXP2101_I2C_ADDR, write_buf, 2, pdMS_TO_TICKS(100));
}

static void axp_set_bit(uint8_t reg, uint8_t bit) {
    uint8_t val = 0;
    if (axp_read_reg(reg, &val) == ESP_OK) {
        axp_write_reg(reg, val | (1 << bit));
    }
}

static void axp_clr_bit(uint8_t reg, uint8_t bit) {
    uint8_t val = 0;
    if (axp_read_reg(reg, &val) == ESP_OK) {
        axp_write_reg(reg, val & ~(1 << bit));
    }
}

bool axp2101_init(void) {
    if (!i2c_initialized) {
        i2c_config_t conf = {
            .mode = I2C_MODE_MASTER,
            .sda_io_num = AXP2101_SDA_PIN,
            .scl_io_num = AXP2101_SCL_PIN,
            .sda_pullup_en = GPIO_PULLUP_ENABLE,
            .scl_pullup_en = GPIO_PULLUP_ENABLE,
            .master.clk_speed = I2C_MASTER_FREQ_HZ,
        };
        esp_err_t err = i2c_param_config(I2C_MASTER_NUM, &conf);
        if (err != ESP_OK) return false;
        err = i2c_driver_install(I2C_MASTER_NUM, conf.mode, I2C_MASTER_TX_BUF_DISABLE, I2C_MASTER_RX_BUF_DISABLE, 0);
        if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return false; // ESP_ERR_INVALID_STATE means already installed
        i2c_initialized = true;
    }

    // Set VBUS input current limit to 2.0A (Reg 0x16: read & 0xF8 | 0x05)
    uint8_t val = 0;
    if (axp_read_reg(0x16, &val) == ESP_OK) {
        axp_write_reg(0x16, (val & 0xF8) | 0x05);
        ESP_LOGI(TAG, "VBUS limit set to 2.0A");
    }

    // Set DCDC1 to 3.3V & Enable (Reg 0x82: 0x12, Reg 0x80: set bit 0)
    axp_write_reg(0x82, 0x12);
    axp_set_bit(0x80, 0);

    // Set ALDO3 to 3.3V & Enable (Reg 0x94: read & 0xE0 | 0x1C, Reg 0x90: set bit 2)
    if (axp_read_reg(0x94, &val) == ESP_OK) {
        axp_write_reg(0x94, (val & 0xE0) | 0x1C);
    }
    axp_set_bit(0x90, 2); // EPD_VCC

    // Set ALDO4 to 3.3V & Enable (Reg 0x95: read & 0xE0 | 0x1C, Reg 0x90: set bit 3)
    if (axp_read_reg(0x95, &val) == ESP_OK) {
        axp_write_reg(0x95, (val & 0xE0) | 0x1C);
    }
    axp_set_bit(0x90, 3);

    // Enable ALDO2 (Audio VCC)
    axp_set_bit(0x90, 1);

    ESP_LOGI(TAG, "AXP2101 PMIC Initialized");
    return true;
}

void axp2101_disable_power(void) {
    if (!i2c_initialized) return;
    // Disable ALDO2, ALDO3, ALDO4 to conserve energy
    uint8_t val = 0;
    if (axp_read_reg(0x90, &val) == ESP_OK) {
        axp_write_reg(0x90, val & ~0x0E);
    }
}

bool axp2101_is_usb_connected(void) {
    if (!i2c_initialized) return true;
    uint8_t val = 0;
    if (axp_read_reg(0x00, &val) == ESP_OK) {
        return (val & 0x20) != 0 || (val & 0x10) != 0;
    }
    return true;
}

bool axp2101_is_battery_connected(void) {
    if (!i2c_initialized) return false;
    uint8_t val = 0;
    if (axp_read_reg(0x00, &val) == ESP_OK) {
        return (val & 0x08) != 0;
    }
    return false;
}

int axp2101_get_battery_percentage(void) {
    if (!i2c_initialized) return 0;
    if (!axp2101_is_battery_connected()) {
        return axp2101_is_usb_connected() ? 100 : 0;
    }
    uint8_t val = 0;
    if (axp_read_reg(0xA4, &val) == ESP_OK) {
        if (val > 100) {
            return axp2101_is_usb_connected() ? 100 : 0;
        }
        return val;
    }
    return 0;
}

void axp2101_power_off(void) {
    if (!i2c_initialized) return;
    axp_write_reg(0x10, 0x01);
}

void axp2101_reboot(void) {
    if (!i2c_initialized) return;
    axp_write_reg(0x10, 0x02);
}
