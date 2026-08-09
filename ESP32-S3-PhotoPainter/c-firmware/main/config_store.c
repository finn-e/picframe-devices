#include "config_store.h"
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include "esp_log.h"
#include "esp_spiffs.h"
#include "esp_vfs_fat.h"
#include "driver/sdmmc_host.h"
#include "sdmmc_cmd.h"
#include "cJSON.h"

static const char *TAG = "ConfigStore";

#define SPIFFS_BASE_PATH "/spiffs"
#define SD_BASE_PATH     "/sd"

#define WIFI_CONFIG_PATH "/spiffs/wifi_config.json"
#define SD_CONFIG_PATH   "/sd/config.json"

static bool spiffs_mounted = false;
static bool sd_mounted = false;

bool config_init_fs(void) {
    // 1. Mount SPIFFS
    esp_vfs_spiffs_conf_t spiffs_conf = {
        .base_path = SPIFFS_BASE_PATH,
        .partition_label = "storage",
        .max_files = 5,
        .format_if_mount_failed = true
    };
    esp_err_t ret = esp_vfs_spiffs_register(&spiffs_conf);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to mount SPIFFS (%s)", esp_err_to_name(ret));
    } else {
        spiffs_mounted = true;
        ESP_LOGI(TAG, "SPIFFS mounted successfully");
    }

    // 2. Mount SD Card via SDMMC
    ESP_LOGI(TAG, "Initializing SD card via SDMMC...");
    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    host.flags = SDMMC_HOST_FLAG_4BIT;

    sdmmc_slot_config_t slot_config = SDMMC_SLOT_CONFIG_DEFAULT();
    slot_config.width = 4;
    slot_config.clk = 39;
    slot_config.cmd = 41;
    slot_config.d0 = 40;
    slot_config.d1 = 1;
    slot_config.d2 = 2;
    slot_config.d3 = 38;

    esp_vfs_fat_sdmmc_mount_config_t mount_config = {
        .format_if_mount_failed = false,
        .max_files = 5,
        .allocation_unit_size = 16 * 1024
    };

    sdmmc_card_t *card;
    ret = esp_vfs_fat_sdmmc_mount(SD_BASE_PATH, &host, &slot_config, &mount_config, &card);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to mount SD card (%s)", esp_err_to_name(ret));
    } else {
        sd_mounted = true;
        ESP_LOGI(TAG, "SD card mounted successfully");
        sdmmc_card_print_info(stdout, card);
    }

    return spiffs_mounted;
}

static char *read_file_to_buf(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return NULL;
    struct stat st;
    if (stat(path, &st) != 0) {
        fclose(f);
        return NULL;
    }
    char *buf = malloc(st.st_size + 1);
    if (!buf) {
        fclose(f);
        return NULL;
    }
    size_t read = fread(buf, 1, st.st_size, f);
    buf[read] = '\0';
    fclose(f);
    return buf;
}

bool config_load_wifi(wifi_config_t *cfg) {
    memset(cfg, 0, sizeof(wifi_config_t));
    strcpy(cfg->server_url, "https://picframes.treee.house");

    if (!spiffs_mounted) return false;
    char *buf = read_file_to_buf(WIFI_CONFIG_PATH);
    if (!buf) {
        ESP_LOGW(TAG, "No wifi config file found, using defaults");
        return false;
    }

    cJSON *json = cJSON_Parse(buf);
    free(buf);
    if (!json) return false;

    cJSON *item = cJSON_GetObjectItem(json, "ssid");
    if (cJSON_IsString(item)) strncpy(cfg->ssid, item->valuestring, sizeof(cfg->ssid) - 1);

    item = cJSON_GetObjectItem(json, "password");
    if (cJSON_IsString(item)) strncpy(cfg->password, item->valuestring, sizeof(cfg->password) - 1);

    item = cJSON_GetObjectItem(json, "server_url");
    if (cJSON_IsString(item)) strncpy(cfg->server_url, item->valuestring, sizeof(cfg->server_url) - 1);

    item = cJSON_GetObjectItem(json, "username");
    if (cJSON_IsString(item)) strncpy(cfg->username, item->valuestring, sizeof(cfg->username) - 1);

    item = cJSON_GetObjectItem(json, "token");
    if (cJSON_IsString(item)) strncpy(cfg->token, item->valuestring, sizeof(cfg->token) - 1);

    item = cJSON_GetObjectItem(json, "landscape_flipped");
    if (cJSON_IsBool(item)) cfg->landscape_flipped = cJSON_IsTrue(item);

    item = cJSON_GetObjectItem(json, "portrait_flipped");
    if (cJSON_IsBool(item)) cfg->portrait_flipped = cJSON_IsTrue(item);

    cJSON_Delete(json);
    return true;
}

bool config_save_wifi(const wifi_config_t *cfg) {
    if (!spiffs_mounted) return false;
    cJSON *json = cJSON_CreateObject();
    if (!json) return false;

    cJSON_AddStringToObject(json, "ssid", cfg->ssid);
    cJSON_AddStringToObject(json, "password", cfg->password);
    cJSON_AddStringToObject(json, "server_url", cfg->server_url);
    cJSON_AddStringToObject(json, "username", cfg->username);
    cJSON_AddStringToObject(json, "token", cfg->token);
    cJSON_AddBoolToObject(json, "landscape_flipped", cfg->landscape_flipped);
    cJSON_AddBoolToObject(json, "portrait_flipped", cfg->portrait_flipped);

    char *str = cJSON_PrintUnformatted(json);
    cJSON_Delete(json);
    if (!str) return false;

    FILE *f = fopen(WIFI_CONFIG_PATH, "w");
    if (!f) {
        free(str);
        return false;
    }
    fputs(str, f);
    fclose(f);
    free(str);
    return true;
}

bool config_load_sd(sd_config_t *cfg) {
    memset(cfg, 0, sizeof(sd_config_t));
    strcpy(cfg->orientation, "landscape");
    cfg->sleep_interval = 900;
    cfg->image_index = 0;

    if (!sd_mounted) return false;
    char *buf = read_file_to_buf(SD_CONFIG_PATH);
    if (!buf) return false;

    cJSON *json = cJSON_Parse(buf);
    free(buf);
    if (!json) return false;

    cJSON *item = cJSON_GetObjectItem(json, "orientation");
    if (cJSON_IsString(item)) strncpy(cfg->orientation, item->valuestring, sizeof(cfg->orientation) - 1);

    item = cJSON_GetObjectItem(json, "sleep_interval");
    if (cJSON_IsNumber(item)) cfg->sleep_interval = item->valueint;

    item = cJSON_GetObjectItem(json, "image_index");
    if (cJSON_IsNumber(item)) cfg->image_index = item->valueint;

    item = cJSON_GetObjectItem(json, "daily_zip_version");
    if (cJSON_IsString(item)) strncpy(cfg->daily_zip_version, item->valuestring, sizeof(cfg->daily_zip_version) - 1);

    cJSON_Delete(json);
    return true;
}

static void json_set_string(cJSON *object, const char *name, const char *value) {
    if (cJSON_HasObjectItem(object, name)) {
        cJSON_ReplaceItemInObject(object, name, cJSON_CreateString(value));
    } else {
        cJSON_AddStringToObject(object, name, value);
    }
}

static void json_set_number(cJSON *object, const char *name, double value) {
    if (cJSON_HasObjectItem(object, name)) {
        cJSON_ReplaceItemInObject(object, name, cJSON_CreateNumber(value));
    } else {
        cJSON_AddNumberToObject(object, name, value);
    }
}

bool config_save_sd(const sd_config_t *cfg) {
    if (!sd_mounted) return false;
    cJSON *json = NULL;
    char *buf = read_file_to_buf(SD_CONFIG_PATH);
    if (buf) {
        json = cJSON_Parse(buf);
        free(buf);
    }
    if (!json) {
        json = cJSON_CreateObject();
    }

    json_set_string(json, "orientation", cfg->orientation);
    json_set_number(json, "sleep_interval", cfg->sleep_interval);
    json_set_number(json, "image_index", cfg->image_index);
    json_set_string(json, "daily_zip_version", cfg->daily_zip_version);

    char *str = cJSON_PrintUnformatted(json);
    cJSON_Delete(json);
    if (!str) return false;

    FILE *f = fopen(SD_CONFIG_PATH, "w");
    if (!f) {
        free(str);
        return false;
    }
    fputs(str, f);
    fclose(f);
    free(str);
    return true;
}
