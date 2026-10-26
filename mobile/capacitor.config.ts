import type { CapacitorConfig } from '@capacitor/cli';

// Адрес веб-версии задаётся на этапе сборки:
//   CAP_SERVER_URL=https://rospit.example.ru npx cap sync
// Приложение — тонкая обёртка: интерфейс и данные приходят с сервера,
// поэтому обновления не требуют пересборки APK.
const serverUrl = process.env.CAP_SERVER_URL || 'https://rospit.example.ru';

const config: CapacitorConfig = {
  appId: 'ru.rospit.app',
  appName: 'РосПит',
  webDir: 'www',
  backgroundColor: '#0a0a0c',
  server: {
    url: serverUrl,
    cleartext: serverUrl.startsWith('http://'),   // только для локальной отладки
    // страница, если сервер недоступен (нет сети)
    errorPath: 'error.html',
  },
  android: {
    // внешние ссылки (СБП, банковские приложения) обрабатывает MainActivity
    allowMixedContent: false,
  },
  ios: {
    contentInset: 'never',
  },
};

export default config;
