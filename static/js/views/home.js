/* Главный экран — витрина сервисов в стиле приложения РОСБИОТЕХ. */
import api from '../api.js';
import { state, loadMenu, loadActiveOrders, isStaff, isAdmin } from '../state.js';
import { esc, money, plural, go, dateLabel, skeletonList } from '../ui.js';
import { dishRow, bindDishList } from '../components.js';

const NEWS = [
  {
    emoji: '🥗',
    title: 'Новое ПП-меню на каждый день',
    text: 'Шеф-повар обновил линейку блюд с пониженной калорийностью — ищите метку «ПП».',
  },
  {
    emoji: '⚡',
    title: 'Экспресс-выдача работает без очереди',
    text: 'Забирайте предзаказ за 15 секунд в отдельном окне по QR-коду из приложения.',
  },
  {
    emoji: '🎓',
    title: 'Кэшбэк 5% для обучающихся',
    text: 'Бонусы начисляются с каждого оплаченного заказа и списываются на следующий.',
  },
];

function bannersHtml() {
  const order = state.activeOrders[0];
  const banners = [];

  if (order) {
    const ready = ['ready', 'in_locker'].includes(order.status);
    banners.push(`
      <button class="banner ${ready ? 'banner--green' : ''}" data-goto="#/order/${order.id}">
        <span class="banner__pill">${ready ? 'Готов к выдаче' : esc(order.status_label)}</span>
        <span class="banner__emoji">${ready ? '🔔' : '🍱'}</span>
        <span class="banner__title">Заказ ${esc(order.number)}</span>
        <span class="banner__text">${esc(order.slot_label)} · ${dateLabel(order.pickup_date)}. Нажмите, чтобы открыть QR-код.</span>
      </button>`);
  }

  banners.push(`
    <button class="banner" data-goto="#/menu">
      <span class="banner__pill">Твой ход!</span>
      <span class="banner__emoji">🍽</span>
      <span class="banner__title">Обед без очереди</span>
      <span class="banner__text">Соберите заказ заранее и заберите его на перемене за 15 секунд.</span>
    </button>`);

  banners.push(`
    <button class="banner banner--purple" data-goto="#/profile">
      <span class="banner__pill">Бонусы</span>
      <span class="banner__emoji">💜</span>
      <span class="banner__title">Кэшбэк 5% с каждого заказа</span>
      <span class="banner__text">Списывайте бонусами до 30% суммы следующего чека.</span>
    </button>`);

  banners.push(`
    <button class="banner banner--orange" data-goto="#/menu?tag=pp">
      <span class="banner__pill">Питание</span>
      <span class="banner__emoji">🥑</span>
      <span class="banner__title">ПП и вегетарианское меню</span>
      <span class="banner__text">Фильтры по диете: без лактозы, без глютена, постное.</span>
    </button>`);

  return banners.join('');
}

function tilesHtml() {
  const count = state.cart.count;
  const tiles = [
    {
      href: '#/menu',
      title: 'Меню столовой',
      sub: `${state.dishes.length} ${plural(state.dishes.length, 'позиция', 'позиции', 'позиций')} сегодня`,
      emoji: '🍲',
      bg: 'linear-gradient(140deg,#3b6dfa,#5b8cff)',
      tall: true,
    },
    {
      href: '#/cart',
      title: 'Корзина',
      emoji: '🛒',
      bg: 'linear-gradient(140deg,#2792ab,#3fb8d4)',
      badge: count ? String(count) : '',
    },
    {
      href: '#/orders',
      title: 'Мои заказы',
      emoji: '🧾',
      bg: 'linear-gradient(140deg,#1f9179,#2fb894)',
    },
    {
      href: '#/menu?category=combo',
      title: 'Комбо-обеды',
      emoji: '🍱',
      bg: 'linear-gradient(140deg,#2f9d63,#4cc38a)',
    },
    {
      href: '#/orders',
      title: 'QR выдачи',
      emoji: '🎫',
      bg: 'linear-gradient(140deg,#6b47d6,#8b6cf7)',
    },
    {
      href: '#/profile',
      title: 'Профиль',
      emoji: '👤',
      bg: 'linear-gradient(140deg,#a83fc4,#c46bdb)',
    },
  ];

  if (isStaff()) {
    tiles.push({
      href: '#/operator',
      title: 'Кабинет столовой',
      emoji: '👨‍🍳',
      bg: 'linear-gradient(140deg,#d9641f,#f0913c)',
    });
  }
  if (isAdmin()) {
    tiles.push({
      href: '#/admin',
      title: 'Админ-панель',
      emoji: '⚙️',
      bg: 'linear-gradient(140deg,#d29a12,#f0b429)',
    });
  }

  return tiles
    .map(
      (t) => `
      <button class="tile ${t.tall ? 'tile--tall' : ''}" style="background:${t.bg}" data-goto="${t.href}">
        ${t.badge ? `<span class="tile__badge">${esc(t.badge)}</span>` : ''}
        <span class="tile__title">${esc(t.title)}</span>
        ${t.sub ? `<span class="tile__sub">${esc(t.sub)}</span>` : ''}
        <span class="tile__emoji">${t.emoji}</span>
      </button>`,
    )
    .join('');
}

export default async function homeView() {
  const name = state.user ? state.user.full_name.split(' ')[0] : 'гость';

  return {
    title: 'Главная',
    html: `
      <section class="section">
        <div class="section__head">
          <h2 class="section__title">Для вас</h2>
        </div>
        <div class="carousel" id="banners">${skeletonList(1, 168)}</div>
        <div class="dots" id="banner-dots"></div>
      </section>

      <div class="stats-row" id="home-stats">
        <div class="skeleton" style="height:108px"></div>
        <div class="skeleton" style="height:108px"></div>
      </div>

      <section class="section">
        <div class="section__head">
          <h2 class="section__title">Сервисы</h2>
        </div>
        <div class="tiles" id="tiles"></div>
        <button class="wide-btn" data-goto="#/menu">Полный список</button>
      </section>

      <section class="section">
        <div class="section__head">
          <h2 class="section__title">Хиты недели</h2>
          <button class="section__link" data-goto="#/menu">Всё меню</button>
        </div>
        <div class="dish-list" id="hits">${skeletonList(3)}</div>
      </section>

      <section class="section">
        <div class="section__head">
          <h2 class="section__title">Новости</h2>
        </div>
        <div class="carousel">
          ${NEWS.map(
            (n) => `
            <div class="card" style="min-height:150px;display:flex;flex-direction:column;gap:8px">
              <div style="font-size:34px">${n.emoji}</div>
              <div class="bold">${esc(n.title)}</div>
              <div class="small muted">${esc(n.text)}</div>
            </div>`,
          ).join('')}
        </div>
      </section>

      <p class="center small muted" style="padding:0 16px" id="home-note">
        Привет, ${esc(name)}!
      </p>
    `,

    async mount(root) {
      await Promise.all([loadMenu(), loadActiveOrders().catch(() => [])]);

      // пока грузились данные, пользователь мог уйти с главной — тогда ничего не рисуем
      const banners = root.querySelector('#banners');
      if (!banners) return;
      api.get('/api/payments/config').then((cfg) => {
        const note = root.querySelector('#home-note');
        if (note && cfg.demo) {
          note.textContent = `Привет, ${name}. Это демонстрационная версия — оплата проходит в тестовом режиме и не обращается к реальным банковским системам.`;
        }
      }).catch(() => {});
      banners.innerHTML = bannersHtml();

      const dots = root.querySelector('#banner-dots');
      const renderDots = () => {
        const total = banners.children.length;
        const index = Math.round(banners.scrollLeft / (banners.scrollWidth / total));
        dots.innerHTML = Array.from(
          { length: total },
          (_, i) => `<span class="dot ${i === index ? 'is-active' : ''}"></span>`,
        ).join('');
      };
      renderDots();
      banners.addEventListener('scroll', renderDots, { passive: true });

      const order = state.activeOrders[0];
      root.querySelector('#home-stats').innerHTML = `
        <button class="stat" data-goto="${order ? `#/order/${order.id}` : '#/menu'}">
          <div class="stat__label">${order ? 'Текущий заказ' : 'Заказ на сегодня'}</div>
          <div class="stat__icon">${order ? '🍱' : '⏱'}</div>
          <div>
            <div class="stat__value ${order && ['ready', 'in_locker'].includes(order.status) ? 'stat__value--green' : ''}">
              ${order ? esc(order.number) : '—'}
            </div>
            <div class="stat__sub">${order ? esc(order.status_label) : 'Ещё не оформлен'}</div>
          </div>
        </button>
        <button class="stat" data-goto="#/profile">
          <div class="stat__label">Бонусный баланс</div>
          <div class="stat__icon">🎁</div>
          <div>
            <div class="stat__value stat__value--green">${
              state.user ? money(state.user.bonus_balance) : '—'
            }</div>
            <div class="stat__sub">Кэшбэк 5% с каждого заказа</div>
          </div>
        </button>`;

      root.querySelector('#tiles').innerHTML = tilesHtml();

      // «Хиты недели» — по фактическим продажам за неделю; сервер сам
      // откатится на тег hit, если продаж ещё не было
      const hitsHost = root.querySelector('#hits');
      let hits = [];
      try {
        hits = await api.get('/api/dishes/popular?limit=4');
      } catch {
        hits = state.dishes.filter((d) => (d.tags || []).includes('hit')).slice(0, 4);
      }
      hitsHost.innerHTML = (hits.length ? hits : state.dishes.slice(0, 4)).map(dishRow).join('');
      bindDishList(hitsHost, { onOpen: (id) => go(`#/dish/${id}`) });

      root.addEventListener('click', (event) => {
        const target = event.target.closest('[data-goto]');
        if (target) go(target.dataset.goto);
      });
    },
  };
}
