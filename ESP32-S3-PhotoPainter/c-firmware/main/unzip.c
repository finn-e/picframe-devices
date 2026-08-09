#include "unzip.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "esp_log.h"
#include "miniz.h"

static const char *TAG = "Unzip";

bool unzip_file(const char *zip_path, const char *dest_dir) {
    mz_zip_archive zip_archive;
    memset(&zip_archive, 0, sizeof(zip_archive));

    mz_bool status = mz_zip_reader_init_file(&zip_archive, zip_path, 0);
    if (!status) {
        ESP_LOGE(TAG, "Failed to initialize ZIP reader for %s", zip_path);
        return false;
    }

    mz_uint num_files = mz_zip_reader_get_num_files(&zip_archive);
    ESP_LOGI(TAG, "ZIP archive contains %u files", num_files);

    for (mz_uint i = 0; i < num_files; i++) {
        mz_zip_archive_file_stat file_stat;
        if (!mz_zip_reader_get_file_stat(&zip_archive, i, &file_stat)) {
            ESP_LOGE(TAG, "Failed to get file stat for index %u", i);
            continue;
        }

        if (mz_zip_reader_is_file_a_directory(&zip_archive, i)) {
            // Ignore directories since the assets zip contains flat files
            continue;
        }

        char dest_file_path[256];
        snprintf(dest_file_path, sizeof(dest_file_path), "%s/%s", dest_dir, file_stat.m_filename);

        ESP_LOGI(TAG, "Extracting %s to %s", file_stat.m_filename, dest_file_path);
        mz_bool extract_status = mz_zip_reader_extract_to_file(&zip_archive, i, dest_file_path, 0);
        if (!extract_status) {
            ESP_LOGE(TAG, "Failed to extract file %s", file_stat.m_filename);
        }
    }

    mz_zip_reader_end(&zip_archive);
    return true;
}
