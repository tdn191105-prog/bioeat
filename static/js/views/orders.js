/* История заказов. */
import api from '../api.js';
import { loadCart } from '../state.js';
import { esc, money, empty, go, dateLabel, skeletonList, toast } from '../ui.js';
import { statusPill, orderSummary, starsHtml } from '../components.js';

/** Кладёт состав прошлого заказа в корзину и честно рассказывает, что пропущено. */
export async function repeatOrder(orderId, button) {
  const label = button ? button.textContent : '';
  if (button) { button.disabled = true; button.textContent = 'Добавляем…'; }
  try {
    const result = await api.post(`/api/orders/${orderId}/repeat`);
    await loadCart();
    if (!result.added.length) {
      toast('Ни одну позицию из заказа сегодня взять нельзя', 'err');
    } else if (result.skipped.length) {
      const missed = result.skipped.map((s) => `${s.name} (${s.reason})`).join('; ');
      toast(`Добавлено ${result.added.length}. Пропущено: ${missed}`, 'err');
    } else {
      toast(`Заказ повторён · ${result.added.length} поз. в корзине`, 'ok');
    }
    return result;
  } catch (err) {
    toast(err.message, 'err');
    return null;
  } finally {
    if (button) { button.disabled = false; button.textContent = label; }
  }
}

export default async function ordersView() {
  return {
    title: 'Мои заказы',
    requiresAuth: true,
    html: `<div class="stack" id="orders">${skeletonList(3, 120)}</div>`,

    async mount(root) {
      const host = root.querySelector('#orders');
      let orders = [];
      try {
        orders = await api.get('/api/orders');
      } catch (err) {
        toast(err.message, 'err');
      }

      if (!orders.length) {
        host.innerHTML = empty(
          '🧾',
          'Заказов пока нет',
          'Соберите первый заказ — это займёт минуту',
          '<button class="btn btn--sm mt-8" data-goto="#/menu">Открыть меню</button>',
        );
      } else {
        const active = orders.filter((o) => !['issued', 'cancelled'].includes(o.status));
        const past = orders.filter((o) => ['issued', 'cancelled'].includes(o.status));

        const card = (order) => `
        <section class="section">
          <div data-goto="#/order/${order.id}" style="text-align:left;width:100%;cursor:pointer">
            <div class="hstack" style="margin-bottom:10px">
              <div>
                <div class="bold" style="font-size:17px">${esc(order.number)}</div>
                <div class="small muted">${dateLabel(order.pickup_date)} · ${esc(order.slot_label)}</div>
              </div>
              <div class="spacer"></div>
              ${statusPill(order)}
            </div>
            <div class="small muted" style="line-height:1.5">${orderSummary(order)}</div>
            <div class="hstack mt-8">
              <span class="bold" style="font-size:17px">${money(order.total)}</span>
              <div class="spacer"></div>
              ${
                order.status === 'created'
                  ? '<span class="status-pill status-pill--created">Оплатить →</span>'
                  : ['ready', 'in_locker'].includes(order.status)
                    ? '<span class="status-pill status-pill--ready">Показать QR →</span>'
                    : '<span class="small muted">Подробнее →</span>'
              }
            </div>
          </div>
          ${
            order.status === 'issued'
              ? order.review
                ? `<div class="small muted mt-8">Ваша оценка: ${starsHtml(order.review.rating)}</div>`
                : `<div class="small bold mt-8">Как вам заказ?</div>
                   <div class="rate-row" aria-label="Оценить заказ">${[1, 2, 3, 4, 5]
                     .map((n) => `<button type="button" data-rate="${n}" data-order="${order.id}" aria-label="${n} из 5">★</button>`)
                     .join('')}</div>`
              : ''
          }
          ${
            ['issued', 'cancelled'].includes(order.status)
              ? `<button class="btn btn--ghost btn--sm mt-8" data-repeat="${order.id}">↻ Повторить заказ</button>`
              : ''
          }
        </section>`;

        host.innerHTML = `
          ${
            active.length
              ? `<div class="small bold muted" style="padding:4px 6px;text-transform:uppercase;letter-spacing:.6px">Активные</div>
                 ${active.map(card).join('')}`
              : ''
          }
          ${
            past.length
              ? `<div class="small bold muted" style="padding:14px 6px 4px;text-transform:uppercase;letter-spacing:.6px">История</div>
                 ${past.map(card).join('')}`
              : ''
          }`;
      }

      host.addEventListener('click', async (e) => {
        const rate = e.target.closest('[data-rate]');
        if (rate) {
          e.stopPropagation();
          go(`#/order/${rate.dataset.order}?rate=${rate.dataset.rate}`);
          return;
        }
        const repeat = e.target.closest('[data-repeat]');
        if (repeat) {
          e.stopPropagation();
          if (await repeatOrder(Number(repeat.dataset.repeat), repeat)) go('#/cart');
          return;
        }
        const link = e.target.closest('[data-goto]');
        if (link) go(link.dataset.goto);
      });
    },
  };
}
