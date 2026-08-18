/* Карточка заказа: QR-код выдачи и трекер статуса. */
import api from '../api.js';
import { loadActiveOrders } from '../state.js';
import { repeatOrder } from './orders.js';
import { esc, money, toast, go, dateLabel, dateTime, confirmSheet } from '../ui.js';
import { itemThumb } from '../components.js';

const STEPS = [
  { key: 'paid', title: 'Оплачен', icon: '✓' },
  { key: 'accepted', title: 'Принят кухней', icon: '👨‍🍳' },
  { key: 'cooking', title: 'Комплектуется', icon: '🍳' },
  { key: 'ready', title: 'Готов к выдаче', icon: '🔔' },
  { key: 'issued', title: 'Выдан', icon: '🎉' },
];
const ORDER_FLOW = STEPS.map((s) => s.key);

export default async function orderView(ctx) {
  const orderId = Number(ctx.params.id);
  let order;
  try {
    order = await api.get(`/api/orders/${orderId}`);
  } catch (err) {
    toast(err.message, 'err');
    return { title: 'Заказ', html: '', mount: () => go('#/orders') };
  }

  const showQr = ['paid', 'accepted', 'cooking', 'ready'].includes(order.status);

  const trackerHtml = (current) => {
    const index = ORDER_FLOW.indexOf(current);
    return STEPS.map((step, i) => {
      const done = index > i;
      const isCurrent = index === i;
      const stamp =
        step.key === 'paid' ? order.paid_at
        : step.key === 'ready' ? order.ready_at
        : step.key === 'issued' ? order.issued_at
        : null;
      return `
        <div class="track-step ${done ? 'is-done' : ''} ${isCurrent ? 'is-current' : ''}">
          <div class="track-dot">${done ? '✓' : step.icon}</div>
          <div>
            <div class="track-step__title">${esc(step.title)}</div>
            <div class="track-step__sub">${stamp ? dateTime(stamp) : isCurrent ? 'сейчас' : ''}</div>
          </div>
        </div>`;
    }).join('');
  };

  return {
    title: `Заказ ${order.number}`,
    requiresAuth: true,
    html: `
      <div class="stack" id="order-body"></div>`,

    async mount(root) {
      const body = root.querySelector('#order-body');

      const render = () => {
        const cancellable = ['created', 'paid', 'accepted'].includes(order.status);
        body.innerHTML = `
          ${
            order.status === 'cancelled'
              ? `<section class="section center">
                   <div style="font-size:46px">🚫</div>
                   <div class="bold mt-8">Заказ отменён</div>
                   <div class="small muted">Бонусы и оплата возвращены</div>
                 </section>`
              : ''
          }

          ${
            showQr
              ? `<section class="section center">
                   <div class="small muted">Покажите код на выдаче</div>
                   <div class="qr-box mt-16" id="qr">
                     <img alt="QR-код заказа ${esc(order.number)}" src="/api/orders/${order.id}/qr.svg">
                   </div>
                   <div class="big-number mt-16">${esc(order.number)}</div>
                   <div class="small muted">${esc(order.pickup_point)}</div>
                   <div class="mt-16">
                     ${
                       order.status === 'ready'
                         ? '<span class="status-pill status-pill--ready">🔔 Заказ готов — можно забирать</span>'
                         : `<span class="status-pill status-pill--${esc(order.status)}">${esc(order.status_label)}</span>`
                     }
                   </div>
                 </section>`
              : order.status === 'created'
                ? `<section class="section center">
                     <div style="font-size:46px">⏳</div>
                     <div class="bold mt-8">Заказ ждёт оплаты</div>
                     <div class="small muted">QR-код появится сразу после оплаты</div>
                     <button class="btn mt-16" data-goto="#/pay/${order.id}">Оплатить ${money(order.total)}</button>
                   </section>`
                : ''
          }

          <section class="section">
            <div class="section__head"><h2 class="section__title">Когда и где</h2></div>
            <div class="rows">
              <div class="row"><span class="row__label">Дата</span><span class="bold">${dateLabel(order.pickup_date)}</span></div>
              <div class="row"><span class="row__label">Окно выдачи</span><span class="bold nowrap">${esc(order.slot_label)}</span></div>
              <div class="row"><span class="row__label">Точка</span><span class="bold" style="text-align:right">${esc(order.pickup_point)}</span></div>
              ${order.comment ? `<div class="row"><span class="row__label">Комментарий</span><span style="text-align:right">${esc(order.comment)}</span></div>` : ''}
            </div>
          </section>

          ${
            order.status !== 'cancelled'
              ? `<section class="section">
                   <div class="section__head"><h2 class="section__title">Статус</h2></div>
                   <div class="tracker">${trackerHtml(order.status)}</div>
                 </section>`
              : ''
          }

          <section class="section">
            <div class="section__head"><h2 class="section__title">Состав</h2></div>
            <div class="rows">
              ${order.items
                .map(
                  (i) => `<div class="row">
                            <span class="row__label hstack" style="gap:10px">
                              ${itemThumb(i)}
                              <span>${esc(i.name)} ×${i.qty}</span>
                            </span>
                            <span class="bold nowrap">${money(i.price * i.qty)}</span>
                          </div>`,
                )
                .join('')}
              ${Number(order.bonus_used) > 0 ? `<div class="row"><span class="row__label">Списано бонусов</span><span style="color:var(--green)">−${money(order.bonus_used)}</span></div>` : ''}
              <div class="row row--total"><span class="row__label">Итого</span><span>${money(order.total)}</span></div>
              ${Number(order.bonus_earned) > 0 && order.status !== 'created' ? `<div class="small muted">Начислено ${money(order.bonus_earned)} бонусами</div>` : ''}
            </div>
          </section>

          ${
            ['issued', 'cancelled'].includes(order.status)
              ? '<button class="btn" data-repeat>↻ Повторить заказ</button>'
              : ''
          }
          ${cancellable ? '<button class="btn btn--danger" data-cancel>Отменить заказ</button>' : ''}
          <button class="btn btn--ghost" data-goto="#/orders">Все мои заказы</button>`;

        const repeat = body.querySelector('[data-repeat]');
        if (repeat) {
          repeat.onclick = async () => {
            if (await repeatOrder(order.id, repeat)) go('#/cart');
          };
        }

        const cancel = body.querySelector('[data-cancel]');
        if (cancel) {
          cancel.onclick = async () => {
            const ok = await confirmSheet({
              title: 'Отменить заказ?',
              text: 'Оплата и списанные бонусы вернутся на счёт, порции — в наличие столовой.',
              confirmLabel: 'Отменить заказ',
              danger: true,
            });
            if (!ok) return;
            try {
              order = await api.post(`/api/orders/${order.id}/cancel`);
              toast('Заказ отменён', 'ok');
              await loadActiveOrders().catch(() => []);
              render();
            } catch (err) {
              toast(err.message, 'err');
            }
          };
        }

        body.querySelectorAll('[data-goto]').forEach((el) => {
          el.onclick = () => go(el.dataset.goto);
        });
      };

      render();

      // мягкий поллинг статуса, пока заказ активен — имитирует push-уведомление
      let previous = order.status;
      const timer = setInterval(async () => {
        if (!document.body.contains(body)) { clearInterval(timer); return; }
        if (['issued', 'cancelled'].includes(order.status)) { clearInterval(timer); return; }
        try {
          const fresh = await api.get(`/api/orders/${order.id}`, { silent: true });
          if (fresh.status !== previous) {
            order = fresh;
            previous = fresh.status;
            render();
            if (fresh.status === 'ready') toast('🔔 Заказ готов к выдаче!', 'ok');
            if (fresh.status === 'issued') toast('Заказ выдан. Приятного аппетита!', 'ok');
            await loadActiveOrders().catch(() => []);
          }
        } catch { /* сеть отвалилась — попробуем на следующем тике */ }
      }, 5000);
    },
  };
}
