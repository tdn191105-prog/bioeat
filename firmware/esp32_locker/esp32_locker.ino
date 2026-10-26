/*
 * Постамат РосПит — черновая прошивка контроллера на ESP32 (Arduino core 3.x).
 *
 * ⚠️  НЕ ПРОВЕРЕНО НА ЖЕЛЕЗЕ. Скетч написан по документации библиотек и
 *     протоколу сервера (docs/locker_integration.md), компиляцию и работу
 *     на реальной плате, замках и QR-модуле нужно проверить на стенде.
 *     Программная часть сервера проверяется эмулятором scripts/locker_simulator.py.
 *
 * Что делает:
 *   - Wi-Fi + время по NTP (подпись запроса содержит отметку времени);
 *   - HTTPS с проверкой сертификата сервера (никакого setInsecure);
 *   - читает QR-модуль GM65/GM805 по UART и PIN с матричной клавиатуры 4×3;
 *   - подписывает запросы HMAC-SHA256: «device_id|ts|nonce|payload»;
 *   - открывает замок ячейки через расширители MCP23017 (2 шт. × 16 выходов)
 *     → модуль реле / MOSFET → соленоид 12 В;
 *   - читает герконы дверей (вторая пара MCP23017 на входы) и шлёт события;
 *   - long-polling команд сервера (открыть ячейку для загрузки / выемки);
 *   - сторожевой таймер: зависание → перезагрузка;
 *   - без сети замки НЕ открываются, на дисплее — «Нет связи, обратитесь в окно выдачи».
 *
 * Библиотеки: WiFi, WiFiClientSecure, HTTPClient (входят в ядро ESP32),
 *             ArduinoJson 7, Adafruit_MCP23X17, Keypad, LiquidCrystal_I2C.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_MCP23X17.h>
#include <Keypad.h>
#include <LiquidCrystal_I2C.h>
#include <esp_task_wdt.h>
#include <mbedtls/md.h>
#include <time.h>

#include "config.h"

// ----------------------------------------------------------------------------
//  Периферия
// ----------------------------------------------------------------------------
HardwareSerial QrSerial(2);
Adafruit_MCP23X17 locksA, locksB;     // выходы: замки 1–16 и 17–24
Adafruit_MCP23X17 doorsA, doorsB;     // входы: герконы 1–16 и 17–24
LiquidCrystal_I2C lcd(0x27, 16, 2);

const byte ROWS = 4, COLS = 3;
char KEYS[ROWS][COLS] = {{'1', '2', '3'}, {'4', '5', '6'}, {'7', '8', '9'}, {'*', '0', '#'}};
byte rowPins[ROWS] = {32, 33, 25, 26};
byte colPins[COLS] = {27, 14, 12};
Keypad keypad = Keypad(makeKeymap(KEYS), rowPins, colPins, ROWS, COLS);

WiFiClientSecure tls;
bool doorWasOpen[CELLS_COUNT + 1] = {false};
String pinBuffer;
uint32_t lastPoll = 0, lastHeartbeat = 0, lastNetOk = 0;

// ----------------------------------------------------------------------------
//  Дисплей
// ----------------------------------------------------------------------------
void show(const char *line1, const char *line2 = "") {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);
}

bool online() { return WiFi.status() == WL_CONNECTED && time(nullptr) > 1700000000; }

void showIdle() {
  if (online()) show("Pospit: QR ili", "PIN + #");
  // кириллицу HD44780 не умеет — на реальном экране лучше OLED/TFT со шрифтом
  else show("Net svyazi.", "Idite v okno vyd.");
}

// ----------------------------------------------------------------------------
//  Подпись запросов
// ----------------------------------------------------------------------------
String hmacSha256(const String &message) {
  byte out[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, (const unsigned char *)DEVICE_SECRET, strlen(DEVICE_SECRET));
  mbedtls_md_hmac_update(&ctx, (const unsigned char *)message.c_str(), message.length());
  mbedtls_md_hmac_finish(&ctx, out);
  mbedtls_md_free(&ctx);
  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + i * 2, "%02x", out[i]);
  return String(hex);
}

String makeNonce() {
  char buf[17];
  for (int i = 0; i < 8; i++) sprintf(buf + i * 2, "%02x", (uint8_t)esp_random());
  return String(buf);
}

// заполняет ts / nonce / sig для строки «device_id|ts|nonce|payload»
void signInto(JsonDocument &doc, const String &payload) {
  long ts = (long)time(nullptr);
  String nonce = makeNonce();
  String msg = String(DEVICE_ID) + "|" + ts + "|" + nonce + "|" + payload;
  doc["ts"] = ts;
  doc["nonce"] = nonce;
  doc["sig"] = hmacSha256(msg);
}

// ----------------------------------------------------------------------------
//  HTTPS
// ----------------------------------------------------------------------------
int postJson(const String &path, JsonDocument &body, JsonDocument &reply, uint32_t timeoutMs = 8000) {
  HTTPClient http;
  String url = String("https://") + SERVER_HOST + ":" + SERVER_PORT + path;
  if (!http.begin(tls, url)) return -1;
  http.setTimeout(timeoutMs);
  http.addHeader("Content-Type", "application/json");
  String payload;
  serializeJson(body, payload);
  int code = http.POST(payload);
  if (code > 0) {
    deserializeJson(reply, http.getString());
    lastNetOk = millis();
  }
  http.end();
  return code;
}

String devicePath(const char *action) { return String("/api/device/lockers/") + DEVICE_ID + "/" + action; }

// ----------------------------------------------------------------------------
//  Замки и двери
// ----------------------------------------------------------------------------
void pulseLock(int cell) {
  if (cell < 1 || cell > CELLS_COUNT) return;
  Adafruit_MCP23X17 &chip = cell <= 16 ? locksA : locksB;
  int pin = (cell - 1) % 16;
  chip.digitalWrite(pin, HIGH);
  delay(LOCK_PULSE_MS);           // соленоид: короткий импульс, не держать постоянно
  chip.digitalWrite(pin, LOW);
}

bool doorOpen(int cell) {
  Adafruit_MCP23X17 &chip = cell <= 16 ? doorsA : doorsB;
  return chip.digitalRead((cell - 1) % 16) == HIGH;   // геркон разомкнут = дверь открыта
}

void sendEvent(const char *type, int cell) {
  JsonDocument body, reply;
  body["type"] = type;
  body["cell"] = cell;
  signInto(body, String(type) + ":" + cell);
  postJson(devicePath("events"), body, reply);
}

void watchDoors() {
  for (int cell = 1; cell <= CELLS_COUNT; cell++) {
    bool open = doorOpen(cell);
    if (open != doorWasOpen[cell]) {
      doorWasOpen[cell] = open;
      sendEvent(open ? "door_opened" : "door_closed", cell);
    }
  }
}

// ----------------------------------------------------------------------------
//  Скан кода
// ----------------------------------------------------------------------------
void handleCode(const String &code) {
  if (!online()) {
    // без сервера проверить одноразовый код нельзя — замок не открываем
    show("Net svyazi.", "Idite v okno vyd.");
    return;
  }
  show("Proveryaem...");
  JsonDocument body, reply;
  body["code"] = code;
  signInto(body, code);
  int status = postJson(devicePath("scan"), body, reply);
  if (status != 200) {
    show("Oshibka svyazi", "Idite v okno vyd.");
    return;
  }
  if (String((const char *)reply["action"]) == "open") {
    int cell = reply["cell"];
    char line[17];
    snprintf(line, sizeof(line), "Yacheyka %d", cell);
    show("Otkryto!", line);
    pulseLock(cell);
  } else {
    show("Otkaz:", reply["reason"] | "kod");
  }
  delay(2500);
  showIdle();
}

void readQr() {
  static String buf;
  while (QrSerial.available()) {
    char ch = QrSerial.read();
    if (ch == '\r' || ch == '\n') {
      if (buf.length() > 0) handleCode(buf);
      buf = "";
    } else if (buf.length() < 120) {
      buf += ch;
    }
  }
}

void readKeypad() {
  char key = keypad.getKey();
  if (!key) return;
  if (key == '*') { pinBuffer = ""; showIdle(); return; }
  if (key == '#') {
    if (pinBuffer.length() == 6) handleCode(pinBuffer);
    pinBuffer = "";
    return;
  }
  if (pinBuffer.length() < 6) pinBuffer += key;
  String stars;
  for (size_t i = 0; i < pinBuffer.length(); i++) stars += '*';
  show("PIN:", stars.c_str());
}

// ----------------------------------------------------------------------------
//  Команды сервера (long-polling) и heartbeat
// ----------------------------------------------------------------------------
void pollCommands() {
  long ts = (long)time(nullptr);
  String nonce = makeNonce();
  String sig = hmacSha256(String(DEVICE_ID) + "|" + ts + "|" + nonce + "|commands");
  String url = String("https://") + SERVER_HOST + ":" + SERVER_PORT + devicePath("commands") +
               "?ts=" + ts + "&nonce=" + nonce + "&sig=" + sig + "&wait=20";
  HTTPClient http;
  if (!http.begin(tls, url)) return;
  http.setTimeout(25000);
  esp_task_wdt_reset();
  int code = http.GET();
  if (code == 200) {
    lastNetOk = millis();
    JsonDocument reply;
    deserializeJson(reply, http.getString());
    for (JsonObject cmd : reply["commands"].as<JsonArray>()) {
      if (String((const char *)cmd["action"]) == "open") pulseLock(cmd["cell"]);
    }
  }
  http.end();
}

void heartbeat() {
  JsonDocument body, reply;
  body["firmware"] = "esp32-draft-0.1";
  signInto(body, "heartbeat");
  postJson(devicePath("heartbeat"), body, reply);
}

// ----------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  // сторожевой таймер 40 с: дольше long-polling, короче «зависания навсегда»
  esp_task_wdt_config_t wdt = {.timeout_ms = 40000, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_init(&wdt);
  esp_task_wdt_add(NULL);

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  lcd.init();
  lcd.backlight();
  show("Zapusk...");

  locksA.begin_I2C(0x20);
  locksB.begin_I2C(0x21);
  doorsA.begin_I2C(0x22);
  doorsB.begin_I2C(0x23);
  for (int p = 0; p < 16; p++) {
    locksA.pinMode(p, OUTPUT); locksA.digitalWrite(p, LOW);
    locksB.pinMode(p, OUTPUT); locksB.digitalWrite(p, LOW);
    doorsA.pinMode(p, INPUT_PULLUP);
    doorsB.pinMode(p, INPUT_PULLUP);
  }
  for (int cell = 1; cell <= CELLS_COUNT; cell++) doorWasOpen[cell] = doorOpen(cell);

  QrSerial.begin(QR_UART_BAUD, SERIAL_8N1, QR_UART_RX_PIN, QR_UART_TX_PIN);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, NTP_SERVER);          // подпись использует UTC-время
  tls.setCACert(ROOT_CA_PEM);            // проверка сертификата сервера

  showIdle();
}

void loop() {
  esp_task_wdt_reset();
  readQr();
  readKeypad();
  watchDoors();

  if (online()) {
    if (millis() - lastHeartbeat > 30000) { heartbeat(); lastHeartbeat = millis(); }
    // long-polling блокирует цикл до 20 с — в реальной прошивке вынести в отдельную задачу FreeRTOS,
    // чтобы сканер и двери обслуживались параллельно
    if (millis() - lastPoll > 1000) { pollCommands(); lastPoll = millis(); }
  } else if (millis() - lastNetOk > 60000) {
    showIdle();
  }
  delay(20);
}
