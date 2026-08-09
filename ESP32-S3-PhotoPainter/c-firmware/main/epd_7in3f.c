#include "epd_7in3f.h"
#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "EPD_7in3f";

static spi_device_handle_t spi_handle = NULL;
static bool epd_has_timeout = false;

static void epd_delay_ms(uint32_t ms) {
    vTaskDelay(pdMS_TO_TICKS(ms));
}

static void epd_write_command(uint8_t cmd) {
    gpio_set_level(EPD_DC_PIN, 0);
    gpio_set_level(EPD_CS_PIN, 0);
    spi_transaction_t t = {
        .length = 8,
        .tx_buffer = &cmd,
    };
    spi_device_polling_transmit(spi_handle, &t);
    gpio_set_level(EPD_CS_PIN, 1);
}

static void epd_write_data(const uint8_t *data, size_t len) {
    gpio_set_level(EPD_DC_PIN, 1);
    gpio_set_level(EPD_CS_PIN, 0);
    spi_transaction_t t = {
        .length = len * 8,
        .tx_buffer = data,
    };
    spi_device_polling_transmit(spi_handle, &t);
    gpio_set_level(EPD_CS_PIN, 1);
}

static void epd_write_data_byte(uint8_t val) {
    epd_write_data(&val, 1);
}

static void epd_reset(void) {
    gpio_set_level(EPD_RST_PIN, 1);
    epd_delay_ms(50);
    gpio_set_level(EPD_RST_PIN, 0);
    epd_delay_ms(20);
    gpio_set_level(EPD_RST_PIN, 1);
    epd_delay_ms(50);
}

static void epd_wait_busy(uint32_t timeout_ms) {
    if (epd_has_timeout) return;
    
    epd_delay_ms(200);
    uint32_t elapsed = 0;
    while (gpio_get_level(EPD_BUSY_PIN) == 0) {
        epd_delay_ms(10);
        elapsed += 10;
        if (elapsed > timeout_ms) {
            ESP_LOGE(TAG, "EPD busy timeout (%d s)!", timeout_ms / 1000);
            epd_has_timeout = true;
            break;
        }
    }
}

bool epd_init(void) {
    epd_has_timeout = false;

    // 1. Enable power via TPS22916 load-switch
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << EPD_POWER_PIN),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    gpio_config(&io_conf);
    gpio_set_level(EPD_POWER_PIN, 1);
    epd_delay_ms(50);

    // 2. Configure other control GPIOs
    io_conf.pin_bit_mask = (1ULL << EPD_DC_PIN) | (1ULL << EPD_CS_PIN) | (1ULL << EPD_RST_PIN);
    gpio_config(&io_conf);
    
    io_conf.pin_bit_mask = (1ULL << EPD_BUSY_PIN);
    io_conf.mode = GPIO_MODE_INPUT;
    io_conf.pull_up_en = GPIO_PULLUP_ENABLE;
    gpio_config(&io_conf);

    gpio_set_level(EPD_CS_PIN, 1);
    gpio_set_level(EPD_DC_PIN, 0);
    gpio_set_level(EPD_RST_PIN, 1);

    // 3. Configure SPI host
    if (!spi_handle) {
        spi_bus_config_t buscfg = {
            .miso_io_num = -1,
            .mosi_io_num = EPD_MOSI_PIN,
            .sclk_io_num = EPD_SCK_PIN,
            .quadwp_io_num = -1,
            .quadhd_io_num = -1,
            .max_transfer_sz = EPD_BUF_SIZE
        };
        spi_device_interface_config_t devcfg = {
            .clock_speed_hz = 10 * 1000 * 1000,
            .mode = 0,
            .spics_io_num = -1, // We control CS manually
            .queue_size = 7,
        };
        esp_err_t ret = spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_CH_AUTO);
        if (ret != ESP_OK) return false;
        ret = spi_bus_add_device(SPI2_HOST, &devcfg, &spi_handle);
        if (ret != ESP_OK) return false;
    }

    // 4. Initialisation Sequence
    epd_reset();
    epd_wait_busy(3000);
    epd_delay_ms(50);

    epd_write_command(0xAA); // CMDH
    const uint8_t cmdh_data[] = {0x49, 0x55, 0x20, 0x08, 0x09, 0x18};
    epd_write_data(cmdh_data, sizeof(cmdh_data));

    epd_write_command(0x01);
    epd_write_data_byte(0x3F);

    epd_write_command(0x00);
    const uint8_t psr_data[] = {0x5F, 0x69};
    epd_write_data(psr_data, sizeof(psr_data));

    epd_write_command(0x03);
    const uint8_t pwr_data[] = {0x00, 0x54, 0x00, 0x44};
    epd_write_data(pwr_data, sizeof(pwr_data));

    epd_write_command(0x05);
    const uint8_t booster_data[] = {0x40, 0x1F, 0x1F, 0x2C};
    epd_write_data(booster_data, sizeof(booster_data));

    epd_write_command(0x06);
    const uint8_t booster_data2[] = {0x6F, 0x1F, 0x17, 0x49};
    epd_write_data(booster_data2, sizeof(booster_data2));

    epd_write_command(0x08);
    const uint8_t booster_data3[] = {0x6F, 0x1F, 0x1F, 0x22};
    epd_write_data(booster_data3, sizeof(booster_data3));

    epd_write_command(0x30);
    epd_write_data_byte(0x03);

    epd_write_command(0x50);
    epd_write_data_byte(0x3F);

    epd_write_command(0x60);
    const uint8_t tcon_data[] = {0x02, 0x00};
    epd_write_data(tcon_data, sizeof(tcon_data));

    epd_write_command(0x61);
    const uint8_t tres_data[] = {0x03, 0x20, 0x01, 0xE0}; // 800 x 480
    epd_write_data(tres_data, sizeof(tres_data));

    epd_write_command(0x84);
    epd_write_data_byte(0x01);

    epd_write_command(0xE3);
    epd_write_data_byte(0x2F);

    epd_write_command(0x04); // PWR_ON
    epd_wait_busy(3000);

    return true;
}

static void epd_turn_on_display(void) {
    epd_write_command(0x04); // POWER_ON
    epd_wait_busy(3000);

    epd_write_command(0x06);
    const uint8_t booster_data[] = {0x6F, 0x1F, 0x17, 0x49};
    epd_write_data(booster_data, sizeof(booster_data));

    epd_write_command(0x12); // DISPLAY_REFRESH
    epd_write_data_byte(0x00);
    epd_wait_busy(30000);

    epd_write_command(0x02); // POWER_OFF
    epd_write_data_byte(0x00);
    epd_wait_busy(3000);
}

void epd_display_file(const char *filepath, const char *orientation) {
    epd_init();
    epd_write_command(0x10); // Write RAM

    gpio_set_level(EPD_DC_PIN, 1);
    gpio_set_level(EPD_CS_PIN, 0);

    bool rotate_180 = (strstr(orientation, "upside-down") == NULL);

    FILE *f = fopen(filepath, "rb");
    if (!f) {
        ESP_LOGE(TAG, "Failed to open file for render: %s", filepath);
        gpio_set_level(EPD_CS_PIN, 1);
        return;
    }

    if (rotate_180) {
        // Fast 180 degree rotation and chunk streaming
        const size_t chunk_size = 4000;
        const size_t num_chunks = 48;
        uint8_t *chunk = malloc(chunk_size);
        if (chunk) {
            for (int chunk_idx = (int)num_chunks - 1; chunk_idx >= 0; chunk_idx--) {
                fseek(f, chunk_idx * chunk_size, SEEK_SET);
                fread(chunk, 1, chunk_size, f);
                
                // Swap bytes and low/high nibbles in place
                for (size_t j = 0; j < chunk_size / 2; j++) {
                    uint8_t b1 = chunk[j];
                    uint8_t b2 = chunk[chunk_size - 1 - j];
                    chunk[j] = ((b2 & 0x0F) << 4) | (b2 >> 4);
                    chunk[chunk_size - 1 - j] = ((b1 & 0x0F) << 4) | (b1 >> 4);
                }
                
                spi_transaction_t t = {
                    .length = chunk_size * 8,
                    .tx_buffer = chunk,
                };
                spi_device_polling_transmit(spi_handle, &t);
            }
            free(chunk);
        }
    } else {
        // Direct stream without rotation
        uint8_t *chunk = malloc(4096);
        if (chunk) {
            size_t n;
            while ((n = fread(chunk, 1, 4096, f)) > 0) {
                spi_transaction_t t = {
                    .length = n * 8,
                    .tx_buffer = chunk,
                };
                spi_device_polling_transmit(spi_handle, &t);
            }
            free(chunk);
        }
    }

    fclose(f);
    gpio_set_level(EPD_CS_PIN, 1);

    epd_turn_on_display();

    // Deep Sleep EPD controller
    epd_write_command(0x07); // Deep Sleep
    epd_write_data_byte(0xA5);

    // Cut power completely
    epd_power_off();
}

void epd_power_off(void) {
    gpio_set_level(EPD_POWER_PIN, 0);
}
