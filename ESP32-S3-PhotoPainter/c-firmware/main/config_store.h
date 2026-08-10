#ifndef CONFIG_STORE_H
#define CONFIG_STORE_H

#include <stdbool.h>

#define MAX_SSID_LEN      64
#define MAX_PASS_LEN      64
#define MAX_URL_LEN       128
#define MAX_USER_LEN      64
#define MAX_TOKEN_LEN     128
#define MAX_ORIENT_LEN    32
#define MAX_ZIP_VER_LEN   64

typedef struct {
    char ssid[MAX_SSID_LEN];
    char password[MAX_PASS_LEN];
    char server_url[MAX_URL_LEN];
    char username[MAX_USER_LEN];
    char token[MAX_TOKEN_LEN];
    bool landscape_flipped;
    bool portrait_flipped;
} app_wifi_config_t;

typedef struct {
    char orientation[MAX_ORIENT_LEN];
    int sleep_interval;
    int image_index;
    char daily_zip_version[MAX_ZIP_VER_LEN];
    // We can parse or update the JSON directly when calling API configs
} sd_config_t;

bool config_init_fs(void); // Mount SPIFFS and SD card
bool config_load_wifi(app_wifi_config_t *cfg);
bool config_save_wifi(const app_wifi_config_t *cfg);
bool config_load_sd(sd_config_t *cfg);
bool config_save_sd(const sd_config_t *cfg);

#endif // CONFIG_STORE_H
