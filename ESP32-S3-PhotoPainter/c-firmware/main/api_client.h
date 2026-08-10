#ifndef API_CLIENT_H
#define API_CLIENT_H

#include <stdbool.h>
#include <stddef.h>

typedef struct {
    int image_index;
    char orientation[32];
    int sleep_interval;
} refresh_result_t;

typedef struct {
    bool landscape_flipped;
    bool portrait_flipped;
    bool debug;
    char daily_zip_version[64];
} daily_config_result_t;

void api_client_init(const char *server_url, const char *mac, const char *token);
void api_client_cleanup(void);

// Register device. Returns new token if success.
bool api_register(const char *username, const char *password, const char *hw_profile, const char *resolution, char *token_out, size_t token_len);

// Check updates. Returns firmware ZIP URL if available, else false.
bool api_check_update(const char *hw_profile, const char *current_ver, char *url_out, size_t url_len);

// Get daily configuration.
bool api_get_daily_config(daily_config_result_t *result, const char *fw_version);

// Download daily ZIP file to local path.
bool api_download_daily_zip(const char *version, const char *dest_path);

// Refresh state.
bool api_refresh(bool skip, int battery, refresh_result_t *result);

// Change orientation.
bool api_change_orientation(const char *orientation);

// Sync NTP.
bool api_sync_ntp(void);

#endif // API_CLIENT_H
