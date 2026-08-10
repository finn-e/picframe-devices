idf_component_register(SRCS "main.c"
                            "axp2101.c"
                            "epd_7in3f.c"
                            "wifi_manager.c"
                            "api_client.c"
                            "config_store.c"
                            "unzip.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES fatfs spiffs json esp_http_client esp_wifi nvs_flash lwip app_update driver esp_https_ota esp_http_server)
