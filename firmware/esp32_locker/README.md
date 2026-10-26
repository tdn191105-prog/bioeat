# Прошивка постамата (черновик)

> ⚠️ **Не проверено на железе.** Скетч не компилировался под реальную плату и не запускался
> с замками, герконами и QR-модулем. Это отправная точка для стенда, а не готовая прошивка.
> Серверная часть и протокол проверены тестами и эмулятором `scripts/locker_simulator.py`.

## Сборка

1. Arduino IDE 2.x, ядро **esp32 by Espressif 3.x**.
2. Библиотеки: ArduinoJson 7, Adafruit MCP23017 Arduino Library, Keypad, LiquidCrystal I2C.
3. `cp config.example.h config.h` и заполнить: Wi-Fi, адрес сервера, `DEVICE_SECRET`
   (`python scripts/locker_simulator.py --device locker-b1 secret` на сервере с боевым `SECRET_KEY`),
   корневой сертификат ISRG Root X1.
4. Плата «ESP32 Dev Module», прошить.

## Что доделать на стенде

- вынести long-polling в отдельную задачу FreeRTOS — сейчас он блокирует цикл до 20 с;
- дисплей с кириллицей (OLED SSD1306/TFT) вместо HD44780;
- антидребезг герконов;
- защита от повторного импульса замка, контроль тока соленоида;
- OTA-обновление прошивки;
- хранение секрета в NVS с шифрованием флеша (Flash Encryption + Secure Boot),
  а не в `config.h`.

Протокол и схема подключения — в [docs/locker_integration.md](../../docs/locker_integration.md).
