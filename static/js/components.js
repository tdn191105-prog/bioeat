/* Переиспользуемые куски интерфейса. */
import api from './api.js';
import { state, cartQty, setCart } from './state.js';
import { esc, money, toast, TAG_LABELS, vibrate } from './ui.js';
import { categoryIcon } from './icons.js';

const CATEGORY_GRADIENTS = {
  combo: 'linear-gradient(135deg,#1f5bff,#4a86ff)',
  soups: 'linear-gradient(135deg,#d9641f,#f0913c)',
  hot: 'linear-gradient(135deg,#c33a34,#e4574c)',
  sides: 'linear-gradient(135deg,#2f9d63,#4cc38a)',
  salads: 'linear-gradient(135deg,#1f9179,#2fb894)',
  bakery: 'linear-gradient(135deg,#d29a12,#f0b429)',
  drinks: 'linear-gradient(135deg,#2792ab,#3fb8d4)',
  desserts: 'linear-gradient(135deg,#8f34a8,#b74cd4)',
};

const categoryOf = (dish) => state.categories.find((c) => c.id === dish.category_id);

export const dishGradient = (dish) => {
  const cat = categoryOf(dish);
  return CATEGORY_GRADIENTS[cat?.slug] || `linear-gradient(135deg,${cat?.color || '#2f6bff'},#4a86ff)`;
};

/** Заглушка вместо фото: иконка категории на её градиенте. */
export function dishFallback(dish) {
  const cat = categoryOf(dish);
  return `<span class="dish-img__fallback" style="background:${dishGradient(dish)}">
            ${categoryIcon(cat?.slug)}
          </span>`;
}

/**
 * Превью блюда для списков.
 * Ширина и высота заданы жёстко, контейнеру задан aspect-ratio —
 * при загрузке фото вёрстка не «дёргается».
 */
export function dishThumb(dish, { sizes = '', width = 400, height = 300 } = {}) {
  const bg = dish.image_placeholder ? ` style="background:${esc(dish.image_placeholder)}"` : '';
  if (!dish.image_thumb_url) {
    return `<span class="dish-img"${bg}>${dishFallback(dish)}</span>`;
  }
  return `<span class="dish-img"${bg}>
            <img src="${esc(dish.image_thumb_url)}" alt="${esc(dish.name)}"
                 loading="lazy" decoding="async" width="${width}" height="${height}"
                 ${sizes ? `sizes="${esc(sizes)}"` : ''}>
          </span>`;
}

/** Большое фото в шапке карточки блюда. */
export function dishHero(dish) {
  const bg = dish.image_placeholder ? ` style="background:${esc(dish.image_placeholder)}"` : '';
  if (!dish.image_url) {
    return `<span class="dish-img dish-img--hero"${bg}>${dishFallback(dish)}</span>`;
  }
  return `<span class="dish-img dish-img--hero"${bg}>
            <img src="${esc(dish.image_url)}" alt="${esc(dish.name)}"
                 decoding="async" fetchpriority="high" width="800" height="600">
          </span>`;
}

/**
 * Маленькое превью для корзины, состава заказа и очереди оператора.
 * Позиция заказа хранит снимок ссылки на фото, поэтому объект может быть
 * не блюдом из меню, а строкой заказа — поля те же.
 */
export function itemThumb(item) {
  const shape = { category_id: item.category_id ?? 0, name: item.name, ...item };
  const bg = item.image_placeholder ? ` style="background:${esc(item.image_placeholder)}"` : '';
  if (!item.image_thumb_url) {
    return `<span class="dish-img dish-img--mini"${bg}>${dishFallback(shape)}</span>`;
  }
  return `<span class="dish-img dish-img--mini"${bg}>
            <img src="${esc(item.image_thumb_url)}" alt="${esc(item.name)}"
                 loading="lazy" decoding="async" width="400" height="300">
          </span>`;
}

export const tagsHtml = (tags = []) =>
  tags.length
    ? `<div class="tag-row">${tags
        .map((t) => `<span class="tag tag--${esc(t)}">${esc(TAG_LABELS[t] || t)}</span>`)
        .join('')}</div>`
    : '';

/** Карточка блюда в списке меню. */
export function dishRow(dish) {
  const qty = cartQty(dish.id);
  const out = !dish.is_active || dish.stock_qty <= 0;
  return `
  <a class="dish ${out ? 'dish--out' : ''}" data-dish="${dish.id}" href="#/dish/${dish.id}">
    ${dishThumb(dish, { sizes: '(min-width: 700px) 96px, 78px' })}
    <div class="dish__body">
      <div class="dish__name">${esc(dish.name)}</div>
      <div class="dish__meta">${dish.weight_g ? `${dish.weight_g} г · ` : ''}${dish.kcal} ккал${
        out ? ' · нет в наличии' : dish.stock_qty <= 5 ? ` · осталось ${dish.stock_qty}` : ''
      }</div>
      ${tagsHtml(dish.tags)}
      <div class="dish__price">${money(dish.price)}</div>
    </div>
    <div class="dish__side">
      ${
        out
          ? '<span class="tag">Стоп-лист</span>'
          : qty > 0
            ? `<div class="stepper" data-stepper="${dish.id}">
                 <button type="button" data-minus aria-label="Убрать одну порцию">−</button>
                 <span class="stepper__val">${qty}</span>
                 <button type="button" data-plus aria-label="Добавить порцию" ${qty >= dish.stock_qty ? 'disabled' : ''}>+</button>
               </div>`
            : `<button type="button" class="add-btn" data-add="${dish.id}" aria-label="Добавить в корзину">+</button>`
      }
    </div>
  </a>`;
}

/** Изменение количества с оптимистичным откликом. */
export async function changeQty(dishId, qty) {
  try {
    const cart = await api.put('/api/cart/items', { dish_id: dishId, qty });
    setCart(cart);
    vibrate();
    return true;
  } catch (err) {
    if (err.status === 401) {
      toast('Войдите, чтобы собрать заказ', 'err');
      window.location.hash = '#/login';
    } else {
      toast(err.message, 'err');
    }
    return false;
  }
}

/** Обработчик кликов по спискам блюд — вешается один раз на контейнер. */
export function bindDishList(root, { onOpen } = {}) {
  root.addEventListener('click', async (event) => {
    const addBtn = event.target.closest('[data-add]');
    if (addBtn) {
      event.preventDefault();
      event.stopPropagation();
      await changeQty(Number(addBtn.dataset.add), 1);
      return;
    }
    const stepper = event.target.closest('[data-stepper]');
    if (stepper) {
      const id = Number(stepper.dataset.stepper);
      const current = cartQty(id);
      if (event.target.closest('[data-plus]')) {
        event.preventDefault();
        event.stopPropagation();
        await changeQty(id, current + 1);
        return;
      }
      if (event.target.closest('[data-minus]')) {
        event.preventDefault();
        event.stopPropagation();
        await changeQty(id, current - 1);
        return;
      }
    }
    const card = event.target.closest('[data-dish]');
    if (card && onOpen) {
      event.preventDefault();
      onOpen(Number(card.dataset.dish));
    }
  });
}

/** Плашка статуса заказа. */
export const statusPill = (order) =>
  `<span class="status-pill status-pill--${esc(order.status)}">${esc(order.status_label)}</span>`;

/** Короткое перечисление состава заказа. */
export const orderSummary = (order) =>
  order.items.map((i) => `${esc(i.name)}${i.qty > 1 ? ` ×${i.qty}` : ''}`).join(' · ');

/* ------------------------------- Отзывы ---------------------------------- */
let reviewTagsCache = null;
export async function reviewTags() {
  if (!reviewTagsCache) reviewTagsCache = await api.get('/api/reviews/tags');
  return reviewTagsCache;
}

export const starsHtml = (rating, cls = '') =>
  `<span class="stars ${cls}" aria-label="Оценка ${rating} из 5">${[1, 2, 3, 4, 5]
    .map((n) => `<span class="${n <= rating ? 'is-on' : ''}">★</span>`)
    .join('')}</span>`;

/** Готовый отзыв: звёзды, теги, текст и ответ столовой. */
export function reviewCard(review, { actions = '' } = {}) {
  return `
    <div class="review">
      <div class="hstack">
        ${starsHtml(review.rating)}
        <div class="spacer"></div>
        <span class="small muted">${esc(review.author)}${review.order_number ? ` · ${esc(review.order_number)}` : ''}</span>
      </div>
      ${review.tag_labels.length ? `<div class="tag-row" style="margin-top:8px">${review.tag_labels.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>` : ''}
      ${review.text ? `<div class="review__text">${esc(review.text)}</div>` : ''}
      ${review.staff_reply ? `<div class="review__reply"><b>Ответ столовой:</b> ${esc(review.staff_reply)}</div>` : ''}
      ${actions}
    </div>`;
}

/**
 * Форма «Как вам заказ?»: звёзды, теги, текст, анонимность.
 * existing — отзыв для редактирования (24 часа после публикации).
 */
export async function mountReviewForm(host, { orderId = null, existing = null, rating = 0, onSaved } = {}) {
  const tags = await reviewTags();
  const form = {
    rating: existing ? existing.rating : rating,
    tags: new Set(existing ? existing.tags : []),
    text: existing ? existing.text : '',
    anon: existing ? existing.is_anonymous : false,
  };
  const hint = ['', 'Очень плохо', 'Плохо', 'Нормально', 'Хорошо', 'Отлично!'];

  const draw = () => {
    // хорошие теги — к высокой оценке, жалобы — к низкой; выбранные видны всегда
    const visible = tags.filter((t) => !form.rating || form.tags.has(t.code)
      || (form.rating >= 4 ? t.positive : form.rating <= 2 ? !t.positive : true));
    host.innerHTML = `
      <div class="stack">
        <div class="star-input" role="radiogroup" aria-label="Оценка">
          ${[1, 2, 3, 4, 5].map((n) => `<button type="button" role="radio" aria-checked="${form.rating === n}"
               aria-label="${n} из 5" class="${n <= form.rating ? 'is-on' : ''}" data-star="${n}">★</button>`).join('')}
        </div>
        <div class="small muted center">${esc(hint[form.rating] || 'Нажмите на звезду')}</div>
        ${form.rating ? `
          <div class="chips chips--wrap">
            ${visible.map((t) => `<button type="button" class="chip ${form.tags.has(t.code) ? 'is-active' : ''}" data-tag="${t.code}">${esc(t.label)}</button>`).join('')}
          </div>
          <textarea class="input" maxlength="1000" data-text placeholder="Что понравилось или что исправить? Необязательно">${esc(form.text)}</textarea>
          <button type="button" class="option ${form.anon ? 'is-active' : ''}" data-anon>
            <span class="option__ico">🙈</span>
            <span class="option__body"><span class="option__title">Анонимно</span>
            <span class="option__sub">Столовая не увидит ваше имя и группу</span></span>
            <span class="switch ${form.anon ? 'is-on' : ''}"></span>
          </button>
          <button type="button" class="btn" data-send>${existing ? 'Сохранить отзыв' : 'Отправить отзыв'}</button>` : ''}
      </div>`;
    const text = host.querySelector('[data-text]');
    if (text) text.oninput = () => { form.text = text.value; };
  };
  draw();

  host.onclick = async (event) => {
    const star = event.target.closest('[data-star]');
    if (star) { form.rating = Number(star.dataset.star); vibrate(); draw(); return; }
    const tag = event.target.closest('[data-tag]');
    if (tag) {
      if (form.tags.has(tag.dataset.tag)) form.tags.delete(tag.dataset.tag); else form.tags.add(tag.dataset.tag);
      draw();
      return;
    }
    if (event.target.closest('[data-anon]')) { form.anon = !form.anon; draw(); return; }
    const send = event.target.closest('[data-send]');
    if (!send) return;
    send.disabled = true;
    const body = { rating: form.rating, tags: [...form.tags], text: form.text.trim(), is_anonymous: form.anon };
    try {
      const saved = existing
        ? await api.patch(`/api/reviews/${existing.id}`, body)
        : await api.post('/api/reviews', { ...body, order_id: orderId });
      toast(existing ? 'Отзыв обновлён' : 'Спасибо за отзыв!', 'ok');
      if (onSaved) onSaved(saved);
    } catch (err) {
      toast(err.message, 'err');
      send.disabled = false;
    }
  };
}
