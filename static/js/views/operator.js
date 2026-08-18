/* Рабочий экран оператора столовой: очередь заказов и выдача по коду. */
import api from '../api.js';
import { esc, money, toast, isoDate, dateLabel, skeletonList, empty } from '../ui.js';

const COLUMNS = [
  { key: 'paid', title: 'Новые', hint: 'оплачены, ждут подтверждения', next: 'accepted', nextLabel: 'Принять' },
  { key: 'accepted', title: 'Принятые', hint: 'в работе у повара', next: 'cooking', nextLabel: 'Комплектовать' },
  { key: 'cooking', title: 'Комплектуются', hint: 'собираются в контейнер', next: 'ready', nextLabel: 'Готов' },
  { key: 'ready', title: 'К выдаче', hint: 'ждут студента', next: 'issued', nextLabel: 'Выдать' },
];

export default async function operatorView() {
  let day = isoDate(0);
  let timer = null;

  return {
    title: 'Экран оператора',
    wide: true,
    requiresAuth: true,
    roles: ['operator', 'admin'],
    html: `
      <div class="stack">
        <section class="section">
          <div class="section__head">
            <h2 class="section__title">Выдача заказа</h2>
            <span class="small muted" id="clock"></span>
          </div>
          <div class="stack stack--sm">
            <div class="searchbar">
              <span>🎫</span>
              <input id="code" placeholder="Отсканируйте QR или введите номер BE-0000"
                     autocomplete="off" enterkeyhint="done" autocapitalize="characters">
            </div>
            <div class="grid-2">
              <button class="btn btn--green" id="issue">Выдать заказ</button>
              <button class="btn btn--ghost" id="lookup">Найти заказ</button>
            </div>
            <div id="scan-result"></div>
          </div>
        </section>

        <section class="section">
          <div class="section__head">
            <h2 class="section__title">Очередь</h2>
            <div class="hstack">
              <span class="status-pill" id="issued-count">выдано 0</span>
              <button class="section__link" id="refresh">Обновить</button>
            </div>
          </div>
          <div class="chips" id="days"></div>
        </section>

        <div class="board" id="board">${skeletonList(4, 200)}</div>
      </div>`,

    async mount(root) {
      const board = root.querySelector('#board');
      const daysHost = root.querySelector('#days');
      const codeInput = root.querySelector('#code');
      const scanResult = root.querySelector('#scan-result');
      const issuedCount = root.querySelector('#issued-count');
      const clock = root.querySelector('#clock');

      const tickClock = () => {
        clock.textContent = new Date().toLocaleTimeString('ru-RU', {
          hour: '2-digit', minute: '2-digit', second: '2-digit',
        });
      };
      tickClock();
      const clockTimer = setInterval(tickClock, 1000);

      const renderDays = () => {
        daysHost.innerHTML = [0, 1, 2, 3]
          .map((offset) => {
            const iso = isoDate(offset);
            return `<button class="chip ${day === iso ? 'is-active' : ''}" data-day="${iso}">${esc(dateLabel(iso))}</button>`;
          })
          .join('');
      };

      const ticketHtml = (order, column) => `
        <div class="ticket ticket--${esc(order.status)}">
          <div class="ticket__head">
            <span class="ticket__num">${esc(order.number)}</span>
            <span class="small muted nowrap">${esc((order.slot_label || '').split('·').pop().trim())}</span>
          </div>
          <div class="small muted" style="margin-top:3px">
            ${esc(order.customer_name || '')}${order.customer_group ? ` · ${esc(order.customer_group)}` : ''}
          </div>
          <div class="ticket__items">
            ${order.items.map((i) => `${esc(i.icon)} ${esc(i.name)} <b>×${i.qty}</b>`).join('<br>')}
          </div>
          ${order.comment ? `<div class="small" style="color:var(--yellow);margin-bottom:8px">💬 ${esc(order.comment)}</div>` : ''}
          <div class="hstack" style="margin-bottom:9px">
            <span class="bold">${money(order.total)}</span>
            <div class="spacer"></div>
            <span class="small muted">${order.items.reduce((s, i) => s + i.qty, 0)} шт.</span>
          </div>
          <div class="ticket__actions">
            <button class="btn btn--sm ${column.next === 'issued' ? 'btn--green' : ''}"
                    data-next="${order.id}" data-status="${column.next}">${esc(column.nextLabel)}</button>
            <button class="btn btn--sm btn--danger" data-cancel="${order.id}">Отменить</button>
          </div>
        </div>`;

      let lastSnapshot = '';

      const renderBoard = (data, force = false) => {
        // не перерисовываем доску, если ничего не изменилось —
        // иначе кнопка уезжает из-под курсора оператора на автообновлении
        const snapshot = JSON.stringify(data);
        if (!force && snapshot === lastSnapshot) return;
        lastSnapshot = snapshot;

        issuedCount.textContent = `выдано ${data.issued_count}`;
        const total = Object.values(data.counts).reduce((a, b) => a + b, 0);
        if (!total) {
          board.innerHTML = `<div style="grid-column:1/-1">${empty(
            '☕',
            'Активных заказов нет',
            `На ${dateLabel(day)} очередь пуста`,
          )}</div>`;
          return;
        }
        board.innerHTML = COLUMNS.map(
          (col) => `
          <div class="board__col">
            <div class="board__col-head">
              <span>${esc(col.title)}</span>
              <span class="board__count">${data.counts[col.key] || 0}</span>
            </div>
            <div class="small muted" style="margin:-6px 0 10px">${esc(col.hint)}</div>
            ${
              (data.columns[col.key] || []).length
                ? data.columns[col.key].map((o) => ticketHtml(o, col)).join('')
                : '<div class="small muted center" style="padding:14px 0">пусто</div>'
            }
          </div>`,
        ).join('');
      };

      const load = async () => {
        try {
          renderBoard(await api.get(`/api/operator/board?date=${day}`, { silent: true }));
        } catch (err) {
          if (err.status !== 0) toast(err.message, 'err');
        }
      };

      renderDays();
      await load();

      // если на сегодня очередь пуста, а на завтра есть заказы — показываем их сразу
      try {
        const todayBoard = await api.get(`/api/operator/board?date=${day}`, { silent: true });
        const todayTotal = Object.values(todayBoard.counts).reduce((a, b) => a + b, 0);
        if (!todayTotal) {
          const nextDay = isoDate(1);
          const nextBoard = await api.get(`/api/operator/board?date=${nextDay}`, { silent: true });
          if (Object.values(nextBoard.counts).reduce((a, b) => a + b, 0)) {
            day = nextDay;
            renderDays();
            renderBoard(nextBoard, true);
          }
        }
      } catch { /* не критично для работы экрана */ }

      timer = setInterval(() => {
        if (!document.body.contains(board)) {
          clearInterval(timer);
          clearInterval(clockTimer);
          return;
        }
        load();
      }, 7000);

      daysHost.onclick = (e) => {
        const btn = e.target.closest('[data-day]');
        if (!btn) return;
        day = btn.dataset.day;
        lastSnapshot = '';
        renderDays();
        load();
      };

      root.querySelector('#refresh').onclick = load;

      board.addEventListener('click', async (event) => {
        const next = event.target.closest('[data-next]');
        if (next) {
          next.disabled = true;
          try {
            const order = await api.patch(`/api/operator/orders/${next.dataset.next}/status`, {
              status: next.dataset.status,
            });
            toast(`${order.number}: ${order.status_label}`, 'ok');
          } catch (err) {
            toast(err.message, 'err');
          }
          await load();
          return;
        }
        const cancel = event.target.closest('[data-cancel]');
        if (cancel) {
          cancel.disabled = true;
          try {
            const order = await api.patch(`/api/operator/orders/${cancel.dataset.cancel}/status`, {
              status: 'cancelled',
            });
            toast(`${order.number} отменён, порции возвращены`, 'ok');
          } catch (err) {
            toast(err.message, 'err');
          }
          await load();
        }
      });

      const showOrder = (order, kind = '') => {
        scanResult.innerHTML = `
          <div class="card" style="border:1px solid ${
            kind === 'ok' ? 'rgba(52,199,89,.5)' : 'var(--line)'
          }">
            <div class="hstack">
              <span class="ticket__num">${esc(order.number)}</span>
              <div class="spacer"></div>
              <span class="status-pill status-pill--${esc(order.status)}">${esc(order.status_label)}</span>
            </div>
            <div class="small muted mt-8">
              ${esc(order.customer_name || '')} · ${esc(order.slot_label)} · ${dateLabel(order.pickup_date)}
            </div>
            <div class="ticket__items">${order.items.map((i) => `${esc(i.icon)} ${esc(i.name)} ×${i.qty}`).join('<br>')}</div>
            <div class="bold">${money(order.total)}</div>
          </div>`;
      };

      const doIssue = async () => {
        const code = codeInput.value.trim();
        if (!code) { toast('Введите код или номер заказа', 'err'); return; }
        try {
          const order = await api.post('/api/operator/issue', { code });
          toast(`Заказ ${order.number} выдан`, 'ok');
          showOrder(order, 'ok');
          codeInput.value = '';
          await load();
        } catch (err) {
          toast(err.message, 'err');
          scanResult.innerHTML = `<div class="card small" style="border:1px solid rgba(255,77,79,.5);color:#ff7875">${esc(err.message)}</div>`;
        }
        codeInput.focus();
      };

      root.querySelector('#issue').onclick = doIssue;
      root.querySelector('#lookup').onclick = async () => {
        const raw = codeInput.value.trim();
        if (!raw) return;
        const number = raw.startsWith('BIOEAT:') ? raw.split(':')[1] : raw.toUpperCase();
        try {
          showOrder(await api.get(`/api/operator/lookup/${encodeURIComponent(number)}`));
        } catch (err) {
          toast(err.message, 'err');
        }
      };

      // сканер-«пистолет» вводит код и жмёт Enter — обрабатываем как выдачу
      codeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); doIssue(); }
      });
      codeInput.focus();
    },
  };
}
