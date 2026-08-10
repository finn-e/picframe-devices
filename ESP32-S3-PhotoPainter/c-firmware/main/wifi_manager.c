#include "wifi_manager.h"
#include <string.h>
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_http_server.h"
#include "lwip/sockets.h"
#include "lwip/sys.h"
#include "lwip/api.h"
#include "cJSON.h"
#include "config_store.h"
#include "axp2101.h"

static const char *TAG = "WifiManager";

static esp_netif_t *sta_netif = NULL;
static esp_netif_t *ap_netif = NULL;
static bool wifi_connected = false;
static char device_mac_str[18] = {0}; // XX:XX:XX:XX:XX:XX
static char device_mac_flat[13] = {0}; // XXXXXXXXXXXX

// DNS Server variables
static TaskHandle_t dns_task_handle = NULL;
static httpd_handle_t web_server = NULL;
static char portal_reason[32] = "setup";

// Event handler
static void event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_connected = false;
        ESP_LOGI(TAG, "Disconnected from Wi-Fi");
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        wifi_connected = true;
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
    }
}

bool wifi_init(void) {
    esp_err_t ret = esp_netif_init();
    if (ret != ESP_OK) return false;
    ret = esp_event_loop_create_default();
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) return false;

    sta_netif = esp_netif_create_default_wifi_sta();
    ap_netif = esp_netif_create_default_wifi_ap();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ret = esp_wifi_init(&cfg);
    if (ret != ESP_OK) return false;

    ret = esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &event_handler, NULL, NULL);
    if (ret != ESP_OK) return false;
    ret = esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &event_handler, NULL, NULL);
    if (ret != ESP_OK) return false;

    ret = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (ret != ESP_OK) return false;

    uint8_t mac[6];
    esp_wifi_get_mac(WIFI_IF_STA, mac);
    snprintf(device_mac_str, sizeof(device_mac_str), "%02x:%02x:%02x:%02x:%02x:%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    snprintf(device_mac_flat, sizeof(device_mac_flat), "%02X%02X%02X%02X%02X%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

    ESP_LOGI(TAG, "WiFi module initialized. MAC: %s", device_mac_str);
    return true;
}

bool wifi_connect_sta(const char *ssid, const char *password, int timeout_s) {
    if (strlen(ssid) == 0) {
        ESP_LOGW(TAG, "SSID is empty");
        return false;
    }

    wifi_config_t wifi_config = {0};
    strncpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, password, sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.scan_method = WIFI_FAST_SCAN;
    wifi_config.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;

    ESP_LOGI(TAG, "Connecting to STA: %s", ssid);
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
    esp_wifi_start();
    esp_wifi_connect();

    int elapsed = 0;
    while (!wifi_connected && elapsed < timeout_s * 10) {
        vTaskDelay(pdMS_TO_TICKS(100));
        elapsed++;
    }

    if (wifi_connected) {
        ESP_LOGI(TAG, "Wi-Fi Connected!");
        return true;
    } else {
        ESP_LOGW(TAG, "Wi-Fi Connection Timeout");
        esp_wifi_stop();
        return false;
    }
}

bool wifi_is_connected(void) {
    return wifi_connected;
}

void wifi_get_mac_str(char *mac_out) {
    strcpy(mac_out, device_mac_str);
}

// ── DNS Server Task (Captive Portal DNS Hijacker) ─────────────────────────────
static void dns_server_task(void *pvParameters) {
    uint8_t rx_buffer[512];
    struct sockaddr_in server_addr;

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "Unable to create socket: errno %d", errno);
        vTaskDelete(NULL);
        return;
    }

    server_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(53);

    int err = bind(sock, (struct sockaddr *)&server_addr, sizeof(server_addr));
    if (err < 0) {
        ESP_LOGE(TAG, "Socket unable to bind: errno %d", errno);
        close(sock);
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "DNS server listening on port 53");

    while (1) {
        struct sockaddr_in source_addr;
        socklen_t socklen = sizeof(source_addr);
        int len = recvfrom(sock, rx_buffer, sizeof(rx_buffer), 0, (struct sockaddr *)&source_addr, &socklen);

        if (len < 0) {
            ESP_LOGE(TAG, "recvfrom failed: errno %d", errno);
            break;
        }

        if (len > 12) {
            // Very simple DNS parser + response creator mapping everything to 192.168.4.1
            // Copy transaction ID
            uint8_t tx_id[2] = {rx_buffer[0], rx_buffer[1]};
            
            // Find start of question section
            int idx = 12;
            while (idx < len) {
                uint8_t l = rx_buffer[idx];
                if (l == 0) {
                    idx += 1;
                    break;
                }
                idx += 1 + l;
            }

            if (idx + 4 <= len) {
                // We have a query. Respond with 192.168.4.1 (0xC0A80401)
                uint8_t resp[512];
                int r_len = 0;

                // Tx ID
                resp[0] = tx_id[0]; resp[1] = tx_id[1];
                // Flags: Standard query response, No error
                resp[2] = 0x81; resp[3] = 0x80;
                // Questions: 1
                resp[4] = 0x00; resp[5] = 0x01;
                // Answer RRs: 1
                resp[6] = 0x00; resp[7] = 0x01;
                // Authority/Additional RRs: 0
                resp[8] = 0x00; resp[9] = 0x00;
                resp[10] = 0x00; resp[11] = 0x00;

                r_len = 12;
                // Copy question section
                int q_len = idx + 4 - 12;
                memcpy(&resp[r_len], &rx_buffer[12], q_len);
                r_len += q_len;

                // Answer: Name pointer to question start (0xC00C)
                resp[r_len++] = 0xC0; resp[r_len++] = 0x0C;
                // Type: A (0x0001)
                resp[r_len++] = 0x00; resp[r_len++] = 0x01;
                // Class: IN (0x0001)
                resp[r_len++] = 0x00; resp[r_len++] = 0x01;
                // TTL: 60s (0x0000003C)
                resp[r_len++] = 0x00; resp[r_len++] = 0x00; resp[r_len++] = 0x00; resp[r_len++] = 0x3C;
                // Data length: 4
                resp[r_len++] = 0x00; resp[r_len++] = 0x04;
                // IP: 192.168.4.1
                resp[r_len++] = 192; resp[r_len++] = 168; resp[r_len++] = 4; resp[r_len++] = 1;

                sendto(sock, resp, r_len, 0, (struct sockaddr *)&source_addr, sizeof(source_addr));
            }
        }
    }

    close(sock);
    vTaskDelete(NULL);
}

// URL Decode helper
static void url_decode(char *dst, const char *src) {
    char a, b;
    while (*src) {
        if ((*src == '%') &&
            ((a = src[1]) && (b = src[2])) &&
            (isxdigit((int)a) && isxdigit((int)b))) {
            if (a >= 'a') a -= 'a' - 'A';
            if (a >= 'A') a -= ('A' - 10);
            else a -= '0';
            if (b >= 'a') b -= 'a' - 'A';
            if (b >= 'A') b -= ('A' - 10);
            else b -= '0';
            *dst++ = 16 * a + b;
            src += 3;
        } else if (*src == '+') {
            *dst++ = ' ';
            src++;
        } else {
            *dst++ = *src++;
        }
    }
    *dst = '\0';
}

// ── Captive Portal Web Server handlers ────────────────────────────────────────
static esp_err_t root_get_handler(httpd_req_t *req) {
    char host[64] = {0};
    if (httpd_req_get_hdr_value_str(req, "Host", host, sizeof(host)) == ESP_OK) {
        // If not matching our gateway IP or local hostname, redirect to portal page
        if (strstr(host, "192.168.4.1") == NULL && strstr(host, "picframe.setup") == NULL) {
            httpd_resp_set_status(req, "302 Found");
            httpd_resp_set_hdr(req, "Location", "http://192.168.4.1/");
            httpd_resp_send(req, NULL, 0);
            return ESP_OK;
        }
    }

    // Load wifi config for default display values
    app_wifi_config_t cfg;
    config_load_wifi(&cfg);

    char dev_id[16];
    strncpy(dev_id, device_mac_flat + 4, 8); // Last 8 digits
    dev_id[8] = '\0';

    const char *err_msg = "";
    if (strcmp(portal_reason, "wifi_failed") == 0) {
        err_msg = "<div class=\"err\">Could not connect to Wi-Fi. Check network name and password.</div>";
    } else if (strcmp(portal_reason, "unreachable") == 0) {
        err_msg = "<div class=\"err\">Cannot reach PicFrames server. Re-enter credentials.</div>";
    }

    char *html = malloc(8192);
    if (!html) return ESP_FAIL;

    snprintf(html, 8192,
             "<!DOCTYPE html><html><head><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
             "<title>PicFrame Setup</title><style>"
             "*{{box-sizing:border-box;margin:0;padding:0}}"
             "body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}"
             ".card{{background:rgba(30,41,59,.8);border:1px solid rgba(255,255,255,.08);padding:32px;border-radius:20px;width:100%;max-width:440px}}"
             "h2{{font-weight:700;font-size:1.7rem;margin-bottom:6px;background:linear-gradient(135deg,hsl(190,100%,55%),hsl(260,90%,65%));-webkit-background-clip:text;-webkit-text-fill-color:transparent;text-align:center}}"
             ".sub{{text-align:center;color:#64748b;font-size:.85rem;margin-bottom:20px}}"
             ".err{{color:hsl(0,85%,65%);background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.2);padding:10px;border-radius:8px;margin-bottom:14px;font-size:.82rem;text-align:center}}"
             "label{{display:block;font-size:.82rem;color:#94a3b8;margin-bottom:4px;font-weight:500}}"
             ".ig{{margin-bottom:14px}}"
             "input[type=text],input[type=password]{{width:100%;padding:10px 12px;background:rgba(15,23,42,.6);border:1px solid rgba(255,255,255,.1);border-radius:8px;color:#fff;font-size:.92rem}}"
             "input[type=submit]{{width:100%;padding:12px;border:none;border-radius:9px;background:linear-gradient(135deg,hsl(190,100%,45%),hsl(260,90%,55%));color:#fff;font-size:.97rem;font-weight:600;cursor:pointer;margin-top:4px}}"
             ".notice{{background:rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.3);border-radius:10px;padding:12px;font-size:.82rem;margin-bottom:20px;color:#a5b4fc;line-height:1.5}}"
             "</style></head><body><div class=\"card\">"
             "<h2>PicFrame Setup</h2><div class=\"sub\">Device ID: %s &nbsp;|&nbsp; MAC: %s</div>"
             "%s"
             "<div class=\"notice\">&#x24D8; Enter your Wi-Fi credentials and PicFrames server details.</div>"
             "<form method=\"POST\" action=\"/save\">"
             "<div class=\"ig\"><label>Wi-Fi Network (SSID)</label><input type=\"text\" name=\"ssid\" value=\"%s\" required></div>"
             "<div class=\"ig\"><label>Wi-Fi Password</label><input type=\"password\" name=\"wifi_pass\" value=\"%s\"></div>"
             "<div class=\"ig\"><label>PicFrames Server URL</label><input type=\"text\" name=\"server_url\" value=\"%s\" placeholder=\"https://picframes.treee.house\"></div>"
             "<div class=\"ig\"><label>Username</label><input type=\"text\" name=\"username\" value=\"%s\"></div>"
             "<div class=\"ig\"><label>Password</label><input type=\"password\" name=\"token\" value=\"\"></div>"
             "<input type=\"submit\" value=\"Save &amp; Connect\"></form></div></body></html>",
             dev_id, device_mac_str, err_msg,
             cfg.ssid, cfg.password, cfg.server_url, cfg.username);

    httpd_resp_send(req, html, HTTPD_RESP_USE_ASSERTION);
    free(html);
    return ESP_OK;
}

static esp_err_t save_post_handler(httpd_req_t *req) {
    char buf[1024];
    int ret, remaining = req->content_len;

    if (remaining >= sizeof(buf)) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Post content too long");
        return ESP_FAIL;
    }

    ret = httpd_req_recv(req, buf, remaining);
    if (ret <= 0) {
        if (ret == HTTPD_SOCK_ERR_TIMEOUT) {
            httpd_resp_send_408(req);
        }
        return ESP_FAIL;
    }
    buf[ret] = '\0';

    // Parse form parameters: ssid, wifi_pass, server_url, username, token
    app_wifi_config_t cfg;
    config_load_wifi(&cfg);

    char *token = strtok(buf, "&");
    while (token != NULL) {
        char key[64] = {0};
        char val[256] = {0};
        if (sscanf(token, "%63[^=]=%255s", key, val) == 2) {
            char decoded_val[256] = {0};
            url_decode(decoded_val, val);
            if (strcmp(key, "ssid") == 0) strncpy(cfg.ssid, decoded_val, sizeof(cfg.ssid) - 1);
            else if (strcmp(key, "wifi_pass") == 0) strncpy(cfg.password, decoded_val, sizeof(cfg.password) - 1);
            else if (strcmp(key, "server_url") == 0) strncpy(cfg.server_url, decoded_val, sizeof(cfg.server_url) - 1);
            else if (strcmp(key, "username") == 0) strncpy(cfg.username, decoded_val, sizeof(cfg.username) - 1);
            else if (strcmp(key, "token") == 0 && strlen(decoded_val) > 0) strncpy(cfg.token, decoded_val, sizeof(cfg.token) - 1);
        }
        token = strtok(NULL, "&");
    }

    config_save_wifi(&cfg);
    ESP_LOGI(TAG, "WiFi config saved. Rebooting...");

    const char *resp = "<html><body><h2>Saved! Rebooting...</h2></body></html>";
    httpd_resp_send(req, resp, HTTPD_RESP_USE_ASSERTION);

    vTaskDelay(pdMS_TO_TICKS(1000));
    axp2101_reboot();
    return ESP_OK;
}

void wifi_start_ap_and_portal(const char *reason) {
    strncpy(portal_reason, reason, sizeof(portal_reason) - 1);
    
    char ap_ssid[32];
    snprintf(ap_ssid, sizeof(ap_ssid), "PicFrame-%s", device_mac_flat);

    ESP_LOGI(TAG, "Starting AP: %s", ap_ssid);
    
    wifi_config_t ap_config = {
        .ap = {
            .ssid_len = strlen(ap_ssid),
            .max_connection = 4,
            .authmode = WIFI_AUTH_OPEN
        }
    };
    memcpy(ap_config.ap.ssid, ap_ssid, strlen(ap_ssid));

    esp_wifi_stop();
    esp_wifi_set_mode(WIFI_MODE_AP);
    esp_wifi_set_config(WIFI_IF_AP, &ap_config);
    esp_wifi_start();

    // Start DNS server task
    xTaskCreate(dns_server_task, "dns_server", 4096, NULL, 5, &dns_task_handle);

    // Start Web Server
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_open_sockets = 4;
    config.ctrl_port = 32768;

    if (httpd_start(&web_server, &config) == ESP_OK) {
        httpd_uri_t root_uri = {
            .uri       = "/",
            .method    = HTTP_GET,
            .handler   = root_get_handler,
            .user_ctx  = NULL
        };
        httpd_register_uri_handler(web_server, &root_uri);

        httpd_uri_t save_uri = {
            .uri       = "/save",
            .method    = HTTP_POST,
            .handler   = save_post_handler,
            .user_ctx  = NULL
        };
        httpd_register_uri_handler(web_server, &save_uri);

        // Catch-all redirect uri
        httpd_uri_t redirect_uri = {
            .uri       = "*",
            .method    = HTTP_GET,
            .handler   = root_get_handler,
            .user_ctx  = NULL
        };
        httpd_register_uri_handler(web_server, &redirect_uri);
    }
}

void wifi_stop(void) {
    if (web_server) {
        httpd_stop(web_server);
        web_server = NULL;
    }
    if (dns_task_handle) {
        vTaskDelete(dns_task_handle);
        dns_task_handle = NULL;
    }
    esp_wifi_stop();
}
