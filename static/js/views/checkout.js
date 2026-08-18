/* Оформление: дата, окно выдачи, бонусы, комментарий. */
import api from '../api.js';
import { state, loadCart } from '../state.js';
import { esc, money, toast, go, isoDate, dateLabel, empty, skeletonList } from '../ui.js';

export default async function checkoutView() {
  const form = {
    date: isoDate(0),
    slotId: null,
    useBonus: false,
    comment: '',
    slots: [],
  };

  return {
    title: 'Когда забрать',
    requiresAuth: true,
    html: `
      <div class="stack">
        <section class="section">
          <div class="section__head"><h2 class="section__title">Дата</h2></div>
          <div class="chips" id="dates"></div>
        </section>

        <section class="section">
          <div class="section__head"><h2 class="section__title">Окно выдачи</h2></div>
          <div class="stack stack--sm" id="slots">${skeletonList(3, 76)}</div>
        </section>

        <section class="section">
          <div class="section__head"><h2 class="section__title">Детали</h2></div>
          <div class="stack">
            <div id="bonus-box"></div>
            <div class="field">
              <label class="field__label" for="comment">Комментарий для кухни</label>
              <textarea class="input" id="comment" maxlength="300"
                placeholder="Например: без лука, приборы не нужны"></textarea>
            </div>
          </div>
        </section>

        <section class="section" id="totals"></section>
      </div>`,

    async mount(root) {
      await loadCart();
      if (!state.cart.count) {
        toast('Корзина пуста', 'err');
        go('#/menu');
        return;
      }

      const datesHost = root.querySelector('#dates');
      const slotsHost = root.querySelector('#slots');
      const bonusHost = root.querySelector('#bonus-box');
      const totalsHost = root.querySelector('#totals');
      const comment = root.querySelector('#comment');

      const renderDates = () => {
        datesHost.innerHTML = [0, 1, 2, 3, 4, 5, 6]
          .map((offset) => {
            const iso = isoDate(offset);
            const d = new Date(`${iso}T00:00:00`);
            const label = offset < 3
              ? dateLabel(iso)
              : d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' });
            return `<button class="chip ${form.date === iso ? 'is-active' : ''}" data-date="${iso}">${esc(label)}</button>`;
          })
          .join('');
      };

      const renderSlots = () => {
        if (!form.slots.length) {
          slotsHost.innerHTML = empty('🕘', 'На эту дату окна не заданы', 'Выберите другой день');
          return;
        }
        const anyAvailable = form.slots.some((s) => s.is_available);
        slotsHost.innerHTML = `
          ${
            anyAvailable
              ? ''
              : `<div class="card small muted" style="border:1px solid rgba(240,180,41,.3)">
                   Приём заказов на сегодня уже закрыт — выберите завтрашний день выше.
                 </div>`
          }
          ${form.slots
            .map(
              (s) => `
              <button class="option ${form.slotId === s.id ? 'is-active' : ''}"
                      data-slot="${s.id}" ${s.is_available ? '' : 'disabled'}>
                <span class="option__ico">${s.left > 10 ? '🕐' : '⏳'}</span>
                <span class="option__body">
                  <span class="option__title">${esc(s.label)} · ${esc(s.time_range)}</span>
                  <span class="option__sub">${esc(s.point)}</span>
                </span>
                <span class="option__right">
                  ${
                    s.is_available
                      ? `свободно<br><b style="color:var(--green)">${s.left}</b>`
                      : s.left <= 0
                        ? 'мест нет'
                        : 'закрыто'
                  }
                </span>
              </button>`,
            )
            .join('')}`;

        slotsHost.querySelectorAll('[data-slot]').forEach((btn) => {
          btn.onclick = () => {
            form.slotId = Number(btn.dataset.slot);
            renderSlots();
            renderTotals();
          };
        });
      };

      const renderBonus = () => {
        const max = Number(state.cart.max_bonus_applicable || 0);
        if (max <= 0) {
          bonusHost.innerHTML = `<div class="card small muted">
            Бонусов пока нет. Кэшбэк 5% начислится после оплаты этого заказа.
          </div>`;
          return;
        }
        bonusHost.innerHTML = `
          <button class="option ${form.useBonus ? 'is-active' : ''}" id="bonus-toggle">
            <span class="option__ico">🎁</span>
            <span class="option__body">
              <span class="option__title">Списать бонусы</span>
              <span class="option__sub">Доступно ${money(state.cart.bonus_available)} · спишем до ${money(max)}</span>
            </span>
            <span class="switch ${form.useBonus ? 'is-on' : ''}"></span>
          </button>`;
        bonusHost.querySelector('#bonus-toggle').onclick = () => {
          form.useBonus = !form.useBonus;
          renderBonus();
          renderTotals();
        };
      };

      const renderTotals = () => {
        const subtotal = Number(state.cart.subtotal);
        const discount = form.useBonus ? Number(state.cart.max_bonus_applicable) : 0;
        const total = Math.max(0, subtotal - discount);
        const slot = form.slots.find((s) => s.id === form.slotId);
        totalsHost.innerHTML = `
          <div class="rows">
            <div class="row"><span class="row__label">Блюда</span><span class="bold">${money(subtotal)}</span></div>
            ${discount ? `<div class="row"><span class="row__label">Списание бонусов</span><span class="bold" style="color:var(--green)">−${money(discount)}</span></div>` : ''}
            <div class="row"><span class="row__label">Время выдачи</span><span class="bold nowrap">${
              slot ? `${esc(slot.time_range)}, ${dateLabel(form.date)}` : 'не выбрано'
            }</span></div>
            <div class="row row--total"><span class="row__label">К оплате</span><span>${money(total)}</span></div>
            <div class="small muted">Начислим ${money(total * 0.05)} бонусами после оплаты.</div>
          </div>`;
        const button = document.querySelector('#action-bar .btn');
        if (button) {
          button.disabled = !form.slotId;
          button.textContent = form.slotId ? `Оформить · ${money(total)}` : 'Выберите окно выдачи';
        }
      };

      const loadSlots = async () => {
        slotsHost.innerHTML = skeletonList(3, 76);
        try {
          form.slots = await api.get(`/api/slots?date=${form.date}`);
        } catch (err) {
          toast(err.message, 'err');
          form.slots = [];
        }
        const current = form.slots.find((s) => s.id === form.slotId);
        if (!current || !current.is_available) {
          const first = form.slots.find((s) => s.is_available);
          form.slotId = first ? first.id : null;
        }
        renderSlots();
        renderTotals();
      };

      renderDates();
      renderBonus();
      await loadSlots();

      // если на сегодня всё закрыто — сразу предлагаем завтра
      if (!form.slots.some((s) => s.is_available)) {
        form.date = isoDate(1);
        renderDates();
        await loadSlots();
      }

      datesHost.onclick = async (e) => {
        const btn = e.target.closest('[data-date]');
        if (!btn) return;
        form.date = btn.dataset.date;
        renderDates();
        await loadSlots();
      };

      comment.addEventListener('input', (e) => { form.comment = e.target.value; });

      root.addEventListener('submit-order', async () => {
        const button = document.querySelector('#action-bar .btn');
        if (button) { button.disabled = true; button.textContent = 'Оформляем…'; }
        try {
          const order = await api.post('/api/orders', {
            slot_id: form.slotId,
            comment: form.comment,
            use_bonus: form.useBonus,
            pickup_date: form.date,
          });
          await loadCart();
          go(`#/pay/${order.id}`);
        } catch (err) {
          toast(err.message, 'err');
          if (err.status === 409) await loadSlots();
          renderTotals();
        }
      });
    },

    footer() {
      const subtotal = Number(state.cart.subtotal || 0);
      const discount = form.useBonus ? Number(state.cart.max_bonus_applicable || 0) : 0;
      const total = Math.max(0, subtotal - discount);
      return form.slotId
        ? `<button class="btn" data-submit>Оформить · ${money(total)}</button>`
        : '<button class="btn" disabled data-submit>Выберите окно выдачи</button>';
    },

    onFooterClick(event, root) {
      if (event.target.closest('[data-submit]')) {
        root.dispatchEvent(new CustomEvent('submit-order'));
      }
    },
  };
}
