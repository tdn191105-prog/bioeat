/* Каркас приложения: маршрутизация, навигация, общий хром. */
import { state, subscribe, loadUser, loadCart, loadActiveOrders, isStaff, isAdmin } from './state.js';
import { esc, toast, go, closeSheet } from './ui.js';

const ROUTES = {
  '/': () => import('./views/home.js'),
  '/menu': () => import('./views/menu.js'),
  '/dish/:id': () => import('./views/dish.js'),
  '/cart': () => import('./views/cart.js'),
  '/checkout': () => import('./views/checkout.js'),
  '/orders': () => import('./views/orders.js'),
  '/order/:id': () => import('./views/order.js'),
  '/pay/:id': () => import('./views/pay.js'),
  '/profile': () => import('./views/profile.js'),
  '/login': () => import('./views/auth.js'),
  '/operator': () => import('./views/operator.js'),
  '/admin': () => import('./views/admin.js'),
  '/reviews': () => import('./views/reviews.js'),
};

const NAV = [
  { href: '#/', icon: '🏠', label: 'Главная', match: (p) => p === '/' },
  { href: '#/menu', icon: '🍲', label: 'Меню', match: (p) => p.startsWith('/menu') },
  { href: '#/cart', icon: '🛒', label: 'Корзина', match: (p) => p === '/cart' || p === '/checkout', badge: () => state.cart.count },
  { href: '#/orders', icon: '🧾', label: 'Заказы', match: (p) => p.startsWith('/order') || p.startsWith('/pay') },
  { href: '#/profile', icon: '👤', label: 'Профиль', match: (p) => p === '/profile' },
];

const BACKABLE = ['/checkout', '/cart', '/profile'];

/* Позиция прокрутки меню: вернувшись из карточки блюда, пользователь должен
   оказаться там же, где нажал, а не в начале длинного списка. */
const scrollMemory = new Map();

const el = {
  app: document.getElementById('app'),
  rail: document.getElementById('rail'),
  shell: document.getElementById('shell'),
  title: document.getElementById('page-title'),
  back: document.getElementById('back-btn'),
  bell: document.getElementById('bell'),
  content: document.getElementById('content'),
  tabbar: document.getElementById('tabbar'),
  actionBar: document.getElementById('action-bar'),
};

let currentView = null;
let previousPath = parseHash().path;

/* ------------------------------ Разбор пути ------------------------------- */
function parseHash() {
  const raw = (window.location.hash || '#/').slice(1) || '/';
  const [pathPart, queryPart] = raw.split('?');
  const path = pathPart.replace(/\/+$/, '') || '/';
  return { path, query: new URLSearchParams(queryPart || '') };
}

function matchRoute(path) {
  if (ROUTES[path]) return { loader: ROUTES[path], params: {} };
  for (const pattern of Object.keys(ROUTES)) {
    if (!pattern.includes(':')) continue;
    const patternParts = pattern.split('/');
    const pathParts = path.split('/');
    if (patternParts.length !== pathParts.length) continue;
    const params = {};
    const ok = patternParts.every((part, i) => {
      if (part.startsWith(':')) { params[part.slice(1)] = decodeURIComponent(pathParts[i]); return true; }
      return part === pathParts[i];
    });
    if (ok) return { loader: ROUTES[pattern], params };
  }
  return null;
}

/* ------------------------------ Навигация -------------------------------- */
function renderNav(path) {
  const item = (n, cls) => {
    const count = n.badge ? n.badge() : 0;
    return `<a class="${cls} ${n.match(path) ? 'is-active' : ''}" href="${n.href}">
              <span class="tab__ico">${n.icon}</span>
              <span class="tab__label">${esc(n.label)}</span>
              ${count ? `<span class="tab__count">${count}</span>` : ''}
            </a>`;
  };

  el.tabbar.innerHTML = NAV.map((n) => item(n, 'tab')).join('');

  const staffLinks = [];
  if (isStaff()) {
    staffLinks.push({ href: '#/operator', icon: '👨‍🍳', label: 'Кабинет столовой', match: (p) => p === '/operator' });
  }
  if (isStaff()) {
    staffLinks.push({ href: '#/reviews', icon: '💬', label: 'Отзывы', match: (p) => p === '/reviews' });
  }
  if (isAdmin()) {
    staffLinks.push({ href: '#/admin', icon: '⚙️', label: 'Админ-панель', match: (p) => p === '/admin' });
  }

  el.rail.innerHTML = `
    <a class="rail__brand" href="#/">
      <img class="rail__logo" src="/static/icons/icon.svg" alt="" width="34" height="34">
      <span>РосПит</span>
    </a>
    ${NAV.map((n) => item(n, 'rail__item')).join('')}
    ${
      staffLinks.length
        ? `<div class="rail__group">Персонал столовой</div>
           ${staffLinks.map((n) => item(n, 'rail__item')).join('')}`
        : ''
    }
    <div class="rail__foot">
      <div class="small muted" style="padding:0 12px 10px">
        ${state.user ? esc(state.user.full_name) : 'Гость'}<br>
        <span style="color:var(--text-3)">${esc(paymentMode)}</span>
      </div>
    </div>`;
}

function updateBell() {
  const active = state.activeOrders.filter((o) => ['ready', 'in_locker'].includes(o.status)).length;
  el.bell.querySelector('.badge-dot')?.remove();
  if (active) {
    const dot = document.createElement('span');
    dot.className = 'badge-dot';
    dot.textContent = String(active);
    el.bell.appendChild(dot);
  }
}

/* ------------------------------- Рендер ---------------------------------- */
async function render() {
  closeSheet();
  const { path, query } = parseHash();
  const match = matchRoute(path);

  if (!match) {
    el.content.innerHTML = `
      <div class="empty">
        <div class="empty__emoji">🧭</div>
        <div class="empty__title">Страница не найдена</div>
        <button class="btn btn--sm mt-8" onclick="location.hash='#/'">На главную</button>
      </div>`;
    return;
  }

  el.content.innerHTML = '<div class="skeleton" style="height:180px"></div>';

  let module;
  try {
    module = await match.loader();
  } catch {
    el.content.innerHTML = '<div class="empty"><div class="empty__title">Не удалось загрузить экран</div></div>';
    return;
  }

  const view = await module.default({ params: match.params, query, path });
  currentView = view;

  // защита маршрутов
  if (view.requiresAuth && !state.user) {
    toast('Сначала войдите в приложение');
    go('#/login');
    return;
  }
  if (view.roles && state.user && !view.roles.includes(state.user.role)) {
    toast('Недостаточно прав для этого раздела', 'err');
    go('#/');
    return;
  }

  el.title.textContent = view.title || 'РосПит';
  document.title = view.title ? `${view.title} · РосПит` : 'РосПит · Столовая РОСБИОТЕХ';
  el.shell.classList.toggle('shell--wide', !!view.wide);
  el.back.style.visibility = BACKABLE.includes(path) || path.startsWith('/pay') || path.startsWith('/order/')
    ? 'visible'
    : 'hidden';
  // у карточки блюда своя кнопка «назад» поверх фото
  if (path.startsWith('/dish/')) el.back.style.visibility = 'hidden';

  el.content.innerHTML = view.html || '';
  window.scrollTo(0, 0);

  // панель действия и навигация рисуются до mount — вью может менять кнопку по ходу
  renderNav(path);
  renderActionBar();
  updateBell();

  if (view.mount) {
    try {
      await view.mount(el.content, { params: match.params, query });
    } catch (err) {
      console.error(err);
      toast('Ошибка при загрузке экрана', 'err');
    }
  }

  // восстанавливаем прокрутку только после mount — до него список ещё пуст
  const remembered = scrollMemory.get(path);
  if (remembered) requestAnimationFrame(() => window.scrollTo(0, remembered));

  renderNav(path);
  updateBell();
}

function renderActionBar() {
  if (!currentView || !currentView.footer) {
    el.actionBar.innerHTML = '';
    el.actionBar.classList.remove('is-visible');
    return;
  }
  const html = currentView.footer();
  el.actionBar.innerHTML = html;
  el.actionBar.classList.toggle('is-visible', !!html);
}

el.actionBar.addEventListener('click', (event) => {
  const link = event.target.closest('[data-goto]');
  if (link) { go(link.dataset.goto); return; }
  if (currentView && currentView.onFooterClick) currentView.onFooterClick(event, el.content);
});

el.back.addEventListener('click', () => window.history.back());
el.bell.addEventListener('click', () => {
  const ready = state.activeOrders.find((o) => ['ready', 'in_locker'].includes(o.status));
  if (ready) { go(`#/order/${ready.id}`); return; }
  const active = state.activeOrders[0];
  if (active) { go(`#/order/${active.id}`); return; }
  toast('Новых уведомлений нет');
});

/* --------------------------- Реакция на состояние ------------------------- */
subscribe(() => {
  renderNav(parseHash().path);
  renderActionBar();
  updateBell();
});

window.addEventListener('hashchange', () => {
  // запоминаем, где был пользователь, до перерисовки на новый маршрут
  scrollMemory.set(previousPath, window.scrollY);
  previousPath = parseHash().path;
  render();
});

/* Подпись режима оплаты в боковом меню — по факту настроек сервера */
let paymentMode = '';
async function loadPaymentMode() {
  try {
    const cfg = await (await fetch('/api/payments/config')).json();
    paymentMode = cfg.demo ? 'Демо-режим оплаты' : '';
  } catch { paymentMode = ''; }
}

/* ------------------------------ Запуск ----------------------------------- */
(async function boot() {
  await Promise.all([loadUser(), loadPaymentMode()]);
  if (state.user) {
    await Promise.all([loadCart().catch(() => {}), loadActiveOrders().catch(() => {})]);
  }
  if (state.offline) {
    el.content.innerHTML = `
      <div class="empty">
        <div class="empty__emoji">📡</div>
        <div class="empty__title">Нет связи</div>
        <div class="small">Заказы и меню появятся, когда вернётся интернет. Вход сохранён.</div>
        <button class="btn btn--sm mt-8" onclick="location.reload()">Повторить</button>
      </div>`;
    window.addEventListener('online', () => window.location.reload(), { once: true });
    return;
  }
  if (!state.user && !window.location.hash.startsWith('#/login')) {
    window.location.hash = '#/login';
  }
  if (!window.location.hash) window.location.hash = '#/';
  await render();

  // фоновое обновление активных заказов — имитация push-уведомлений
  let readyShown = new Set();
  setInterval(async () => {
    if (!state.user || state.user.role !== 'student') return;
    try {
      const before = new Set(state.activeOrders.filter((o) => ['ready', 'in_locker'].includes(o.status)).map((o) => o.id));
      await loadActiveOrders();
      state.activeOrders
        .filter((o) => ['ready', 'in_locker'].includes(o.status) && !before.has(o.id) && !readyShown.has(o.id))
        .forEach((o) => {
          readyShown.add(o.id);
          toast(o.status === 'in_locker' && o.cell_number
            ? `📦 Заказ ${o.number} в ячейке №${o.cell_number}`
            : `🔔 Заказ ${o.number} готов к выдаче`, 'ok');
        });
    } catch { /* не мешаем пользователю сетевыми ошибками фонового опроса */ }
  }, 20000);
})();

/* Экранная клавиатура: плавающие нижние панели не должны закрывать поле ввода.
   Пока в текстовом поле фокус (на телефоне), панели прячем. */
const isTextField = (el) => el && (el.tagName === 'TEXTAREA'
  || (el.tagName === 'INPUT' && !['checkbox', 'radio', 'button', 'submit'].includes(el.type)));
document.addEventListener('focusin', (e) => {
  if (isTextField(e.target) && window.matchMedia('(max-width: 1023px)').matches) {
    document.body.classList.add('keyboard-open');
  }
});
document.addEventListener('focusout', () => {
  setTimeout(() => {
    if (!isTextField(document.activeElement)) document.body.classList.remove('keyboard-open');
  }, 60);
});

/* Обёртка Capacitor (APK): системная кнопка «Назад» Android.
   Сначала закрывает лист, потом шаг назад по истории, на первом экране — выход. */
const nativeApp = window.Capacitor?.Plugins?.App;
if (nativeApp && window.Capacitor.getPlatform?.() === 'android') {
  nativeApp.addListener('backButton', ({ canGoBack }) => {
    const sheet = document.querySelector('.sheet-host.is-open');
    if (sheet) { closeSheet(); return; }
    if (canGoBack && !location.hash.startsWith('#/login') && location.hash !== '#/') {
      window.history.back();
    } else {
      nativeApp.exitApp();
    }
  });
}

/* Service worker — офлайн-оболочка PWA */
if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* не критично */ });
  });
}
