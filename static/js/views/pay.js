/* Экран оплаты. Провайдер задаётся на сервере (PAYMENT_PROVIDER):
   demo — платёж имитируется, можно смоделировать отказ банка;
   боевой (ЮKassa) — студент уходит на страницу банка или в банковское приложение (СБП),
   а заказ станет «Оплачен» только после подтверждения банка. */
import api from '../api.js';
import { loadUser, loadActiveOrders } from '../state.js';
import { esc, money, toast, go, dateLabel } from '../ui.js';

const METHODS = [
  { id: 'sbp', icon: '⚡', title: 'СБП', sub: 'Через приложение вашего банка · без комиссии' },
  { id: 'card', icon: '💳', title: 'Банковская карта', sub: 'МИР · Visa · Mastercard' },
];

/** Переход на страницу банка. В обёртке Android ссылки СБП открывает нативный код (см. mobile/). */
export function openBank(url) {
  window.location.href = url;
}

export default async function payView(ctx) {
  const orderId = Number(ctx.params.id);
  let order;
  let config = { provider: 'demo', demo: true };
  try {
    [order, config] = await Promise.all([
      api.get(`/api/orders/${orderId}`),
      api.get('/api/payments/config').catch(() => config),
    ]);
  } catch (err) {
    toast(err.message, 'err');
    return { title: 'Оплата', html: '', mount: () => go('#/orders') };
  }

  if (order.status !== 'created') {
    return { title: 'Оплата', html: '', mount: () => go(`#/order/${orderId}`) };
  }

  const form = { method: 'sbp', failure: false, busy: false };
  const demo = config.demo;

  return {
    title: 'Оплата',
    requiresAuth: true,
    html: `
      <div class="stack">
        <section class="section center">
          ${demo ? '<span class="status-pill status-pill--created">Демо-режим</span>' : ''}
          <div class="small muted mt-8">Заказ ${esc(order.number)}</div>
          <div style="font-size:38px;font-weight:900;letter-spacing:-1px;margin:6px 0">${money(order.total)}</div>
          <div class="small muted">${esc(order.slot_label)} · ${dateLabel(order.pickup_date)}</div>
          <div class="small mt-8" id="pay-left"></div>
        </section>

        <section class="section">
          <div class="section__head"><h2 class="section__title">Способ оплаты</h2></div>
          <div class="stack stack--sm" id="methods"></div>
        </section>

        <section class="section">
          <div class="section__head"><h2 class="section__title">Состав</h2></div>
          <div class="rows">
            ${order.items
              .map(
                (i) => `<div class="row">
                          <span class="row__label">${esc(i.name)} ×${i.qty}</span>
                          <span>${money(i.price * i.qty)}</span>
                        </div>`,
              )
              .join('')}
            ${
              Number(order.bonus_used) > 0
                ? `<div class="row"><span class="row__label">Списано бонусов</span>
                     <span style="color:var(--green)">−${money(order.bonus_used)}</span></div>`
                : ''
            }
            <div class="row row--total"><span class="row__label">К оплате</span><span>${money(order.total)}</span></div>
          </div>
          ${demo ? '' : '<div class="small muted mt-8">Электронный чек придёт на вашу почту.</div>'}
        </section>

        ${
          demo
            ? `<section class="section">
                 <div class="stack stack--sm">
                   <div class="small bold">Демонстрационный режим</div>
                   <div class="small muted">
                     Платёж имитируется на стороне сервера — обращений к банку и СБП не происходит.
                     Переключатель ниже позволяет показать сценарий отказа.
                   </div>
                   <button class="option" id="fail-toggle">
                     <span class="option__ico">🧪</span>
                     <span class="option__body">
                       <span class="option__title">Смоделировать отказ банка</span>
                       <span class="option__sub">Для демонстрации обработки ошибки</span>
                     </span>
                     <span class="switch"></span>
                   </button>
                 </div>
               </section>`
            : ''
        }
      </div>`,

    async mount(root) {
      const methodsHost = root.querySelector('#methods');
      const leftHost = root.querySelector('#pay-left');

      const renderMethods = () => {
        methodsHost.innerHTML = METHODS.map(
          (m) => `
          <button class="option ${form.method === m.id ? 'is-active' : ''}" data-method="${m.id}">
            <span class="option__ico">${m.icon}</span>
            <span class="option__body">
              <span class="option__title">${esc(m.title)}</span>
              <span class="option__sub">${esc(m.sub)}</span>
            </span>
            <span class="option__right">${form.method === m.id ? '✓' : ''}</span>
          </button>`,
        ).join('');
        methodsHost.querySelectorAll('[data-method]').forEach((btn) => {
          btn.onclick = () => { form.method = btn.dataset.method; renderMethods(); };
        });
      };
      renderMethods();

      // сколько осталось на оплату: потом заказ отменится, порции вернутся в меню
      const payUntil = order.pay_until ? new Date(order.pay_until.endsWith('Z') ? order.pay_until : `${order.pay_until}Z`) : null;
      const tick = () => {
        if (!payUntil || !document.body.contains(leftHost)) { clearInterval(timer); return; }
        const sec = Math.max(0, Math.round((payUntil - Date.now()) / 1000));
        leftHost.innerHTML = sec
          ? `<span class="${sec < 120 ? 'slot-deadline--soon' : 'muted'}">Оплатите в течение ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}</span>`
          : '<span class="slot-deadline--soon">Время на оплату вышло</span>';
      };
      const timer = setInterval(tick, 1000);
      tick();

      const failToggle = root.querySelector('#fail-toggle');
      if (failToggle) {
        failToggle.onclick = () => {
          form.failure = !form.failure;
          failToggle.classList.toggle('is-active', form.failure);
          failToggle.querySelector('.switch').classList.toggle('is-on', form.failure);
        };
      }

      root.addEventListener('do-pay', async () => {
        if (form.busy) return;
        form.busy = true;
        const button = document.querySelector('#action-bar .btn');
        const setButton = (text, disabled) => { if (button) { button.disabled = disabled; button.textContent = text; } };
        setButton(demo ? 'Проводим платёж…' : 'Переходим в банк…', true);

        // в демо — небольшая задержка, как у настоящего эквайринга
        if (demo) await new Promise((r) => setTimeout(r, 900));

        try {
          const result = await api.post(`/api/orders/${orderId}/pay`, {
            method: form.method,
            simulate_failure: demo && form.failure,
          });
          if (result.ok) {
            toast(result.message, 'ok');
            await Promise.all([loadUser(), loadActiveOrders().catch(() => [])]);
            go(`#/order/${orderId}`);
            return;
          }
          if (result.status === 'pending' && result.confirmation_url) {
            openBank(result.confirmation_url);
            return;
          }
          toast(result.message, 'err');
        } catch (err) {
          toast(err.message, 'err');
          if (err.status === 409) { go(`#/order/${orderId}`); return; }
        }
        form.busy = false;
        setButton(`Оплатить ${money(order.total)}`, false);
      });
    },

    footer() {
      return `<button class="btn" data-pay>Оплатить ${money(order.total)}</button>`;
    },

    onFooterClick(event, root) {
      if (event.target.closest('[data-pay]')) root.dispatchEvent(new CustomEvent('do-pay'));
    },
  };
}
