/* Отзывы для столовой: средняя оценка, распределение, частые теги, лента с ответами. */
import api from '../api.js';
import { esc, toast, skeletonList, empty, dateTime, openSheet, closeSheet } from '../ui.js';
import { reviewCard, reviewTags, starsHtml } from '../components.js';

export default async function reviewsView() {
  const filters = { period: 'week', rating: '', tag: '', status: '', unanswered: false };

  return {
    title: 'Отзывы',
    wide: true,
    requiresAuth: true,
    roles: ['operator', 'admin'],
    html: `
      <div class="stack">
        <div class="grid-2" id="summary">${skeletonList(2, 150)}</div>
        <section class="section">
          <div class="stack stack--sm">
            <div class="chips" id="period"></div>
            <div class="chips" id="filters"></div>
          </div>
        </section>
        <section class="section"><div id="feed">${skeletonList(3, 90)}</div></section>
      </div>`,

    async mount(root) {
      const summaryHost = root.querySelector('#summary');
      const periodHost = root.querySelector('#period');
      const filtersHost = root.querySelector('#filters');
      const feed = root.querySelector('#feed');
      const tags = await reviewTags().catch(() => []);

      const summaryCard = (title, s) => {
        const max = Math.max(1, ...Object.values(s.distribution));
        return `
          <section class="section">
            <div class="small muted">${esc(title)}</div>
            <div class="hstack" style="margin:4px 0 12px">
              <span style="font-size:34px;font-weight:900">${s.avg != null ? s.avg.toFixed(1).replace('.', ',') : '—'}</span>
              ${s.avg != null ? starsHtml(Math.round(s.avg), 'stars--lg') : ''}
              <div class="spacer"></div>
              <span class="small muted">${s.count} отз.</span>
            </div>
            <div class="review-dist">
              ${[5, 4, 3, 2, 1].map((n) => `
                <span>${n}★</span>
                <span class="review-dist__bar"><span style="width:${Math.round((s.distribution[n] / max) * 100)}%"></span></span>
                <span class="small muted">${s.distribution[n]}</span>`).join('')}
            </div>
            ${s.top_tags.length ? `<div class="tag-row" style="margin-top:12px">${s.top_tags
              .map((t) => `<span class="tag" style="${t.positive ? '' : 'color:#ff8a8c'}">${esc(t.label)} · ${t.count}</span>`)
              .join('')}</div>` : ''}
            ${s.unanswered ? `<div class="small mt-8" style="color:var(--orange)">Без ответа с оценкой ≤ 3: ${s.unanswered}</div>` : ''}
          </section>`;
      };

      const renderFilters = () => {
        periodHost.innerHTML = [['week', 'Неделя'], ['month', 'Месяц'], ['all', 'Всё время']]
          .map(([k, l]) => `<button class="chip ${filters.period === k ? 'is-active' : ''}" data-period="${k}">${l}</button>`)
          .join('');
        filtersHost.innerHTML = `
          ${[5, 4, 3, 2, 1].map((n) => `<button class="chip ${filters.rating === String(n) ? 'is-active' : ''}" data-rating="${n}">${n}★</button>`).join('')}
          <button class="chip ${filters.unanswered ? 'is-active' : ''}" data-unanswered>Без ответа</button>
          <button class="chip ${filters.status === 'hidden' ? 'is-active' : ''}" data-hidden>Скрытые</button>
          ${tags.map((t) => `<button class="chip ${filters.tag === t.code ? 'is-active' : ''}" data-tag="${t.code}">${esc(t.label)}</button>`).join('')}`;
      };

      const load = async () => {
        const q = new URLSearchParams({ period: filters.period });
        if (filters.rating) q.set('rating', filters.rating);
        if (filters.tag) q.set('tag', filters.tag);
        if (filters.status) q.set('status', filters.status);
        if (filters.unanswered) q.set('only_unanswered', 'true');
        try {
          const data = await api.get(`/api/staff/reviews?${q}`);
          summaryHost.innerHTML = summaryCard('За неделю', data.summary.week) + summaryCard('За месяц', data.summary.month);
          feed.innerHTML = data.items.length
            ? data.items.map((r) => reviewCard(r, {
                actions: `
                  <div class="hstack small muted mt-8" style="gap:12px;flex-wrap:wrap">
                    <span>${dateTime(r.created_at)}</span>
                    ${r.status === 'hidden' ? '<span class="status-pill status-pill--cancelled">скрыт</span>' : ''}
                    <div class="spacer"></div>
                    <button class="section__link" data-reply="${r.id}">${r.staff_reply ? 'Изменить ответ' : 'Ответить'}</button>
                    <button class="section__link" data-hide="${r.id}" data-to="${r.status !== 'hidden'}">${r.status === 'hidden' ? 'Показать' : 'Скрыть'}</button>
                  </div>`,
              })).join('')
            : empty('💬', 'Отзывов пока нет', 'Попробуйте другой период или фильтр');
          feed.dataset.items = JSON.stringify(data.items.map((r) => ({ id: r.id, reply: r.staff_reply })));
        } catch (err) {
          toast(err.message, 'err');
        }
      };

      renderFilters();
      await load();

      const toggle = (key, value) => { filters[key] = filters[key] === value ? '' : value; };
      root.addEventListener('click', async (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        if (b.dataset.period) filters.period = b.dataset.period;
        else if (b.dataset.rating) toggle('rating', b.dataset.rating);
        else if (b.dataset.tag) toggle('tag', b.dataset.tag);
        else if ('unanswered' in b.dataset) filters.unanswered = !filters.unanswered;
        else if ('hidden' in b.dataset) toggle('status', 'hidden');
        else if (b.dataset.hide) {
          try {
            await api.post(`/api/staff/reviews/${b.dataset.hide}/visibility?hidden=${b.dataset.to}`);
            toast(b.dataset.to === 'true' ? 'Отзыв скрыт' : 'Отзыв снова виден', 'ok');
          } catch (err) { toast(err.message, 'err'); }
          await load();
          return;
        } else if (b.dataset.reply) {
          const current = JSON.parse(feed.dataset.items || '[]').find((r) => String(r.id) === b.dataset.reply);
          openSheet(
            `<div class="stack">
               <h2 class="section__title" style="font-size:21px">Ответ столовой</h2>
               <textarea class="input" id="reply-text" maxlength="1000" placeholder="Спасибо за отзыв! …">${esc(current?.reply || '')}</textarea>
               <button class="btn" id="reply-send">Отправить</button>
               <button class="btn btn--ghost" id="reply-cancel">Отмена</button>
             </div>`,
            (sheet) => {
              sheet.querySelector('#reply-cancel').onclick = closeSheet;
              sheet.querySelector('#reply-send').onclick = async () => {
                const text = sheet.querySelector('#reply-text').value.trim();
                if (!text) { toast('Напишите ответ', 'err'); return; }
                try {
                  await api.post(`/api/staff/reviews/${b.dataset.reply}/reply`, { text });
                  toast('Ответ опубликован', 'ok');
                  closeSheet();
                  await load();
                } catch (err) { toast(err.message, 'err'); }
              };
            },
          );
          return;
        } else return;
        renderFilters();
        await load();
      });
    },
  };
}
