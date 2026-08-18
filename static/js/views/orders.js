/* История заказов. */
import api from '../api.js';
import { esc, money, empty, go, dateLabel, skeletonList, toast } from '../ui.js';
import { statusPill, orderSummary } from '../components.js';

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
          <button class="section" data-goto="#/order/${order.id}" style="text-align:left;width:100%">
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
                  : order.status === 'ready'
                    ? '<span class="status-pill status-pill--ready">Показать QR →</span>'
                    : '<span class="small muted">Подробнее →</span>'
              }
            </div>
          </button>`;

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

      host.addEventListener('click', (e) => {
        const link = e.target.closest('[data-goto]');
        if (link) go(link.dataset.goto);
      });
    },
  };
}
