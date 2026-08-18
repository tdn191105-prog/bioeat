/* Карточка блюда: состав, аллергены, пищевая ценность, похожие позиции.

   Отдельный экран, а не нижний лист: на карточку можно дать ссылку,
   а на десктопе лист выглядел бы неуместно. */
import api from '../api.js';
import { state, loadMenu, cartQty, subscribe } from '../state.js';
import { esc, money, toast, go, plural, TAG_LABELS } from '../ui.js';
import { changeQty, dishHero, dishThumb, tagsHtml } from '../components.js';

/* Ориентир суточной нормы взрослого — тот же, что в app/reference.py */
const DAILY_NORMS = { kcal: 2000, protein: 75, fat: 70, carbs: 260 };

let allergenBook = null;

async function loadAllergens() {
  if (allergenBook) return allergenBook;
  try {
    const list = await api.get('/api/reference/allergens');
    allergenBook = Object.fromEntries(list.map((a) => [a.code, a]));
  } catch {
    allergenBook = {}; // справочник не критичен — покажем сами коды
  }
  return allergenBook;
}

/* ------------------------------ Блоки экрана ------------------------------ */
function ingredientsHtml(dish) {
  if (!dish.ingredients || !dish.ingredients.length) {
    return `<section class="section">
              <div class="section__head"><h2 class="section__title">Состав</h2></div>
              <p class="muted small" style="margin:0">Состав уточняется у повара.</p>
            </section>`;
  }
  return `
    <section class="section">
      <div class="section__head"><h2 class="section__title">Состав</h2></div>
      <ul class="ingredients">
        ${dish.ingredients.map((i) => `<li>${esc(i)}</li>`).join('')}
      </ul>
    </section>`;
}

function allergensHtml(dish, book) {
  const codes = dish.allergens || [];
  if (!codes.length) {
    return `
      <section class="section">
        <div class="section__head"><h2 class="section__title">Аллергены</h2></div>
        <div class="allergen-none">
          <span class="allergen-none__mark">✓</span>
          <span>Аллергенов из перечня ТР ТС 022/2011 не заявлено.</span>
        </div>
      </section>`;
  }
  return `
    <section class="section">
      <div class="section__head"><h2 class="section__title">Аллергены</h2></div>
      <div class="allergen-note">
        <div class="allergen-note__row">
          ${codes
            .map((code) => {
              const a = book[code] || { short: code, icon: '⚠️', name: code, note: '' };
              return `<span class="allergen" title="${esc(a.note || a.name)}">
                        <span class="allergen__ico">${esc(a.icon)}</span>${esc(a.short || a.name)}
                      </span>`;
            })
            .join('')}
        </div>
        <p class="allergen-note__text">
          Содержит: ${codes.map((c) => esc((book[c] || {}).name || c)).join(', ').toLowerCase()}.
          Если сомневаетесь — уточните у повара на выдаче.
        </p>
      </div>
    </section>`;
}

function nutritionHtml(dish) {
  const rows = [
    { label: 'Белки', value: Number(dish.protein), norm: DAILY_NORMS.protein, unit: 'г', color: 'var(--green)' },
    { label: 'Жиры', value: Number(dish.fat), norm: DAILY_NORMS.fat, unit: 'г', color: 'var(--yellow)' },
    { label: 'Углеводы', value: Number(dish.carbs), norm: DAILY_NORMS.carbs, unit: 'г', color: 'var(--orange)' },
    { label: 'Калорийность', value: Number(dish.kcal), norm: DAILY_NORMS.kcal, unit: 'ккал', color: 'var(--accent)' },
  ];
  return `
    <section class="section">
      <div class="section__head"><h2 class="section__title">Пищевая ценность</h2></div>
      <div class="nutrition">
        ${rows
          .map((r) => {
            const percent = r.norm ? Math.round((r.value / r.norm) * 100) : 0;
            return `
            <div class="nutri">
              <div class="nutri__head">
                <span class="nutri__label">${esc(r.label)}</span>
                <span class="nutri__value">${r.value} ${esc(r.unit)}</span>
                <span class="nutri__percent">${percent}%</span>
              </div>
              <div class="nutri__track">
                <span class="nutri__fill" style="width:${Math.min(100, percent)}%;background:${r.color}"></span>
              </div>
            </div>`;
          })
          .join('')}
      </div>
      <p class="small muted" style="margin:12px 0 0">
        Процент — доля от ориентировочной суточной нормы взрослого:
        ${DAILY_NORMS.kcal} ккал, белки ${DAILY_NORMS.protein} г, жиры ${DAILY_NORMS.fat} г,
        углеводы ${DAILY_NORMS.carbs} г. Личная норма зависит от возраста и нагрузки.
      </p>
    </section>`;
}

function similarHtml(dish) {
  const similar = state.dishes
    .filter((d) => d.category_id === dish.category_id && d.id !== dish.id && d.is_active)
    .slice(0, 6);
  if (!similar.length) return '';

  return `
    <section class="section">
      <div class="section__head"><h2 class="section__title">Похожие блюда</h2></div>
      <div class="carousel similar">
        ${similar
          .map(
            (d) => `
          <a class="similar__card" href="#/dish/${d.id}">
            <div class="similar__media">${dishThumb(d, { sizes: '160px' })}</div>
            <div class="similar__name">${esc(d.name)}</div>
            <div class="similar__price">${money(d.price)}</div>
          </a>`,
          )
          .join('')}
      </div>
    </section>`;
}

function creditHtml(dish) {
  if (!dish.image_url || (!dish.image_author && !dish.image_license)) return '';
  const author = dish.image_author || 'автор не указан';
  const license = dish.image_license ? ` · ${esc(dish.image_license)}` : '';
  const link = dish.image_source_url
    ? ` · <a href="${esc(dish.image_source_url)}" target="_blank" rel="noreferrer noopener">первоисточник</a>`
    : '';
  return `<p class="photo-credit">Фото: ${esc(author)}${license}${link}</p>`;
}

/* --------------------------------- Экран ---------------------------------- */
export default async function dishView(ctx) {
  const dishId = Number(ctx.params.id);
  await loadMenu();

  let dish = state.dishes.find((d) => d.id === dishId);
  if (!dish) {
    // блюдо может быть скрыто из общего списка — тянем напрямую
    try {
      dish = await api.get(`/api/dishes/${dishId}`);
    } catch {
      return {
        title: 'Блюдо',
        html: '',
        mount: () => { toast('Блюдо не найдено', 'err'); go('#/menu'); },
      };
    }
  }

  const book = await loadAllergens();
  const out = () => !dish.is_active || dish.stock_qty <= 0;

  return {
    title: dish.name,
    html: `
      <article class="dish-page">
        <div class="dish-hero">
          ${dishHero(dish)}
          <button class="dish-hero__back" type="button" data-back aria-label="Назад к меню">←</button>
        </div>

        <div class="stack">
          <section class="section">
            <h1 class="dish-page__name">${esc(dish.name)}</h1>
            <div class="dish-page__meta" id="dish-meta"></div>
            <div class="dish-page__price-row">
              <span class="dish-page__price">${money(dish.price)}</span>
              ${tagsHtml(dish.tags)}
            </div>
            ${dish.description ? `<p class="dish-page__desc">${esc(dish.description)}</p>` : ''}
          </section>

          ${ingredientsHtml(dish)}
          ${allergensHtml(dish, book)}
          ${nutritionHtml(dish)}
          ${similarHtml(dish)}
          ${creditHtml(dish)}
        </div>
      </article>`,

    async mount(root) {
      const meta = root.querySelector('#dish-meta');

      const renderMeta = () => {
        const parts = [];
        if (dish.weight_g) parts.push(`${dish.weight_g} г`);
        parts.push(`${dish.kcal} ккал`);
        parts.push(
          out()
            ? 'сегодня закончилось'
            : `осталось ${dish.stock_qty} ${plural(dish.stock_qty, 'порция', 'порции', 'порций')}`,
        );
        meta.innerHTML = parts.map((p) => `<span>${esc(p)}</span>`).join('<i>·</i>');
        meta.classList.toggle('is-out', out());
      };
      renderMeta();

      root.querySelector('[data-back]').onclick = () => window.history.back();

      // корзину мог изменить кто-то ещё (другая вкладка, футер) — держим кнопку в тонусе
      const unsubscribe = subscribe(() => {
        if (!document.body.contains(meta)) { unsubscribe(); return; }
        renderMeta();
      });
    },

    /* Липкая нижняя панель: степпер + сумма */
    footer() {
      if (out()) return '<button class="btn" disabled>Сегодня закончилось</button>';
      const qty = cartQty(dish.id) || 1;
      const capped = Math.min(qty, dish.stock_qty);
      return `
        <div class="buy-bar">
          <div class="stepper stepper--lg" data-buy-stepper>
            <button type="button" data-minus aria-label="Меньше" ${capped <= 1 ? 'disabled' : ''}>−</button>
            <span class="stepper__val" data-qty>${capped}</span>
            <button type="button" data-plus aria-label="Больше" ${capped >= dish.stock_qty ? 'disabled' : ''}>+</button>
          </div>
          <button class="btn" data-buy>
            ${cartQty(dish.id) ? 'Обновить корзину' : 'Добавить в корзину'} · ${money(dish.price * capped)}
          </button>
        </div>`;
    },

    async onFooterClick(event) {
      const bar = event.currentTarget || document.getElementById('action-bar');
      const valueHost = bar.querySelector('[data-qty]');
      if (!valueHost) return;
      let qty = Number(valueHost.textContent) || 1;

      if (event.target.closest('[data-minus]')) qty = Math.max(1, qty - 1);
      else if (event.target.closest('[data-plus]')) qty = Math.min(dish.stock_qty, qty + 1);
      else if (event.target.closest('[data-buy]')) {
        const button = event.target.closest('[data-buy]');
        button.disabled = true;
        const ok = await changeQty(dish.id, qty);
        button.disabled = false;
        if (ok) toast(`«${dish.name}» в корзине · ${qty} шт.`, 'ok');
        return;
      } else return;

      // локально пересчитываем панель, не дёргая сервер на каждый щелчок
      valueHost.textContent = String(qty);
      bar.querySelector('[data-minus]').disabled = qty <= 1;
      bar.querySelector('[data-plus]').disabled = qty >= dish.stock_qty;
      const buy = bar.querySelector('[data-buy]');
      buy.innerHTML = `${cartQty(dish.id) ? 'Обновить корзину' : 'Добавить в корзину'} · ${money(dish.price * qty)}`;
    },
  };
}

export { TAG_LABELS };
