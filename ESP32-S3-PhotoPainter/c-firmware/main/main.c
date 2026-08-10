#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "esp_ota_ops.h"
#include "esp_http_client.h"
#include "esp_https_ota.h"
#include "nvs_flash.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "axp2101.h"
#include "config_store.h"
#include "wifi_manager.h"
#include "api_client.h"
#include "epd_7in3f.h"
#include "display_overlay.h"
#include "unzip.h"
#include "cJSON.h"

static const char *TAG = "Main";

#define BOOT_BUTTON_PIN   0
#define KEY_BUTTON_PIN    4
#define PWR_BUTTON_PIN    5

#define FIRMWARE_VERSION  "1.8.0-c"

static app_wifi_config_t wifi_cfg;
static sd_config_t sd_cfg;
static bool wifi_ok = false;
static char mac_str[32] = {0};
static char fail_reason[128] = {0};

static bool check_button(gpio_num_t pin) {
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << pin),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&io_conf);
    vTaskDelay(pdMS_TO_TICKS(50));
    return gpio_get_level(pin) == 0;
}

// OTA Update handler
static bool perform_ota_update(const char *url) {
    ESP_LOGI(TAG, "Starting OTA update from: %s", url);
    esp_http_client_config_t config = {
        .url = url,
        .transport_type = HTTP_TRANSPORT_OVER_SSL,
        .skip_cert_common_name_check = true,
        .timeout_ms = 30000,
        .keep_alive_enable = true,
    };
    
    esp_https_ota_config_t ota_config = {
        .http_config = &config,
    };

    esp_err_t ret = esp_https_ota(&ota_config);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "OTA Update Succeeded, rebooting...");
        vTaskDelay(pdMS_TO_TICKS(500));
        esp_restart();
        return true;
    } else {
        ESP_LOGE(TAG, "OTA Update Failed (%s)", esp_err_to_name(ret));
        return false;
    }
}

static void go_to_sleep(int seconds) {
    if (sd_cfg.sleep_interval <= 0) sd_cfg.sleep_interval = 900;
    
    ESP_LOGI(TAG, "Preparing for sleep of %d seconds", seconds);
    api_client_cleanup();
    wifi_stop();

    if (axp2101_is_usb_connected()) {
        ESP_LOGI(TAG, "USB connected — simulating sleep via delay");
        vTaskDelay(pdMS_TO_TICKS(seconds * 1000));
        esp_restart();
        return;
    }

    axp2101_disable_power();

    // Enable button wakeups:
    // BOOT (GPIO0) -> ext0 (active low)
    esp_sleep_enable_ext0_wakeup(BOOT_BUTTON_PIN, 0);
    // KEY (GPIO4) -> ext1 (active low)
    esp_sleep_enable_ext1_wakeup(1ULL << KEY_BUTTON_PIN, ESP_EXT1_WAKEUP_ANY_LOW);

    esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
    ESP_LOGI(TAG, "Entering deep sleep now");
    esp_deep_sleep_start();
}

static void draw_message_screen(const char **lines, int count, const char *orientation) {
    uint8_t *buf = malloc(EPD_BUF_SIZE);
    if (!buf) return;
    
    // Load logo or clear with default background
    char logo_path[64];
    snprintf(logo_path, sizeof(logo_path), "/sd/picframes_logo_%c.bin", (strstr(orientation, "landscape") != NULL) ? 'l' : 'p');
    FILE *lf = fopen(logo_path, "rb");
    if (lf) {
        fread(buf, 1, EPD_BUF_SIZE, lf);
        fclose(lf);
    } else {
        memset(buf, 0x11, EPD_BUF_SIZE); // White fallback
    }

    // Paint lines onto the buffer
    
    if (strstr(orientation, "portrait") != NULL) {
        for (int i = 0; i < count; i++) {
            // Draw visual portrait text
            display_overlay_caption(buf, logo_path, "details", lines[i], true, 100);
        }
    } else {
        for (int i = 0; i < count; i++) {
            display_overlay_caption(buf, logo_path, "details", lines[i], false, 100);
        }
    }

    display_overlay_battery_square(buf, axp2101_get_battery_percentage());
    
    const char *out_path = "/sd/msg_screen.bin";
    FILE *f = fopen(out_path, "wb");
    if (f) {
        fwrite(buf, 1, EPD_BUF_SIZE, f);
        fclose(f);
        epd_display_file(out_path, orientation);
        unlink(out_path);
    }
    free(buf);
}

static void run_offline_fallback(void) {
    ESP_LOGI(TAG, "Entering offline fallback mode...");
    // Read playlist / images
    char img_path[128] = {0};
    
    // Check if we have config
    cJSON *sd_json = NULL;
    FILE *f = fopen("/sd/config.json", "r");
    if (f) {
        struct stat st;
        if (fstat(fileno(f), &st) == 0) {
            char *buf = malloc(st.st_size + 1);
            if (buf) {
                fread(buf, 1, st.st_size, f);
                buf[st.st_size] = '\0';
                sd_json = cJSON_Parse(buf);
                free(buf);
            }
        }
        fclose(f);
    }

    if (sd_json) {
        cJSON *imgs = cJSON_GetObjectItem(sd_json, "images");
        if (cJSON_IsArray(imgs) && cJSON_GetArraySize(imgs) > 0) {
            cJSON *img = cJSON_GetArrayItem(imgs, sd_cfg.image_index % cJSON_GetArraySize(imgs));
            if (cJSON_IsString(img)) {
                snprintf(img_path, sizeof(img_path), "/sd/%s_%c.bin", img->valuestring,
                         (strstr(sd_cfg.orientation, "landscape") != NULL) ? 'l' : 'p');
            }
        }
        cJSON_Delete(sd_json);
    }

    struct stat st;
    if (strlen(img_path) > 0 && stat(img_path, &st) == 0) {
        ESP_LOGI(TAG, "Offline image found: %s", img_path);
        // Load image and render
        uint8_t *buf = malloc(EPD_BUF_SIZE);
        FILE *img_f = fopen(img_path, "rb");
        if (buf && img_f) {
            fread(buf, 1, EPD_BUF_SIZE, img_f);
            fclose(img_f);
            
            // Draw battery & captions overlays
            display_overlay_battery_square(buf, axp2101_get_battery_percentage());
            if (strlen(fail_reason) > 0) {
                display_overlay_status(buf, fail_reason);
            }
            
            const char *out_path = "/sd/render_out.bin";
            FILE *out_f = fopen(out_path, "wb");
            if (out_f) {
                fwrite(buf, 1, EPD_BUF_SIZE, out_f);
                fclose(out_f);
                epd_display_file(out_path, sd_cfg.orientation);
                unlink(out_path);
            }
            free(buf);
            go_to_sleep(sd_cfg.sleep_interval);
            return;
        }
        if (buf) free(buf);
    }

    ESP_LOGW(TAG, "No offline cached image to render");
    if (!wifi_ok) {
        char ap_name[64];
        snprintf(ap_name, sizeof(ap_name), "PicFrame-%s", mac_str);
        const char *lines[] = {
            "WIFI CONNECTION FAILED",
            wifi_cfg.ssid,
            "",
            "TO RECONFIGURE CONNECT TO:",
            ap_name,
            "THEN VISIT: picframe.setup"
        };
        draw_message_screen(lines, 6, sd_cfg.orientation);
        wifi_start_ap_and_portal("wifi_failed");
        while (1) vTaskDelay(pdMS_TO_TICKS(1000)); // Sleep blocked in Portal Mode
    } else {
        const char *lines[] = {
            "NO IMAGES CACHED",
            "",
            "TO ADD PICS VISIT:",
            wifi_cfg.server_url
        };
        draw_message_screen(lines, 4, sd_cfg.orientation);
        go_to_sleep(sd_cfg.sleep_interval);
    }
}

static void run_connected_sequence(void) {
    ESP_LOGI(TAG, "Starting connected sequence...");
    api_client_init(wifi_cfg.server_url, mac_str, wifi_cfg.token);

    // 1. Sync NTP
    api_sync_ntp();

    // 2. Check update
    char update_url[256] = {0};
    if (api_check_update("Waveshare-PhotoPainter-7in3", FIRMWARE_VERSION, update_url, sizeof(update_url))) {
        ESP_LOGI(TAG, "Update available: %s. Applying...", update_url);
        perform_ota_update(update_url);
    }

    // 3. Get daily-config
    daily_config_result_t dcfg = {0};
    if (api_get_daily_config(&dcfg, FIRMWARE_VERSION)) {
        wifi_cfg.landscape_flipped = dcfg.landscape_flipped;
        wifi_cfg.portrait_flipped = dcfg.portrait_flipped;
        config_save_wifi(&wifi_cfg);
        
        // 4. Download zip if changed
        if (strcmp(dcfg.daily_zip_version, sd_cfg.daily_zip_version) != 0) {
            ESP_LOGI(TAG, "New zip version available: %s", dcfg.daily_zip_version);
            if (api_download_daily_zip(dcfg.daily_zip_version, "/sd/daily.zip")) {
                // Wipe old sd images
                // Extract zip
                unzip_file("/sd/daily.zip", "/sd");
                unlink("/sd/daily.zip");
                strcpy(sd_cfg.daily_zip_version, dcfg.daily_zip_version);
                config_save_sd(&sd_cfg);
            }
        }
    } else {
        strcpy(fail_reason, "DAILY CONFIG FAILED");
        run_offline_fallback();
        return;
    }

    // 5. Refresh
    refresh_result_t ref = {0};
    if (api_refresh(false, axp2101_get_battery_percentage(), &ref)) {
        sd_cfg.image_index = ref.image_index;
        strncpy(sd_cfg.orientation, ref.orientation, sizeof(sd_cfg.orientation) - 1);
        sd_cfg.sleep_interval = ref.sleep_interval;
        config_save_sd(&sd_cfg);
    } else {
        strcpy(fail_reason, "REFRESH FAILED");
        run_offline_fallback();
        return;
    }

    // 6. Draw current image
    run_offline_fallback();
}

void app_main(void) {
    // Initialize NVS
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // Initialize PMIC
    axp2101_init();

    // Mount FS
    config_init_fs();

    // Load configs
    config_load_wifi(&wifi_cfg);
    config_load_sd(&sd_cfg);

    wifi_init();
    wifi_get_mac_str(mac_str);

    // Check wake reason
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    ESP_LOGI(TAG, "Wakeup cause: %d", cause);

    // If cold boot, check BOOT pin for portal request
    bool force_portal = false;
    if (cause == ESP_SLEEP_WAKEUP_UNDEFINED) {
        if (check_button(BOOT_BUTTON_PIN)) {
            ESP_LOGI(TAG, "BOOT button held at startup. Force portal mode.");
            force_portal = true;
        }
    }

    if (force_portal || strlen(wifi_cfg.ssid) == 0) {
        const char *lines[] = {
            "PICFRAME ONBOARDING",
            "CONNECT TO WI-FI AP:",
            "PicFrame-<MAC>",
            "THEN VISIT: picframe.setup"
        };
        draw_message_screen(lines, 4, sd_cfg.orientation);
        wifi_start_ap_and_portal("setup");
        while (1) vTaskDelay(pdMS_TO_TICKS(1000));
    }

    // Try WiFi STA Connect
    wifi_ok = wifi_connect_sta(wifi_cfg.ssid, wifi_cfg.password, 15);
    if (wifi_ok) {
        // Run connected pipeline
        run_connected_sequence();
    } else {
        strcpy(fail_reason, "WIFI CONNECTION TIMEOUT");
        run_offline_fallback();
    }
}
