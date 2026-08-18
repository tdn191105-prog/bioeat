/* Экран оплаты. Демонстрационный эквайринг: реальные системы не подключены. */
import api from '../api.js';
import { loadUser, loadActiveOrders } from '../state.js';
import { esc, money, toast, go, dateLabel } from '../ui.js';

const METHODS = [
  { id: 'sbp', icon: '⚡', title: 'СБП', sub: 'Система быстрых платежей · без комиссии' },
  { id: 'card', icon: '💳', title: 'Банковская карта', sub: 'МИР · Visa · Mastercard' },
];

export default async function payView(ctx) {
  const orderId = Number(ctx.params.id);
  let order;
  try {
    order = await api.get(`/api/orders/${orderId}`);
  } catch (err) {
    toast(err.message, 'err');
    return { title: 'Оплата', html: '', mount: () => go('#/orders') };
  }

  if (order.status !== 'created') {
    return { title: 'Оплата', html: '', mount: () => go(`#/order/${orderId}`) };
  }

  const form = { method: 'sbp', failure: false, busy: false };

  return {
    title: 'Оплата',
    requiresAuth: true,
    html: `
      <div class="stack">
        <section class="section center">
          <div class="small muted">Заказ ${esc(order.number)}</div>
          <div style="font-size:38px;font-weight:900;letter-spacing:-1px;margin:6px 0">${money(order.total)}</div>
          <div class="small muted">${esc(order.slot_label)} · ${dateLabel(order.pickup_date)}</div>
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
                          <span class="row__label">${esc(i.icon)} ${esc(i.name)} ×${i.qty}</span>
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
        </section>

        <section class="section">
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
        </section>
      </div>`,

    async mount(root) {
      const methodsHost = root.querySelector('#methods');

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

      const failToggle = root.querySelector('#fail-toggle');
      failToggle.onclick = () => {
        form.failure = !form.failure;
        failToggle.classList.toggle('is-active', form.failure);
        failToggle.querySelector('.switch').classList.toggle('is-on', form.failure);
      };

      root.addEventListener('do-pay', async () => {
        if (form.busy) return;
        form.busy = true;
        const button = document.querySelector('#action-bar .btn');
        if (button) { button.disabled = true; button.textContent = 'Проводим платёж…'; }

        // небольшая задержка — как у настоящего эквайринга
        await new Promise((r) => setTimeout(r, 900));

        try {
          const result = await api.post(`/api/orders/${orderId}/pay`, {
            method: form.method,
            simulate_failure: form.failure,
          });
          if (result.ok) {
            toast(result.message, 'ok');
            await Promise.all([loadUser(), loadActiveOrders().catch(() => [])]);
            go(`#/order/${orderId}`);
            return;
          }
          toast(result.message, 'err');
        } catch (err) {
          toast(err.message, 'err');
        }
        form.busy = false;
        if (button) { button.disabled = false; button.textContent = `Оплатить ${money(order.total)}`; }
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
