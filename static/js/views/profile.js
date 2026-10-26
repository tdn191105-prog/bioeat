/* Профиль пользователя. */
import { state, logout, isStaff, isAdmin } from '../state.js';
import { esc, money, go, toast, confirmSheet, openSheet, closeSheet } from '../ui.js';
import { mountReviewForm } from '../components.js';

const ROLE_LABELS = { student: 'Обучающийся', operator: 'Оператор столовой', admin: 'Администратор' };

export default async function profileView() {
  const user = state.user;

  return {
    title: 'Профиль',
    requiresAuth: true,
    html: `
      <div class="stack">
        <section class="section center">
          <div style="width:78px;height:78px;border-radius:26px;margin:0 auto;
                      background:linear-gradient(135deg,#1f5bff,#4a86ff);display:grid;place-items:center;
                      font-size:32px;font-weight:800">
            ${esc((user.full_name || '?').trim().charAt(0).toUpperCase())}
          </div>
          <div class="bold mt-16" style="font-size:20px">${esc(user.full_name)}</div>
          <div class="small muted">${esc(user.email)}</div>
          <div class="mt-8">
            <span class="status-pill">${esc(ROLE_LABELS[user.role] || user.role)}</span>
            ${user.group_name ? `<span class="status-pill">${esc(user.group_name)}</span>` : ''}
          </div>
        </section>

        <section class="section">
          <div class="hstack">
            <div>
              <div class="small muted">Бонусный баланс</div>
              <div style="font-size:30px;font-weight:900;color:var(--green)">${money(user.bonus_balance)}</div>
              <div class="small muted">5% кэшбэка с каждого оплаченного заказа</div>
            </div>
            <div class="spacer"></div>
            <div style="font-size:44px">🎁</div>
          </div>
        </section>

        <section class="section">
          <div class="section__head"><h2 class="section__title">Разделы</h2></div>
          <div class="stack stack--sm">
            <button class="option" data-goto="#/orders">
              <span class="option__ico">🧾</span>
              <span class="option__body"><span class="option__title">Мои заказы</span>
              <span class="option__sub">История и активные предзаказы</span></span>
              <span class="option__right">→</span>
            </button>
            <button class="option" data-feedback>
              <span class="option__ico">⭐</span>
              <span class="option__body"><span class="option__title">Отзыв о столовой</span>
              <span class="option__sub">Что нравится и что улучшить — читает столовая</span></span>
              <span class="option__right">→</span>
            </button>
            <button class="option" data-goto="#/menu">
              <span class="option__ico">🍲</span>
              <span class="option__body"><span class="option__title">Меню столовой</span>
              <span class="option__sub">Блюда, состав, БЖУ и фильтры по диете</span></span>
              <span class="option__right">→</span>
            </button>
            ${
              isStaff()
                ? `<button class="option" data-goto="#/operator">
                     <span class="option__ico">👨‍🍳</span>
                     <span class="option__body"><span class="option__title">Кабинет столовой</span>
                     <span class="option__sub">Заказы по переменам, сборка и выдача</span></span>
                     <span class="option__right">→</span>
                   </button>`
                : ''
            }
            ${
              isStaff()
                ? `<button class="option" data-goto="#/reviews">
                     <span class="option__ico">💬</span>
                     <span class="option__body"><span class="option__title">Отзывы</span>
                     <span class="option__sub">Оценки, ответы и модерация</span></span>
                     <span class="option__right">→</span>
                   </button>`
                : ''
            }
            ${
              isAdmin()
                ? `<button class="option" data-goto="#/admin">
                     <span class="option__ico">⚙️</span>
                     <span class="option__body"><span class="option__title">Админ-панель</span>
                     <span class="option__sub">Меню, окна выдачи, отчёты, сотрудники</span></span>
                     <span class="option__right">→</span>
                   </button>`
                : ''
            }
          </div>
        </section>

        <section class="section">
          <div class="stack stack--sm small muted">
            <div class="bold" style="color:var(--text)">О приложении</div>
            <img src="/static/icons/logo.svg" alt="РосПит" width="148" height="28" style="margin:4px 0">
            <div>РосПит — предзаказ питания в столовой РОСБИОТЕХ. Версия 1.1.</div>
            <div>Оплата работает в демонстрационном режиме: обращений к банковским системам и СБП не происходит.</div>
          </div>
        </section>

        <button class="btn btn--danger" id="logout">Выйти из аккаунта</button>
      </div>`,

    async mount(root) {
      root.querySelectorAll('[data-goto]').forEach((el) => {
        el.onclick = () => go(el.dataset.goto);
      });
      root.querySelector('[data-feedback]').onclick = () => {
        openSheet(
          `<div class="stack">
             <h2 class="section__title" style="font-size:21px">Отзыв о столовой</h2>
             <div data-form></div>
           </div>`,
          (sheet) => mountReviewForm(sheet.querySelector('[data-form]'), {
            onSaved: () => closeSheet(),
          }),
        );
      };
      root.querySelector('#logout').onclick = async () => {
        const ok = await confirmSheet({
          title: 'Выйти из аккаунта?',
          text: 'Корзина сохранится на сервере — она вернётся при следующем входе.',
          confirmLabel: 'Выйти',
          danger: true,
        });
        if (!ok) return;
        await logout();
        toast('Вы вышли из аккаунта');
        go('#/login');
      };
    },
  };
}
