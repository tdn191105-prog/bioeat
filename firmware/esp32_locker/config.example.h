// Скопируйте в config.h и заполните. config.h в git не попадает.
#pragma once

#define WIFI_SSID      "rosbiotech-iot"
#define WIFI_PASSWORD  ""

// Публичный адрес сервера РосПит (только HTTPS)
#define SERVER_HOST    "rospit.example.ru"
#define SERVER_PORT    443

// Выдаётся сервером: python scripts/locker_simulator.py --device locker-b1 secret
#define DEVICE_ID      "locker-b1"
#define DEVICE_SECRET  ""

// Корневой сертификат, которым подписан сертификат сервера (Let's Encrypt — ISRG Root X1).
// Вставьте PEM целиком; без него прошивка не подключится — это намеренно.
static const char ROOT_CA_PEM[] = R"PEM(
-----BEGIN CERTIFICATE-----
...вставьте ISRG Root X1...
-----END CERTIFICATE-----
)PEM";

// Аппаратная конфигурация
#define CELLS_COUNT        24
#define QR_UART_RX_PIN     16      // TX модуля GM65 → RX ESP32
#define QR_UART_TX_PIN     17
#define QR_UART_BAUD       9600
#define I2C_SDA_PIN        21
#define I2C_SCL_PIN        22
#define LOCK_PULSE_MS      600     // сколько держать соленоид замка
#define NTP_SERVER         "pool.ntp.org"
