/* Карточка заказа: QR-код выдачи и трекер статуса. */
import api from '../api.js';
import { loadActiveOrders } from '../state.js';
import { repeatOrder } from './orders.js';
import { esc, money, toast, go, dateLabel, dateTime, confirmSheet } from '../ui.js';
import { itemThumb, mountReviewForm, reviewCard } from '../components.js';

/* Шаги «принят» и «комплектуется» у кухни необязательны, поэтому для студента
   они сведены в один: «Кухня собирает». Для постамата третий шаг — ячейка. */
const STEP_OF = { paid: 0, accepted: 1, cooking: 1, ready: 2, in_locker: 2, issued: 3 };
const isLocker = (order) => order.status === 'in_locker' || !!order.cell_number;
const lockerText = (order) =>
  `Заказ в ячейке №${order.cell_number}${order.locker_name ? `, ${order.locker_name}` : ''}`;

export default async function orderView(ctx) {
  const orderId = Number(ctx.params.id);
  let order;
  try {
    order = await api.get(`/api/orders/${orderId}`);
  } catch (err) {
    toast(err.message, 'err');
    return { title: 'Заказ', html: '', mount: () => go('#/orders') };
  }

  const trackerHtml = (current) => {
    const index = STEP_OF[current] ?? -1;
    const steps = [
      { title: 'Оплачен', icon: '✓', stamp: order.paid_at },
      { title: 'Кухня собирает', icon: '👨‍🍳', stamp: null },
      isLocker(order)
        ? { title: order.cell_number ? `В ячейке №${order.cell_number}` : 'В ячейке постамата', icon: '📦', stamp: order.placed_at }
        : { title: 'Готов к выдаче', icon: '🔔', stamp: order.ready_at },
      { title: 'Выдан', icon: '🎉', stamp: order.issued_at || order.picked_up_at },
    ];
    return steps.map((step, i) => {
      const done = index > i || current === 'issued';
      const isCurrent = index === i && current !== 'issued';
      const { stamp } = step;
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
        // правило отмены считает сервер: до отсечки перемены — сам, после — через оператора
        const cancellable = order.can_cancel;
        const lockedByDeadline = ['paid', 'accepted'].includes(order.status) && !order.can_cancel;
        const locker = order.pickup_kind === 'locker';
        const showQr = !locker && ['paid', 'accepted', 'cooking', 'ready'].includes(order.status);
        const waitLocker = locker && ['paid', 'accepted', 'cooking', 'ready'].includes(order.status);
        body.innerHTML = `
          ${
            order.status === 'cancelled'
              ? `<section class="section center">
                   <div style="font-size:46px">🚫</div>
                   <div class="bold mt-8">Заказ отменён</div>
                   <div class="small muted">${
                     order.cancel_reason === 'expired'
                       ? 'Время на оплату вышло — порции вернулись в меню. Оформите заказ заново.'
                       : order.cancel_reason === 'deadline'
                         ? `Приём заказов на перемену закрылся в ${esc(order.deadline_time || '')}. Деньги не списаны.`
                         : 'Бонусы и оплата возвращены'
                   }</div>
                 </section>`
              : ''
          }

          ${
            order.status === 'in_locker'
              ? `<section class="section center">
                   <div class="small muted">Поднесите код к сканеру постамата</div>
                   <div class="qr-box mt-16" id="locker-qr"><div class="skeleton" style="height:100%"></div></div>
                   <div class="locker-pin mt-16" id="locker-pin" aria-live="polite"></div>
                   <div class="small muted" id="locker-timer">Код одноразовый и обновляется каждую минуту</div>
                   <div class="mt-16">
                     <span class="status-pill status-pill--in_locker">📦 ${esc(lockerText(order))}</span>
                   </div>
                   <div class="small muted mt-8">Нет камеры у сканера? Введите PIN на клавиатуре постамата.</div>
                 </section>`
              : ''
          }
          ${
            waitLocker
              ? `<section class="section center">
                   <div style="font-size:46px">📦</div>
                   <div class="big-number mt-8">${esc(order.number)}</div>
                   <div class="bold mt-8">${order.status === 'ready' ? 'Заказ собран — скоро положим в ячейку' : 'Заказ заберёте в постамате'}</div>
                   <div class="small muted">${esc(order.pickup_point)}. Номер ячейки и одноразовый QR появятся здесь, когда заказ положат в постамат.</div>
                   <div class="mt-16"><span class="status-pill status-pill--${esc(order.status)}">${esc(order.status_label)}</span></div>
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
                       order.status === 'in_locker'
                         ? `<span class="status-pill status-pill--in_locker">📦 ${esc(lockerText(order))}</span>`
                         : order.status === 'ready'
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
              ${order.deadline_time && ['created', 'paid', 'accepted'].includes(order.status) ? `<div class="row"><span class="row__label">Приём заказов</span><span class="bold">до ${esc(order.deadline_time)}</span></div>` : ''}
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
            order.status === 'issued'
              ? `<section class="section" id="review-box">
                   <div class="section__head"><h2 class="section__title">Как вам заказ?</h2></div>
                   <div data-review-body><div class="skeleton" style="height:60px"></div></div>
                 </section>`
              : ''
          }
          ${
            ['issued', 'cancelled'].includes(order.status)
              ? '<button class="btn" data-repeat>↻ Повторить заказ</button>'
              : ''
          }
          ${cancellable ? '<button class="btn btn--danger" data-cancel>Отменить заказ</button>' : ''}
          ${lockedByDeadline ? `<div class="small muted center">Приём заказов закрылся в ${esc(order.deadline_time || '')} — кухня уже собирает. Отменить заказ можно через оператора на выдаче.</div>` : ''}
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
        syncLockerCode();
        mountReview();
      };

      /* Отзыв после выдачи: форма или уже оставленный отзыв (править можно 24 часа). */
      const presetRating = Number(ctx.query?.get('rate')) || 0;
      const mountReview = async (forceEdit = false) => {
        const host = body.querySelector('[data-review-body]');
        if (!host) return;
        let mine = null;
        try {
          [mine] = await api.get(`/api/reviews/mine?order_id=${order.id}`);
        } catch { /* покажем форму — сервер всё равно не даст оставить второй отзыв */ }
        if (mine && !forceEdit) {
          host.innerHTML = reviewCard(mine, {
            actions: mine.can_edit
              ? '<button class="btn btn--ghost btn--sm mt-8" data-edit-review>Изменить отзыв</button><div class="small muted mt-8">Изменить можно в течение 24 часов</div>'
              : '',
          });
          const editBtn = host.querySelector('[data-edit-review]');
          if (editBtn) editBtn.onclick = () => mountReview(true);
          return;
        }
        await mountReviewForm(host, {
          orderId: order.id,
          existing: mine,
          rating: presetRating,
          onSaved: () => mountReview(),
        });
      };

      /* Одноразовый QR постамата: живёт 120 с, экран берёт новый каждые ~60 с,
         старый при этом гаснет. Скриншот, пересланный другу, быстро протухнет. */
      let tokenTimer = null;
      let countdownTimer = null;
      let tokenExpires = 0;
      const stopLockerCode = () => {
        clearTimeout(tokenTimer);
        clearInterval(countdownTimer);
        tokenTimer = null;
        countdownTimer = null;
      };
      const refreshLockerCode = async () => {
        const qrHost = body.querySelector('#locker-qr');
        if (!qrHost || !document.body.contains(body)) { stopLockerCode(); return; }
        try {
          const t = await api.post(`/api/orders/${order.id}/pickup-token`, {}, { silent: true });
          qrHost.innerHTML = t.qr_svg;
          qrHost.querySelector('svg')?.setAttribute('aria-label', `Одноразовый QR заказа ${order.number}`);
          body.querySelector('#locker-pin').innerHTML = `PIN <b>${esc(t.pin.slice(0, 3))} ${esc(t.pin.slice(3))}</b>`;
          tokenExpires = Date.now() + t.ttl_seconds * 1000;
          tokenTimer = setTimeout(refreshLockerCode, t.refresh_after_seconds * 1000);
        } catch (err) {
          body.querySelector('#locker-timer').textContent = err.status === 0
            ? 'Нет связи — код обновится, когда появится интернет'
            : err.message;
          tokenTimer = setTimeout(refreshLockerCode, 10000);
        }
      };
      const syncLockerCode = () => {
        stopLockerCode();
        if (order.status !== 'in_locker') return;
        refreshLockerCode();
        countdownTimer = setInterval(() => {
          const label = body.querySelector('#locker-timer');
          if (!label || !document.body.contains(body)) { stopLockerCode(); return; }
          const left = Math.max(0, Math.round((tokenExpires - Date.now()) / 1000));
          if (tokenExpires) label.textContent = `Код одноразовый · действует ещё ${left} с`;
        }, 1000);
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
            if (fresh.status === 'in_locker') toast(`📦 ${lockerText(fresh)}`, 'ok');
            if (fresh.status === 'issued') toast('Заказ выдан. Приятного аппетита!', 'ok');
            await loadActiveOrders().catch(() => []);
          }
        } catch { /* сеть отвалилась — попробуем на следующем тике */ }
      }, 5000);
    },
  };
}
