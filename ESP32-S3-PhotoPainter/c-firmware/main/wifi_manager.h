#ifndef WIFI_MANAGER_H
#define WIFI_MANAGER_H

#include <stdbool.h>

bool wifi_init(void);
bool wifi_connect_sta(const char *ssid, const char *password, int timeout_s);
void wifi_start_ap_and_portal(const char *reason);
void wifi_stop(void);
bool wifi_is_connected(void);
void wifi_get_mac_str(char *mac_out); // Returns 12-char hex MAC, uppercase

#endif // WIFI_MANAGER_H
