# Мобильные сборки: Android APK, iPhone

Приложение одно — PWA. Для Android и iOS это тонкая обёртка Capacitor (`mobile/`), которая
открывает веб-версию с сервера (`server.url`). Плюс: обновления приезжают без пересборки,
минус: без сервера и интернета обёртка показывает только экран «Нет связи».

## Android: APK

Настройки обёртки (`mobile/capacitor.config.ts`): `appId` `ru.rospit.app`, имя «РосПит»,
иконка и сплэш из логотипа (`mobile/resources/`, генерация — `npm run assets`),
адрес сервера — переменная `CAP_SERVER_URL` на этапе сборки, версия 1.1.

Доработки нативной части:

- **Оплата внутри WebView** — `android/app/src/main/java/ru/rospit/app/ExternalLinksPlugin.java`.
  Ссылки СБП (`https://qr.nspk.ru/…`, схемы `bankXXXXXXXXXX://`, `intent://`) уходят в систему —
  Android предлагает выбрать банковское приложение; если банка нет — подсказка выбрать карту.
  Страницы ЮKassa и 3-D Secure любого банка остаются в WebView, поэтому банк возвращает
  студента прямо в приложение (`return_url`), где экран заказа ждёт подтверждения.
- **Кнопка «Назад»** (`static/js/app.js`): закрывает открытый лист, иначе шаг назад по истории,
  на главной и на входе — выход из приложения.
- **Нет связи** — `mobile/www/error.html` вместо системной ошибки WebView.

### Как собрать

Локально (нужны Node 22, JDK 21, Android SDK 36):

```bash
cd mobile
npm ci
CAP_SERVER_URL=https://rospit.<домен> npm run android:debug
# → mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

Без Android SDK — через GitHub Actions (`.github/workflows/android.yml`):
GitHub → вкладка **Actions** → **Android APK** → **Run workflow** → указать адрес сервера →
через ~5 минут в запуске появится артефакт **rospit-debug-apk**. Workflow также запускается сам
при изменениях в `mobile/`; адрес по умолчанию берётся из переменной репозитория `ROSPIT_SERVER_URL`.

Debug-APK ставится на телефон напрямую (разрешить установку из неизвестных источников).
Для RuStore / Google Play нужен release-APK/AAB, подписанный ключом команды
(`./gradlew bundleRelease` + keystore) — ключ хранить вне репозитория.

### Альтернатива: TWA

| | Capacitor (сделано) | TWA через Bubblewrap |
|---|---|---|
| Что это | Свой WebView + нативный код | Chrome в полноэкранном режиме, без своего WebView |
| Плюсы | Обработка ссылок СБП и «Назад» в нашем коде, работает без Chrome, есть iOS-проект | Меньше APK, движок Chrome (как в браузере), push и установки PWA «из коробки» |
| Минусы | Свой WebView: ведёт себя чуть иначе Chrome | Нужен `/.well-known/assetlinks.json` на домене с SHA-256 ключа подписи; без Chrome на телефоне не работает; iOS нет |

## iPhone

### Основной путь для пилота: веб-версия + «На экран Домой»

TestFlight требует платного аккаунта Apple Developer (99 $ в год, оплата из России затруднена),
Mac с Xcode и проверки Apple. Для пилота этого не нужно: PWA уже ведёт себя как приложение.

Проверено в коде: `apple-mobile-web-app-capable`, `apple-mobile-web-app-title` «РосПит»,
статус-бар `black-translucent`, `apple-touch-icon` 180×180 с логотипом, стартовые экраны
(`apple-touch-startup-image`) для iPhone SE…Pro Max и iPad, `viewport-fit=cover` и отступы
safe-area. Инструкция для студентов в три шага с картинками —
[docs/students_iphone.md](students_iphone.md).

### TestFlight — когда будут Mac и аккаунт

iOS-проект уже создан: `mobile/ios/App` (Capacitor 8, Swift Package Manager, без CocoaPods),
иконка и сплэш сгенерированы. На этой машине нет Xcode — сборка **не проверялась**.

1. Mac с Xcode 16+, аккаунт Apple Developer Program (для организации — D-U-N-S номер).
2. ```bash
   cd mobile && npm ci
   CAP_SERVER_URL=https://rospit.<домен> npx cap sync ios
   npx cap open ios
   ```
3. В Xcode: таргет **App** → Signing & Capabilities → выбрать команду, Bundle Identifier
   `ru.rospit.app` (зарегистрировать в developer.apple.com → Identifiers).
4. Version 1.1, Build 1. Product → Archive → Distribute App → App Store Connect → Upload.
5. В App Store Connect создать приложение «РосПит», вкладка TestFlight: заполнить
   «Что тестировать», контакт и, для внешних тестировщиков, пройти бета-проверку Apple (1–2 дня).
6. Добавить тестировщиков по почте или публичной ссылке — её и отправлять студентам.

Учтите: Apple может отклонить приложение, которое «просто показывает сайт» (Guideline 4.2).
Для TestFlight внутри команды это не мешает, для публикации в App Store понадобятся нативные
функции (push, сканер QR) — поэтому для пилота рекомендуем PWA.
