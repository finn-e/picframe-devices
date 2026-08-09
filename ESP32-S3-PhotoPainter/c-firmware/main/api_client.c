#include "api_client.h"
#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "esp_http_client.h"
#include "esp_sntp.h"
#include "cJSON.h"

static const char *TAG = "ApiClient";

static char server_base_url[128] = {0};
static char device_mac[32] = {0};
static char device_token[128] = {0};

static esp_http_client_handle_t client_handle = NULL;

void api_client_init(const char *server_url, const char *mac, const char *token) {
    strncpy(server_base_url, server_url, sizeof(server_base_url) - 1);
    // Strip trailing slash if present
    size_t len = strlen(server_base_url);
    if (len > 0 && server_base_url[len - 1] == '/') {
        server_base_url[len - 1] = '\0';
    }
    strncpy(device_mac, mac, sizeof(device_mac) - 1);
    strncpy(device_token, token, sizeof(device_token) - 1);
}

void api_client_cleanup(void) {
    if (client_handle) {
        esp_http_client_cleanup(client_handle);
        client_handle = NULL;
    }
}

static esp_err_t _http_event_handler(esp_http_client_event_t *evt) {
    switch (evt->event_id) {
        case HTTP_EVENT_ERROR:
            ESP_LOGD(TAG, "HTTP_EVENT_ERROR");
            break;
        case HTTP_EVENT_ON_CONNECTED:
            ESP_LOGD(TAG, "HTTP_EVENT_ON_CONNECTED");
            break;
        case HTTP_EVENT_HEADER_SENT:
            ESP_LOGD(TAG, "HTTP_EVENT_HEADER_SENT");
            break;
        case HTTP_EVENT_ON_HEADER:
            ESP_LOGD(TAG, "HTTP_EVENT_ON_HEADER, key=%s, value=%s", evt->header_key, evt->header_value);
            break;
        case HTTP_EVENT_ON_DATA:
            ESP_LOGD(TAG, "HTTP_EVENT_ON_DATA, len=%d", evt->data_len);
            if (evt->user_ctx) {
                // If user_ctx is passed, append data to it
                char *buf = (char *)evt->user_ctx;
                size_t current_len = strlen(buf);
                if (current_len + evt->data_len < 8192) {
                    memcpy(buf + current_len, evt->data, evt->data_len);
                    buf[current_len + evt->data_len] = '\0';
                }
            }
            break;
        case HTTP_EVENT_ON_FINISH:
            ESP_LOGD(TAG, "HTTP_EVENT_ON_FINISH");
            break;
        case HTTP_EVENT_DISCONNECTED:
            ESP_LOGD(TAG, "HTTP_EVENT_DISCONNECTED");
            break;
        case HTTP_EVENT_REDIRECT:
            ESP_LOGD(TAG, "HTTP_EVENT_REDIRECT");
            break;
    }
    return ESP_OK;
}

// Internal request dispatcher (Keep-Alive reused)
static bool perform_request(esp_http_client_method_t method, const char *path, const char *post_data, char *response_buf, int response_buf_size, int *status_code_out, const char *fw_version) {
    char url[256];
    snprintf(url, sizeof(url), "%s%s", server_base_url, path);

    esp_http_client_config_t config = {
        .url = url,
        .method = method,
        .event_handler = _http_event_handler,
        .user_ctx = response_buf,
        .keep_alive_enable = true,
        .timeout_ms = 10000,
        .transport_type = HTTP_TRANSPORT_OVER_SSL,
        .skip_cert_common_name_check = true, // Skip certificate validation for self-signed development/local servers
    };

    if (response_buf) {
        response_buf[0] = '\0';
    }

    if (!client_handle) {
        client_handle = esp_http_client_init(&config);
    } else {
        esp_http_client_set_url(client_handle, url);
        esp_http_client_set_method(client_handle, method);
        esp_http_client_set_user_data(client_handle, response_buf);
    }

    if (!client_handle) {
        ESP_LOGE(TAG, "Failed to initialize HTTP client");
        return false;
    }

    esp_http_client_set_header(client_handle, "Content-Type", "application/json");
    esp_http_client_set_header(client_handle, "X-Device-Mac", device_mac);
    esp_http_client_set_header(client_handle, "X-Device-Token", device_token);
    if (fw_version) {
        esp_http_client_set_header(client_handle, "X-Firmware-Version", fw_version);
    }

    if (post_data && method == HTTP_METHOD_POST) {
        esp_http_client_set_post_field(client_handle, post_data, strlen(post_data));
    } else {
        esp_http_client_set_post_field(client_handle, NULL, 0);
    }

    esp_err_t err = esp_http_client_perform(client_handle);
    if (err == ESP_OK) {
        int code = esp_http_client_get_status_code(client_handle);
        if (status_code_out) *status_code_out = code;
        ESP_LOGI(TAG, "HTTP %s to %s returned %d", (method == HTTP_METHOD_POST) ? "POST" : "GET", path, code);
        return true;
    } else {
        ESP_LOGE(TAG, "HTTP perform failed: %s", esp_err_to_name(err));
        return false;
    }
}

bool api_register(const char *username, const char *password, const char *hw_profile, const char *resolution, char *token_out, size_t token_len) {
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "mac", device_mac);
    cJSON_AddStringToObject(root, "username", username);
    cJSON_AddStringToObject(root, "password", password);
    cJSON_AddStringToObject(root, "hw_profile", hw_profile);
    cJSON_AddStringToObject(root, "resolution", resolution);
    char *post_data = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    char resp[1024];
    int status = 0;
    bool success = perform_request(HTTP_METHOD_POST, "/api/register", post_data, resp, sizeof(resp), &status, NULL);
    free(post_data);

    if (success && status == 200) {
        cJSON *json = cJSON_Parse(resp);
        if (json) {
            cJSON *token = cJSON_GetObjectItem(json, "token");
            if (cJSON_IsString(token)) {
                strncpy(token_out, token->valuestring, token_len - 1);
                token_out[token_len - 1] = '\0';
                cJSON_Delete(json);
                return true;
            }
            cJSON_Delete(json);
        }
    }
    return false;
}

bool api_check_update(const char *hw_profile, const char *current_ver, char *url_out, size_t url_len) {
    char path[256];
    snprintf(path, sizeof(path), "/api/update?hw=%s&version=%s", hw_profile, current_ver);

    char resp[1024];
    int status = 0;
    bool success = perform_request(HTTP_METHOD_GET, path, NULL, resp, sizeof(resp), &status, current_ver);

    if (success && status == 200 && strlen(resp) > 0) {
        // Strip spaces/newlines
        char *ptr = resp;
        while (*ptr == ' ' || *ptr == '\n' || *ptr == '\r') ptr++;
        size_t len = strlen(ptr);
        while (len > 0 && (ptr[len - 1] == ' ' || ptr[len - 1] == '\n' || ptr[len - 1] == '\r')) {
            ptr[len - 1] = '\0';
            len--;
        }
        if (len > 0) {
            strncpy(url_out, ptr, url_len - 1);
            url_out[url_len - 1] = '\0';
            return true;
        }
    }
    return false;
}

bool api_get_daily_config(daily_config_result_t *result, const char *fw_version) {
    char resp[4096];
    int status = 0;
    bool success = perform_request(HTTP_METHOD_GET, "/api/daily-config", NULL, resp, sizeof(resp), &status, fw_version);

    if (success && status == 200) {
        cJSON *json = cJSON_Parse(resp);
        if (json) {
            cJSON *lf = cJSON_GetObjectItem(json, "landscape_flipped");
            if (cJSON_IsBool(lf)) result->landscape_flipped = cJSON_IsTrue(lf);

            cJSON *pf = cJSON_GetObjectItem(json, "portrait_flipped");
            if (cJSON_IsBool(pf)) result->portrait_flipped = cJSON_IsTrue(pf);

            cJSON *dbg = cJSON_GetObjectItem(json, "debug");
            if (cJSON_IsBool(dbg)) result->debug = cJSON_IsTrue(dbg);

            cJSON *ver = cJSON_GetObjectItem(json, "daily_zip_version");
            if (cJSON_IsString(ver)) strncpy(result->daily_zip_version, ver->valuestring, sizeof(result->daily_zip_version) - 1);

            cJSON_Delete(json);
            return true;
        }
    }
    return false;
}

bool api_download_daily_zip(const char *version, const char *dest_path) {
    char path[256];
    snprintf(path, sizeof(path), "/api/daily-zip?version=%s", version ? version : "0");
    char url[512];
    snprintf(url, sizeof(url), "%s%s", server_base_url, path);

    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_GET,
        .keep_alive_enable = true,
        .timeout_ms = 30000,
        .transport_type = HTTP_TRANSPORT_OVER_SSL,
        .skip_cert_common_name_check = true,
    };

    esp_http_client_handle_t dl_client = esp_http_client_init(&config);
    if (!dl_client) return false;

    esp_http_client_set_header(dl_client, "X-Device-Mac", device_mac);
    esp_http_client_set_header(dl_client, "X-Device-Token", device_token);

    esp_err_t err = esp_http_client_open(dl_client, 0);
    if (err != ESP_OK) {
        esp_http_client_cleanup(dl_client);
        return false;
    }

    int content_length = esp_http_client_fetch_headers(dl_client);
    int status_code = esp_http_client_get_status_code(dl_client);

    if (status_code == 304 || status_code == 204) {
        ESP_LOGI(TAG, "daily-zip unchanged (304/204)");
        esp_http_client_close(dl_client);
        esp_http_client_cleanup(dl_client);
        return false;
    }

    if (status_code != 200) {
        ESP_LOGE(TAG, "daily-zip returned status code %d", status_code);
        esp_http_client_close(dl_client);
        esp_http_client_cleanup(dl_client);
        return false;
    }

    FILE *f = fopen(dest_path, "wb");
    if (!f) {
        ESP_LOGE(TAG, "Failed to open destination file %s", dest_path);
        esp_http_client_close(dl_client);
        esp_http_client_cleanup(dl_client);
        return false;
    }

    char *buffer = malloc(4096);
    if (!buffer) {
        fclose(f);
        esp_http_client_close(dl_client);
        esp_http_client_cleanup(dl_client);
        return false;
    }

    int read_bytes;
    int total_bytes = 0;
    while ((read_bytes = esp_http_client_read(dl_client, buffer, 4096)) > 0) {
        fwrite(buffer, 1, read_bytes, f);
        total_bytes += read_bytes;
    }

    free(buffer);
    fclose(f);
    esp_http_client_close(dl_client);
    esp_http_client_cleanup(dl_client);

    ESP_LOGI(TAG, "Downloaded %d bytes to %s", total_bytes, dest_path);
    return true;
}

bool api_refresh(bool skip, int battery, refresh_result_t *result) {
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "mac", device_mac);
    cJSON_AddBoolToObject(root, "skip", skip);
    if (battery >= 0) {
        cJSON_AddNumberToObject(root, "battery", battery);
    }
    char *post_data = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    char resp[1024];
    int status = 0;
    bool success = perform_request(HTTP_METHOD_POST, "/api/refresh", post_data, resp, sizeof(resp), &status, NULL);
    free(post_data);

    if (success && status == 200) {
        cJSON *json = cJSON_Parse(resp);
        if (json) {
            cJSON *idx = cJSON_GetObjectItem(json, "image_index");
            if (cJSON_IsNumber(idx)) result->image_index = idx->valueint;

            cJSON *orient = cJSON_GetObjectItem(json, "current_orientation");
            if (cJSON_IsString(orient)) strncpy(result->orientation, orient->valuestring, sizeof(result->orientation) - 1);

            cJSON *si = cJSON_GetObjectItem(json, "sleep_interval");
            if (cJSON_IsNumber(si)) result->sleep_interval = si->valueint;

            cJSON_Delete(json);
            return true;
        }
    }
    return false;
}

bool api_change_orientation(const char *orientation) {
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "mac", device_mac);
    cJSON_AddStringToObject(root, "orientation", orientation);
    char *post_data = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    char resp[128];
    int status = 0;
    bool success = perform_request(HTTP_METHOD_POST, "/api/change-orientation", post_data, resp, sizeof(resp), &status, NULL);
    free(post_data);

    return success && status == 200;
}

bool api_sync_ntp(void) {
    ESP_LOGI(TAG, "Initializing SNTP...");
    sntp_setoperatingmode(SNTP_OPMODE_POLL);
    sntp_setservername(0, "pool.ntp.org");
    sntp_setservername(1, "time.google.com");
    sntp_init();

    int retry = 0;
    const int retry_count = 10;
    while (sntp_get_sync_status() == SNTP_SYNC_STATUS_RESET && ++retry < retry_count) {
        ESP_LOGI(TAG, "Waiting for system time to be set... (%d/%d)", retry, retry_count);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    
    if (sntp_get_sync_status() == SNTP_SYNC_STATUS_COMPLETED) {
        time_t now;
        struct tm timeinfo;
        time(&now);
        localtime_r(&now, &timeinfo);
        char str[64];
        strftime(str, sizeof(str), "%c", &timeinfo);
        ESP_LOGI(TAG, "Time synchronized: %s", str);
        return true;
    }
    ESP_LOGE(TAG, "NTP Sync failed");
    return false;
}
