/* Корзина: состав заказа, бонусы, переход к выбору времени. */
import api from '../api.js';
import { state, loadCart, loadMenu, setCart, subscribe } from '../state.js';
import { esc, money, empty, toast, go, confirmSheet, plural } from '../ui.js';
import { dishGradient } from '../components.js';

export default async function cartView() {
  return {
    title: 'Корзина',
    requiresAuth: true,
    html: '<div class="stack" id="cart-body"></div>',

    async mount(root) {
      await Promise.all([loadMenu(), loadCart()]);
      const body = root.querySelector('#cart-body');

      const render = () => {
        const { items, count, subtotal, bonus_available: bonus, max_bonus_applicable: maxBonus } = state.cart;

        if (!count) {
          body.innerHTML = empty(
            '🛒',
            'Корзина пуста',
            'Загляните в меню — там 50+ позиций из столовой',
            '<button class="btn btn--sm mt-8" data-goto="#/menu">Открыть меню</button>',
          );
          return;
        }

        body.innerHTML = `
          <section class="section">
            <div class="section__head">
              <h2 class="section__title">Ваш заказ</h2>
              <button class="section__link" data-clear>Очистить</button>
            </div>
            <div class="dish-list">
              ${items
                .map((item) => {
                  const dish = state.dishes.find((d) => d.id === item.dish_id) || {
                    category_id: 0, icon: item.icon,
                  };
                  return `
                  <div class="dish">
                    <div class="dish__thumb" style="background:${dishGradient(dish)}">${esc(item.icon)}</div>
                    <div class="dish__body">
                      <div class="dish__name">${esc(item.name)}</div>
                      <div class="dish__meta">${money(item.price)} за порцию</div>
                      <div class="dish__price">${money(item.line_total)}</div>
                    </div>
                    <div class="dish__side">
                      <div class="stepper" data-id="${item.dish_id}">
                        <button data-minus aria-label="Убрать">−</button>
                        <span class="stepper__val">${item.qty}</span>
                        <button data-plus aria-label="Добавить" ${item.qty >= item.stock_qty ? 'disabled' : ''}>+</button>
                      </div>
                    </div>
                  </div>`;
                })
                .join('')}
            </div>
          </section>

          <section class="section">
            <div class="rows">
              <div class="row">
                <span class="row__label">${count} ${plural(count, 'позиция', 'позиции', 'позиций')}</span>
                <span class="bold">${money(subtotal)}</span>
              </div>
              ${
                Number(bonus) > 0
                  ? `<div class="row">
                       <span class="row__label">Доступно бонусов</span>
                       <span class="bold" style="color:var(--green)">${money(bonus)}</span>
                     </div>
                     <div class="small muted">
                       Списать можно до ${money(maxBonus)} — не больше 30% суммы заказа.
                       Выбор способа списания на следующем шаге.
                     </div>`
                  : ''
              }
              <div class="row row--total">
                <span class="row__label">Итого</span>
                <span>${money(subtotal)}</span>
              </div>
            </div>
          </section>

          <p class="small muted center" style="padding:0 12px">
            Заказ комплектуется к выбранному времени. Забрать можно по QR-коду без общей очереди.
          </p>`;

        body.querySelectorAll('[data-id]').forEach((stepper) => {
          const id = Number(stepper.dataset.id);
          const item = items.find((i) => i.dish_id === id);
          stepper.querySelector('[data-minus]').onclick = () => update(id, item.qty - 1);
          stepper.querySelector('[data-plus]').onclick = () => update(id, item.qty + 1);
        });

        const clear = body.querySelector('[data-clear]');
        if (clear) {
          clear.onclick = async () => {
            const ok = await confirmSheet({
              title: 'Очистить корзину?',
              text: 'Все выбранные блюда будут удалены.',
              confirmLabel: 'Очистить',
              danger: true,
            });
            if (!ok) return;
            setCart(await api.del('/api/cart'));
            toast('Корзина очищена');
          };
        }
      };

      const update = async (dishId, qty) => {
        try {
          setCart(await api.put('/api/cart/items', { dish_id: dishId, qty }));
        } catch (err) {
          toast(err.message, 'err');
        }
      };

      render();
      const unsubscribe = subscribe(() => {
        if (!document.body.contains(body)) { unsubscribe(); return; }
        render();
      });

      body.addEventListener('click', (e) => {
        const link = e.target.closest('[data-goto]');
        if (link) go(link.dataset.goto);
      });
    },

    footer() {
      if (!state.cart.count) return '';
      return `<button class="btn" data-goto="#/checkout">
                Выбрать время · ${money(state.cart.subtotal)}
              </button>`;
    },
  };
}
