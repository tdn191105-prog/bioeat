/* Мелкие помощники интерфейса: экранирование, форматирование, тосты, листы. */

export const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[ch]);

export const money = (value) => {
  const n = Number(value || 0);
  const rounded = Math.round(n * 100) / 100;
  const text = Number.isInteger(rounded)
    ? rounded.toLocaleString('ru-RU')
    : rounded.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${text} ₽`;
};

export const plural = (n, one, few, many) => {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return many;
  if (last > 1 && last < 5) return few;
  if (last === 1) return one;
  return many;
};

export const dateLabel = (iso) => {
  const today = new Date();
  const target = new Date(`${iso}T00:00:00`);
  const diff = Math.round((target - new Date(today.toDateString())) / 86400000);
  if (diff === 0) return 'сегодня';
  if (diff === 1) return 'завтра';
  if (diff === 2) return 'послезавтра';
  return target.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
};

export const dateTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
  return d.toLocaleString('ru-RU', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  });
};

export const isoDate = (offsetDays = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export const TAG_LABELS = {
  pp: 'ПП',
  veg: 'Вегетарианское',
  no_lactose: 'Без лактозы',
  no_gluten: 'Без глютена',
  spicy: 'Острое',
  hit: 'Хит',
};

/* --------------------------------- Тосты --------------------------------- */
let toastHost;

export function toast(message, kind = '') {
  if (!toastHost) {
    toastHost = document.createElement('div');
    toastHost.className = 'toast-host';
    document.body.appendChild(toastHost);
  }
  const el = document.createElement('div');
  el.className = `toast ${kind ? `toast--${kind}` : ''}`;
  const icon = kind === 'ok' ? '✓' : kind === 'err' ? '✕' : 'ℹ';
  el.innerHTML = `<span>${icon}</span><span>${esc(message)}</span>`;
  toastHost.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .2s, transform .2s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(8px)';
    setTimeout(() => el.remove(), 220);
  }, 2600);
}

/* ------------------------------ Нижний лист ------------------------------ */
let sheetHost;

export function openSheet(html, onMount) {
  if (!sheetHost) {
    sheetHost = document.createElement('div');
    sheetHost.className = 'sheet-host';
    sheetHost.innerHTML = '<div class="sheet-host__bg"></div><div class="sheet"></div>';
    document.body.appendChild(sheetHost);
    sheetHost.querySelector('.sheet-host__bg').addEventListener('click', closeSheet);
  }
  const sheet = sheetHost.querySelector('.sheet');
  sheet.innerHTML = `<div class="sheet__grip"></div>${html}`;
  sheet.scrollTop = 0;
  sheetHost.classList.add('is-open');
  document.body.style.overflow = 'hidden';
  if (onMount) onMount(sheet);
  return sheet;
}

export function closeSheet() {
  if (!sheetHost) return;
  sheetHost.classList.remove('is-open');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeSheet();
});

/* ------------------------------ Подтверждение ---------------------------- */
export function confirmSheet({ title, text, confirmLabel = 'Подтвердить', danger = false }) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeSheet();
      resolve(value);
    };
    openSheet(
      `<div class="stack">
        <h2 class="section__title" style="font-size:21px">${esc(title)}</h2>
        <p class="muted" style="margin:0">${esc(text)}</p>
        <button class="btn ${danger ? 'btn--danger' : ''}" data-yes>${esc(confirmLabel)}</button>
        <button class="btn btn--ghost" data-no>Отмена</button>
      </div>`,
      (sheet) => {
        sheet.querySelector('[data-yes]').onclick = () => finish(true);
        sheet.querySelector('[data-no]').onclick = () => finish(false);
      },
    );
  });
}

/* ------------------------------ Заглушки --------------------------------- */
export const empty = (emoji, title, text = '', action = '') => `
  <div class="empty">
    <div class="empty__emoji">${emoji}</div>
    <div class="empty__title">${esc(title)}</div>
    ${text ? `<div class="small">${esc(text)}</div>` : ''}
    ${action}
  </div>`;

export const skeletonList = (count = 4, height = 92) =>
  Array.from({ length: count }, () => `<div class="skeleton" style="height:${height}px"></div>`).join('');

/* -------------------------- Прочие утилиты ------------------------------- */
export function debounce(fn, delay = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

export const go = (hash) => { window.location.hash = hash; };

export function vibrate(ms = 8) {
  if (navigator.vibrate) { try { navigator.vibrate(ms); } catch { /* нет вибромотора */ } }
}
