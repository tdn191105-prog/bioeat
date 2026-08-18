/* Монохромные иконки категорий — фолбэк, когда у блюда нет фотографии.

   Приложение обязано выглядеть достойно даже с пустой папкой static/img/dishes,
   поэтому вместо эмодзи рисуем иконку на градиенте категории.
   Все контуры — 24×24, stroke: currentColor, без заливки. */

const ICON_ATTRS =
  'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ' +
  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"';

/* Супница */
const SOUP = `
  <path d="M3.2 11.2h17.6a8.8 8.8 0 0 1-8.8 7.6 8.8 8.8 0 0 1-8.8-7.6z"/>
  <path d="M5.6 18.4h12.8"/>
  <path d="M12 8.6V7"/>
  <path d="M9 9.2c-.7-.8-.7-1.7 0-2.5s.7-1.7 0-2.5"/>
  <path d="M15 9.2c-.7-.8-.7-1.7 0-2.5s.7-1.7 0-2.5"/>`;

/* Курица — ножка */
const CHICKEN = `
  <path d="M13.4 4.2a4.6 4.6 0 0 1 5.9 5.9 4.2 4.2 0 0 1-4.5 2.7l-3 3"/>
  <path d="M11.8 15.8 8.4 19.2"/>
  <circle cx="7" cy="17" r="2.2"/>
  <circle cx="9.6" cy="19.6" r="1.6"/>`;

/* Миска с крупой */
const GRAIN = `
  <path d="M3.4 12h17.2a8.6 8.6 0 0 1-17.2 0z"/>
  <path d="M12 12V9.4"/>
  <path d="M12 9.4c-1.5 0-2.4-.9-2.4-2.4 1.5 0 2.4.9 2.4 2.4z"/>
  <path d="M12 9.4c1.5 0 2.4-.9 2.4-2.4-1.5 0-2.4.9-2.4 2.4z"/>
  <path d="M6.6 18.6h10.8"/>`;

/* Лист салата */
const LEAF = `
  <path d="M20 4.4c0 8-4.6 12.4-11 12.4-2 0-3.4-.5-4.4-1.2C3.8 8.6 9.4 4.4 20 4.4z"/>
  <path d="M4 20c1.6-3.6 4.4-6.6 8.4-8.6"/>`;

/* Круассан */
const CROISSANT = `
  <path d="M3 15.4c2.6-6.4 9-9.6 15.6-8.2C20 7.6 21 8.8 21 10.4c0 3.6-4.4 7-9.6 7-3.6 0-6.6-.8-8.4-2z"/>
  <path d="M8.6 8.4 7.4 15.6"/>
  <path d="M12.6 7.2l.8 9.6"/>
  <path d="M16.6 7.6l2.4 7.4"/>`;

/* Стакан */
const GLASS = `
  <path d="M6.4 4.4h11.2l-1.4 14.2a1.8 1.8 0 0 1-1.8 1.6H9.6a1.8 1.8 0 0 1-1.8-1.6z"/>
  <path d="M7 10.8h10"/>
  <path d="M14.4 4.4 12.4 1.8"/>`;

/* Кекс */
const CUPCAKE = `
  <path d="M5.6 12.6h12.8l-1.3 7a1.6 1.6 0 0 1-1.6 1.3H8.5a1.6 1.6 0 0 1-1.6-1.3z"/>
  <path d="M6.8 12.6a3.4 3.4 0 0 1 1.4-5.2 3.8 3.8 0 0 1 7.6 0 3.4 3.4 0 0 1 1.4 5.2"/>
  <path d="M10.4 15.4l-.6 5.5M13.6 15.4l.6 5.5"/>`;

/* Ланчбокс */
const BENTO = `
  <rect x="3.2" y="7.2" width="17.6" height="12.4" rx="2.6"/>
  <path d="M3.2 12.4h17.6"/>
  <path d="M12 12.4v7.2"/>
  <path d="M8.6 7.2V5.6a1.8 1.8 0 0 1 1.8-1.8h3.2a1.8 1.8 0 0 1 1.8 1.8v1.6"/>`;

const BY_SLUG = {
  combo: BENTO,
  soups: SOUP,
  hot: CHICKEN,
  sides: GRAIN,
  salads: LEAF,
  bakery: CROISSANT,
  drinks: GLASS,
  desserts: CUPCAKE,
};

/* Для категорий, добавленных администратором, берём нейтральную миску. */
const DEFAULT_ICON = GRAIN;

/** SVG-иконка категории по её слагу. */
export function categoryIcon(slug) {
  return `<svg class="cat-ico" ${ICON_ATTRS}>${BY_SLUG[slug] || DEFAULT_ICON}</svg>`;
}

export const CATEGORY_ICON_SLUGS = Object.keys(BY_SLUG);
