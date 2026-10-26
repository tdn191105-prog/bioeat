/* Кабинет столовой: заказы по переменам, сводка «что собрать», выдача по коду.
   Процесс кухни: после отсечки перемены повара собирают все её заказы разом,
   поэтому экран построен вокруг перемен, а не вокруг канбана статусов. */
import api from '../api.js';
import { esc, money, toast, isoDate, dateLabel, skeletonList, empty, confirmSheet } from '../ui.js';
import { itemThumb } from '../components.js';

const COLLECT = ['paid', 'accepted', 'cooking'];

export default async function operatorView() {
  let day = isoDate(0);
  let timer = null;
  // раскрытые перемены переживают автообновление; null — ещё не выбирали
  let expanded = null;

  return {
    title: 'Кабинет столовой',
    wide: true,
    requiresAuth: true,
    roles: ['operator', 'admin'],
    html: `
      <div class="stack">
        <section class="section no-print">
          <div class="section__head">
            <h2 class="section__title">Выдача заказа</h2>
            <span class="small muted" id="clock"></span>
          </div>
          <div class="stack stack--sm">
            <div class="searchbar">
              <span>🎫</span>
              <input id="code" placeholder="Отсканируйте QR или введите номер RP-0000"
                     autocomplete="off" enterkeyhint="done" autocapitalize="characters">
            </div>
            <div class="grid-2">
              <button class="btn btn--green" id="issue">Выдать заказ</button>
              <button class="btn btn--ghost" id="lookup">Найти заказ</button>
            </div>
            <div id="scan-result"></div>
          </div>
        </section>

        <section class="section no-print">
          <div class="section__head">
            <h2 class="section__title">Смена</h2>
            <div class="hstack">
              <span id="lockers"></span>
              <span class="status-pill" id="issued-count">выдано 0</span>
              <button class="section__link" id="refresh">Обновить</button>
            </div>
          </div>
          <div class="chips" id="days"></div>
        </section>

        <div class="stack" id="shift">${skeletonList(3, 160)}</div>
      </div>`,

    async mount(root) {
      const shiftHost = root.querySelector('#shift');
      const daysHost = root.querySelector('#days');
      const codeInput = root.querySelector('#code');
      const scanResult = root.querySelector('#scan-result');
      const issuedCount = root.querySelector('#issued-count');
      const lockersHost = root.querySelector('#lockers');
      const clock = root.querySelector('#clock');
      let data = null;

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

      const orderCard = (order, slot) => {
        const actions = [];
        if (COLLECT.includes(order.status)) {
          actions.push(`<button class="btn btn--sm btn--green" data-ready="${order.id}">Собран</button>`);
        } else if (order.status === 'ready' && slot.is_locker) {
          actions.push(`<button class="btn btn--sm" data-place="${order.id}">Положен в ячейку</button>`);
        } else if (order.status === 'ready') {
          actions.push(`<button class="btn btn--sm btn--green" data-issue="${order.id}">Выдан</button>`);
        }
        actions.push(`<button class="btn btn--sm btn--danger" data-cancel="${order.id}" aria-label="Отменить заказ ${esc(order.number)}">Отменить</button>`);
        return `
          <div class="ticket ticket--${esc(order.status)}">
            <div class="ticket__head">
              <span class="ticket__num">${esc(order.number)}</span>
              <span class="status-pill status-pill--${esc(order.status)}">${
                order.status === 'in_locker' && order.cell_number
                  ? `Ячейка №${esc(order.cell_number)}`
                  : esc(order.status_label)
              }</span>
            </div>
            <div class="small muted" style="margin-top:3px">
              ${esc(order.customer_name || '')}${order.customer_group ? ` · ${esc(order.customer_group)}` : ''}
            </div>
            <div class="ticket__items">
              ${order.items
                .map((i) => `<span class="ticket__item">${itemThumb(i)}${esc(i.name)} <b>×${i.qty}</b></span>`)
                .join('')}
            </div>
            ${order.comment ? `<div class="small" style="color:var(--yellow);margin-bottom:8px">💬 ${esc(order.comment)}</div>` : ''}
            <div class="hstack" style="margin-bottom:9px">
              <span class="bold">${money(order.total)}</span>
              <div class="spacer"></div>
              <span class="small muted">${order.items.reduce((s, i) => s + i.qty, 0)} шт.</span>
            </div>
            <div class="ticket__actions no-print">${actions.join('')}</div>
          </div>`;
      };

      const summaryChips = (list) => list.length
        ? `<div class="collect">${list
            .map((i) => `<span class="collect__item">${esc(i.name)} <b>×${i.qty}</b></span>`)
            .join('')}</div>`
        : '';

      /* Лист сборки для печати: только то, что нужно повару, без кнопок. */
      const printSheet = (slot) => `
        <div class="print-sheet">
          <h2>${esc(slot.label)} · ${esc(slot.time_range)} · ${esc(dateLabel(data.date))}</h2>
          <div>${esc(slot.point)} · приём закрыт в ${esc(slot.deadline_time)} · заказов: ${slot.total}</div>
          <h3>Собрать</h3>
          <table>
            ${slot.all_items.map((i) => `<tr><td>☐ ${esc(i.name)}</td><td><b>${i.qty}</b></td></tr>`).join('')}
          </table>
          <h3>Заказы</h3>
          <table>
            ${slot.orders
              .map(
                (o) => `<tr>
                  <td><b>${esc(o.number)}</b></td>
                  <td>${esc(o.customer_name || '')}${o.customer_group ? `, ${esc(o.customer_group)}` : ''}</td>
                  <td>${o.items.map((i) => `${esc(i.name)} ×${i.qty}`).join('; ')}${o.comment ? ` — «${esc(o.comment)}»` : ''}</td>
                </tr>`,
              )
              .join('')}
          </table>
        </div>`;

      const slotSection = (slot) => {
        const key = String(slot.id);
        const open = expanded.has(key);
        const current = slot.id === data.current_slot_id;
        const intake = slot.intake_closed
          ? `<span class="status-pill status-pill--cooking">приём закрыт в ${esc(slot.deadline_time)}</span>`
          : slot.deadline_time
            ? `<span class="status-pill">приём до ${esc(slot.deadline_time)}</span>`
            : '';
        const c = slot.counts;
        const counters = [
          slot.to_collect_count ? `собрать ${slot.to_collect_count}` : '',
          c.ready ? `готово ${c.ready}` : '',
          c.in_locker ? `в ячейках ${c.in_locker}` : '',
          c.issued ? `выдано ${c.issued}` : '',
        ].filter(Boolean).join(' · ');

        return `
          <section class="section shift-slot ${current ? 'shift-slot--current' : ''} ${open ? 'is-open' : ''}"
                   data-slot-section="${key}">
            <button class="shift-slot__head" data-toggle="${key}" aria-expanded="${open}">
              <span class="shift-slot__time">${esc(slot.starts_at || '—')}</span>
              <span class="shift-slot__title">
                <span class="bold">${esc(slot.label)}${current ? ` <span class="shift-slot__now">${slot.is_over ? 'не всё выдано' : 'сейчас'}</span>` : ''}</span>
                <span class="small muted">${esc(slot.time_range)} · ${esc(slot.point)}${slot.is_locker ? ' · постамат' : ''}</span>
                <span class="small">${esc(counters || 'заказов нет')}</span>
              </span>
              <span class="shift-slot__side">
                ${intake}
                <span class="board__count">${slot.total}</span>
              </span>
            </button>
            ${
              open
                ? `<div class="shift-slot__body">
                     ${
                       slot.to_collect.length
                         ? `<div class="small bold muted shift-slot__label">Собрать (${slot.to_collect_count} зак.)</div>
                            ${summaryChips(slot.to_collect)}`
                         : slot.total
                           ? '<div class="small muted">Всё собрано ✓</div>'
                           : ''
                     }
                     ${
                       slot.total
                         ? `<div class="hstack shift-slot__tools no-print">
                              ${slot.to_collect_count && slot.id ? `<button class="btn btn--sm btn--green" data-collect-all="${slot.id}">Отметить всё как собранное</button>` : ''}
                              <button class="btn btn--sm btn--ghost" data-print="${key}">🖨 Печать / PDF</button>
                            </div>
                            <div class="board shift-slot__orders">${slot.orders.map((o) => orderCard(o, slot)).join('')}</div>
                            ${printSheet(slot)}`
                         : '<div class="small muted center" style="padding:10px 0">На эту перемену заказов нет</div>'
                     }
                   </div>`
                : ''
            }
          </section>`;
      };

      let lastSnapshot = '';

      const renderShift = (force = false) => {
        // не перерисовываем, если ничего не изменилось, — иначе кнопка уезжает
        // из-под пальца повара на автообновлении
        const snapshot = JSON.stringify({ d: { ...data, now: null }, e: [...expanded] });
        if (!force && snapshot === lastSnapshot) return;
        lastSnapshot = snapshot;

        issuedCount.textContent = `выдано ${data.issued_count}`;
        const lockers = data.lockers || [];
        lockersHost.innerHTML = lockers
          .map((l) => `<span class="status-pill ${l.is_online ? 'status-pill--ready' : 'status-pill--cancelled'}"
                         title="${esc(l.name)}">${l.is_online ? '● постамат онлайн' : '○ постамат не на связи'}</span>`)
          .join(' ');

        if (!data.slots.length) {
          shiftHost.innerHTML = empty('🕘', 'Окна выдачи не заданы', 'Добавьте их в админ-панели');
          return;
        }
        // сохраняем прокрутку: перерисовка не должна «прыгать» по странице
        const y = window.scrollY;
        shiftHost.innerHTML = `
          ${data.active_count ? '' : `<div class="card small muted">На ${esc(dateLabel(day))} активных заказов нет.</div>`}
          ${data.slots.map(slotSection).join('')}`;
        window.scrollTo(0, y);
      };

      const load = async (force = false) => {
        try {
          data = await api.get(`/api/operator/shift?date=${day}`, { silent: true });
          if (expanded === null) {
            expanded = new Set(data.current_slot_id != null ? [String(data.current_slot_id)] : []);
          }
          renderShift(force);
        } catch (err) {
          if (err.status !== 0) toast(err.message, 'err');
        }
      };

      renderDays();
      await load(true);

      // если сегодня всё пусто, а на завтра есть заказы — показываем завтра
      if (data && !data.active_count) {
        try {
          const nextDay = isoDate(1);
          const next = await api.get(`/api/operator/shift?date=${nextDay}`, { silent: true });
          if (next.active_count) {
            day = nextDay;
            data = next;
            expanded = new Set(next.current_slot_id != null ? [String(next.current_slot_id)] : []);
            renderDays();
            renderShift(true);
          }
        } catch { /* не критично для работы экрана */ }
      }

      timer = setInterval(() => {
        if (!document.body.contains(shiftHost)) {
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
        expanded = null;
        renderDays();
        load(true);
      };

      root.querySelector('#refresh').onclick = () => load(true);

      const patchStatus = async (id, status, okText) => {
        const order = await api.patch(`/api/operator/orders/${id}/status`, { status });
        toast(okText ? okText(order) : `${order.number}: ${order.status_label}`, 'ok');
        return order;
      };

      shiftHost.addEventListener('click', async (event) => {
        const toggle = event.target.closest('[data-toggle]');
        if (toggle) {
          const key = toggle.dataset.toggle;
          if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
          renderShift(true);
          return;
        }

        const print = event.target.closest('[data-print]');
        if (print) {
          const section = print.closest('[data-slot-section]');
          section.classList.add('print-target');
          document.body.classList.add('printing-slot');
          const cleanup = () => {
            section.classList.remove('print-target');
            document.body.classList.remove('printing-slot');
            window.removeEventListener('afterprint', cleanup);
          };
          window.addEventListener('afterprint', cleanup);
          window.print();
          setTimeout(cleanup, 1000);
          return;
        }

        const button = event.target.closest('button');
        if (!button) return;
        try {
          if (button.dataset.ready) {
            button.disabled = true;
            await patchStatus(button.dataset.ready, 'ready', (o) => `${o.number} собран`);
          } else if (button.dataset.issue) {
            button.disabled = true;
            await patchStatus(button.dataset.issue, 'issued', (o) => `${o.number} выдан`);
          } else if (button.dataset.place) {
            button.disabled = true;
            const order = await api.post(`/api/operator/orders/${button.dataset.place}/place`, {});
            toast(`${order.number} → ячейка №${order.cell_number}`, 'ok');
          } else if (button.dataset.collectAll) {
            const slot = data.slots.find((s) => String(s.id) === button.dataset.collectAll);
            const ok = await confirmSheet({
              title: `Отметить всё как собранное?`,
              text: `${slot.label}: ${slot.to_collect_count} зак. станут «Собран». Студенты получат уведомление «Заказ готов».`,
              confirmLabel: 'Да, всё собрано',
            });
            if (!ok) return;
            const result = await api.post(`/api/operator/shift/${slot.id}/collected?date=${day}`, {});
            toast(`Отмечено собранными: ${result.updated}`, 'ok');
          } else if (button.dataset.cancel) {
            const ok = await confirmSheet({
              title: 'Отменить заказ?',
              text: 'Порции вернутся в наличие, оплата и бонусы — студенту.',
              confirmLabel: 'Отменить заказ',
              danger: true,
            });
            if (!ok) return;
            await patchStatus(button.dataset.cancel, 'cancelled', (o) => `${o.number} отменён, порции возвращены`);
          } else {
            return;
          }
        } catch (err) {
          toast(err.message, 'err');
          button.disabled = false;
        }
        await load(true);
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
              ${order.cell_number ? ` · ячейка №${esc(order.cell_number)}` : ''}
            </div>
            <div class="ticket__items">${order.items
              .map((i) => `<span class="ticket__item">${itemThumb(i)}${esc(i.name)} ×${i.qty}</span>`)
              .join('')}</div>
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
          await load(true);
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
        // подписанный QR (ROSPIT: или старый BIOEAT:) и номер разбирает сервер
        try {
          showOrder(await api.get(`/api/operator/lookup/${encodeURIComponent(raw)}`));
        } catch (err) {
          toast(err.message, 'err');
        }
      };

      // сканер-«пистолет» вводит код и жмёт Enter — обрабатываем как выдачу
      codeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); doIssue(); }
      });
      // на стойке выдачи сканер вводит код в поле с фокусом; на телефоне не открываем клавиатуру
      if (window.matchMedia('(min-width: 900px)').matches) codeInput.focus();
    },
  };
}
