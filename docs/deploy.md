# Публичный адрес по HTTPS

Без публичного HTTPS-адреса не работают ни APK, ни «На экран Домой» на iPhone,
ни вебхуки оплаты. Нужны **сервер** (любой VPS с Docker) и **домен** (или поддомен вуза).

## Вариант 1. VPS за 15 минут (для пилота)

Подойдёт любой российский VPS: 2 vCPU, 2 ГБ RAM, 20 ГБ диска, Ubuntu 24.04
(Timeweb Cloud, Selectel, Yandex Cloud, REG.RU — примерно 400–900 ₽ в месяц, проверить актуальные цены).

1. **Домен.** В DNS добавить запись `A rospit.<домен>` → IP сервера. Подождать 5–15 минут.
2. **Docker** на сервере:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. **Код:**
   ```bash
   git clone <адрес репозитория> rospit && cd rospit && git checkout rospit
   cp deploy/.env.prod.example .env.prod
   nano .env.prod     # DOMAIN, ACME_EMAIL, SECRET_KEY (openssl rand -hex 32), POSTGRES_PASSWORD
   ```
4. **Запуск:**
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
   docker compose -f docker-compose.prod.yml --env-file .env.prod exec app python -m app.demo_data   # демо-заказы, по желанию
   ```
   Caddy сам получит сертификат Let's Encrypt — через минуту открывается `https://rospit.<домен>`.
5. **Проверка:** `curl https://rospit.<домен>/api/health` → `{"status":"ok",…}`.

Что настроено в `docker-compose.prod.yml`:

- Caddy перед приложением: автоматический HTTPS, редирект с HTTP (308), HSTS, сжатие;
- `ENVIRONMENT=production`: приложение **не стартует**, если `SECRET_KEY` по умолчанию или
  короче 32 символов, `CORS_ORIGINS=*`, cookie без `Secure` или `PUBLIC_BASE_URL` не на https;
- `CORS_ORIGINS` — только свой домен, cookie сессии `Secure; HttpOnly; SameSite=Lax`;
- база и приложение не публикуют порты наружу, наружу открыты только 80 и 443;
- `FORWARDED_ALLOW_IPS` — приложение видит настоящий IP клиента из заголовка Caddy
  (нужно для проверки адресов вебхуков ЮKassa).

Проверено локально: стек поднимается с `DOMAIN=localhost` (Caddy выдаёт локальный сертификат),
`/api/health` отвечает по HTTPS, HTTP → HTTPS 308, cookie с `Secure`, чужой `Origin` не получает
`Access-Control-Allow-Origin`. На настоящем VPS с доменом и Let's Encrypt **не запускалось** —
сервера и домена у разработчика нет.

Обновление: `git pull && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`.
Резервная копия базы: `docker compose … exec db pg_dump -U bioeat bioeat > backup.sql` (по cron раз в сутки).

## Вариант 2. Временный туннель для показа (только демо)

Если сервера ещё нет, а показать с телефона нужно сегодня, — Cloudflare Tunnel с компьютера:

```bash
brew install cloudflared                    # или скачать с developers.cloudflare.com
make local                                  # приложение на http://localhost:8000
cloudflared tunnel --url http://localhost:8000
```

Cloudflared напечатает адрес вида `https://<случайные-слова>.trycloudflare.com` — его можно открыть
на телефоне и даже собрать на него APK.

**Ограничения:** адрес меняется при каждом запуске; работает, пока включён ноутбук; трафик идёт
через Cloudflare; гарантий доступности нет. Для пилота со студентами и для вебхуков
боевой оплаты — только VPS.

## Что нужно от команды

- сервер (VPS) и доступ к нему по SSH;
- домен или поддомен (например, `pit.rosbiotech.ru` — тогда нужно согласие IT-службы вуза
  и запись в DNS вуза);
- почта для уведомлений Let's Encrypt.
