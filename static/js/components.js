/* Переиспользуемые куски интерфейса. */
import api from './api.js';
import { state, cartQty, setCart } from './state.js';
import { esc, money, toast, openSheet, closeSheet, TAG_LABELS, vibrate } from './ui.js';

const CATEGORY_GRADIENTS = {
  combo: 'linear-gradient(135deg,#1f5bff,#4a86ff)',
  soups: 'linear-gradient(135deg,#d9641f,#f0913c)',
  hot: 'linear-gradient(135deg,#c33a34,#e4574c)',
  sides: 'linear-gradient(135deg,#2f9d63,#4cc38a)',
  salads: 'linear-gradient(135deg,#1f9179,#2fb894)',
  bakery: 'linear-gradient(135deg,#d29a12,#f0b429)',
  drinks: 'linear-gradient(135deg,#2792ab,#3fb8d4)',
  desserts: 'linear-gradient(135deg,#8f34a8,#b74cd4)',
};

export const dishGradient = (dish) => {
  const cat = state.categories.find((c) => c.id === dish.category_id);
  return CATEGORY_GRADIENTS[cat?.slug] || `linear-gradient(135deg,${cat?.color || '#2f6bff'},#4a86ff)`;
};

export const tagsHtml = (tags = []) =>
  tags.length
    ? `<div class="tag-row">${tags
        .map((t) => `<span class="tag tag--${esc(t)}">${esc(TAG_LABELS[t] || t)}</span>`)
        .join('')}</div>`
    : '';

/** Карточка блюда в списке меню. */
export function dishRow(dish) {
  const qty = cartQty(dish.id);
  const out = !dish.is_active || dish.stock_qty <= 0;
  return `
  <div class="dish ${out ? 'dish--out' : ''}" data-dish="${dish.id}">
    <div class="dish__thumb" style="background:${dishGradient(dish)}">${esc(dish.icon)}</div>
    <div class="dish__body">
      <div class="dish__name">${esc(dish.name)}</div>
      <div class="dish__meta">${dish.weight_g ? `${dish.weight_g} г · ` : ''}${dish.kcal} ккал${
        out ? ' · нет в наличии' : dish.stock_qty <= 5 ? ` · осталось ${dish.stock_qty}` : ''
      }</div>
      ${tagsHtml(dish.tags)}
      <div class="dish__price">${money(dish.price)}</div>
    </div>
    <div class="dish__side">
      ${
        out
          ? '<span class="tag">Стоп-лист</span>'
          : qty > 0
            ? `<div class="stepper" data-stepper="${dish.id}">
                 <button data-minus aria-label="Убрать одну порцию">−</button>
                 <span class="stepper__val">${qty}</span>
                 <button data-plus aria-label="Добавить порцию" ${qty >= dish.stock_qty ? 'disabled' : ''}>+</button>
               </div>`
            : `<button class="add-btn" data-add="${dish.id}" aria-label="Добавить в корзину">+</button>`
      }
    </div>
  </div>`;
}

/** Изменение количества с оптимистичным откликом. */
export async function changeQty(dishId, qty) {
  try {
    const cart = await api.put('/api/cart/items', { dish_id: dishId, qty });
    setCart(cart);
    vibrate();
    return true;
  } catch (err) {
    if (err.status === 401) {
      toast('Войдите, чтобы собрать заказ', 'err');
      window.location.hash = '#/login';
    } else {
      toast(err.message, 'err');
    }
    return false;
  }
}

/** Обработчик кликов по спискам блюд — вешается один раз на контейнер. */
export function bindDishList(root, { onOpen } = {}) {
  root.addEventListener('click', async (event) => {
    const addBtn = event.target.closest('[data-add]');
    if (addBtn) {
      event.stopPropagation();
      await changeQty(Number(addBtn.dataset.add), 1);
      return;
    }
    const stepper = event.target.closest('[data-stepper]');
    if (stepper) {
      const id = Number(stepper.dataset.stepper);
      const current = cartQty(id);
      if (event.target.closest('[data-plus]')) {
        event.stopPropagation();
        await changeQty(id, current + 1);
        return;
      }
      if (event.target.closest('[data-minus]')) {
        event.stopPropagation();
        await changeQty(id, current - 1);
        return;
      }
    }
    const card = event.target.closest('[data-dish]');
    if (card && onOpen) onOpen(Number(card.dataset.dish));
  });
}

/** Подробная карточка блюда в нижнем листе. */
export function openDishSheet(dishId) {
  const dish = state.dishes.find((d) => d.id === dishId);
  if (!dish) return;
  const qty = cartQty(dish.id);
  const out = !dish.is_active || dish.stock_qty <= 0;

  openSheet(
    `<div class="stack">
      <div style="background:${dishGradient(dish)};border-radius:20px;height:150px;display:grid;place-items:center;font-size:76px">${esc(dish.icon)}</div>
      <div>
        <h2 class="section__title" style="font-size:22px;margin-bottom:6px">${esc(dish.name)}</h2>
        <div class="muted small">${dish.weight_g ? `${dish.weight_g} г · ` : ''}${dish.kcal} ккал</div>
        ${tagsHtml(dish.tags)}
      </div>
      ${dish.description ? `<p class="muted" style="margin:0;font-size:14px">${esc(dish.description)}</p>` : ''}
      <div class="grid-3">
        ${[['Белки', dish.protein], ['Жиры', dish.fat], ['Углеводы', dish.carbs]]
          .map(([label, value]) => `
            <div class="card center">
              <div class="small muted">${label}</div>
              <div class="bold" style="font-size:17px;margin-top:3px">${Number(value)} г</div>
            </div>`)
          .join('')}
      </div>
      <div class="hstack">
        <div>
          <div class="small muted">Цена</div>
          <div style="font-size:24px;font-weight:900">${money(dish.price)}</div>
        </div>
        <div class="spacer"></div>
        <div class="small muted">${out ? 'Нет в наличии' : `Осталось ${dish.stock_qty} порц.`}</div>
      </div>
      ${
        out
          ? '<button class="btn" disabled>Сегодня закончилось</button>'
          : `<div id="sheet-action"></div>`
      }
    </div>`,
    (sheet) => {
      const host = sheet.querySelector('#sheet-action');
      if (!host) return;

      const render = () => {
        const current = cartQty(dish.id);
        host.innerHTML = current
          ? `<div class="hstack" style="gap:12px">
               <div class="stepper" style="flex:0 0 auto">
                 <button data-m>−</button><span class="stepper__val">${current}</span>
                 <button data-p ${current >= dish.stock_qty ? 'disabled' : ''}>+</button>
               </div>
               <button class="btn" data-go-cart>В корзину · ${money(dish.price * current)}</button>
             </div>`
          : '<button class="btn" data-add-one>Добавить в корзину</button>';

        const add = host.querySelector('[data-add-one]');
        if (add) add.onclick = async () => { if (await changeQty(dish.id, 1)) render(); };
        const minus = host.querySelector('[data-m]');
        if (minus) minus.onclick = async () => { if (await changeQty(dish.id, current - 1)) render(); };
        const plus = host.querySelector('[data-p]');
        if (plus) plus.onclick = async () => { if (await changeQty(dish.id, current + 1)) render(); };
        const goCart = host.querySelector('[data-go-cart]');
        if (goCart) goCart.onclick = () => { closeSheet(); window.location.hash = '#/cart'; };
      };
      render();
    },
  );
  return qty;
}

/** Плашка статуса заказа. */
export const statusPill = (order) =>
  `<span class="status-pill status-pill--${esc(order.status)}">${esc(order.status_label)}</span>`;

/** Короткое перечисление состава заказа. */
export const orderSummary = (order) =>
  order.items.map((i) => `${esc(i.icon)} ${esc(i.name)}${i.qty > 1 ? ` ×${i.qty}` : ''}`).join(' · ');
