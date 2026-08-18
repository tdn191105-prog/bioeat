/* Меню столовой: поиск, категории, фильтры по диете. */
import { state, loadMenu, subscribe } from '../state.js';
import { esc, money, debounce, empty, skeletonList, TAG_LABELS, go } from '../ui.js';
import { dishRow, bindDishList, openDishSheet } from '../components.js';

const DIET_TAGS = ['pp', 'veg', 'no_lactose', 'no_gluten', 'spicy'];

export default async function menuView(ctx) {
  const filters = {
    category: ctx.query.get('category') || '',
    tag: ctx.query.get('tag') || '',
    q: '',
  };

  return {
    title: 'Меню',
    html: `
      <div class="stack">
        <div class="searchbar">
          <span>🔍</span>
          <input id="search" type="search" placeholder="Найти блюдо" autocomplete="off" enterkeyhint="search">
        </div>
        <div class="chips" id="cats"></div>
        <div class="chips" id="tags"></div>
        <div class="small muted" id="count" style="padding-left:4px"></div>
        <div class="dish-list" id="list">${skeletonList(6)}</div>
      </div>`,

    async mount(root) {
      await loadMenu();

      const listHost = root.querySelector('#list');
      const catsHost = root.querySelector('#cats');
      const tagsHost = root.querySelector('#tags');
      const countHost = root.querySelector('#count');
      const search = root.querySelector('#search');

      const renderChips = () => {
        catsHost.innerHTML = [
          `<button class="chip ${!filters.category ? 'is-active' : ''}" data-cat="">Всё меню</button>`,
          ...state.categories.map(
            (c) => `<button class="chip ${filters.category === c.slug ? 'is-active' : ''}" data-cat="${esc(c.slug)}">
                      ${esc(c.icon)} ${esc(c.name)}
                    </button>`,
          ),
        ].join('');

        tagsHost.innerHTML = DIET_TAGS.map(
          (t) => `<button class="chip chip--filter ${filters.tag === t ? 'is-active' : ''}" data-tag="${t}">
                    ${esc(TAG_LABELS[t])}
                  </button>`,
        ).join('');
      };

      const filtered = () => {
        const query = filters.q.trim().toLowerCase();
        return state.dishes.filter((d) => {
          if (!d.is_active) return false;
          if (filters.category) {
            const cat = state.categories.find((c) => c.id === d.category_id);
            if (!cat || cat.slug !== filters.category) return false;
          }
          if (filters.tag && !(d.tags || []).includes(filters.tag)) return false;
          if (query && !d.name.toLowerCase().includes(query) && !d.description.toLowerCase().includes(query)) {
            return false;
          }
          return true;
        });
      };

      const renderList = () => {
        const dishes = filtered();
        countHost.textContent = dishes.length
          ? `Найдено: ${dishes.length}`
          : '';

        if (!dishes.length) {
          listHost.innerHTML = empty(
            '🔍',
            'Ничего не нашлось',
            'Попробуйте изменить запрос или сбросить фильтры',
            '<button class="btn btn--ghost btn--sm mt-8" data-reset>Сбросить фильтры</button>',
          );
          const reset = listHost.querySelector('[data-reset]');
          if (reset) {
            reset.onclick = () => {
              filters.category = '';
              filters.tag = '';
              filters.q = '';
              search.value = '';
              renderChips();
              renderList();
            };
          }
          return;
        }

        // группируем по категориям, когда выбрано «Всё меню»
        if (!filters.category) {
          const groups = state.categories
            .map((cat) => ({ cat, items: dishes.filter((d) => d.category_id === cat.id) }))
            .filter((g) => g.items.length);
          listHost.innerHTML = groups
            .map(
              (g) => `
              <div style="padding:14px 4px 2px;font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.6px;color:var(--text-2)">
                ${esc(g.cat.icon)} ${esc(g.cat.name)}
              </div>
              ${g.items.map(dishRow).join('')}`,
            )
            .join('');
        } else {
          listHost.innerHTML = dishes.map(dishRow).join('');
        }
      };

      renderChips();
      renderList();

      catsHost.onclick = (e) => {
        const btn = e.target.closest('[data-cat]');
        if (!btn) return;
        filters.category = btn.dataset.cat;
        renderChips();
        renderList();
      };

      tagsHost.onclick = (e) => {
        const btn = e.target.closest('[data-tag]');
        if (!btn) return;
        filters.tag = filters.tag === btn.dataset.tag ? '' : btn.dataset.tag;
        renderChips();
        renderList();
      };

      search.addEventListener(
        'input',
        debounce((e) => {
          filters.q = e.target.value;
          renderList();
        }, 200),
      );

      bindDishList(listHost, { onOpen: openDishSheet });

      // перерисовываем степперы при изменении корзины
      const unsubscribe = subscribe(() => {
        if (!document.body.contains(listHost)) { unsubscribe(); return; }
        const scroll = window.scrollY;
        renderList();
        window.scrollTo(0, scroll);
      });
    },

    footer() {
      const { count, subtotal } = state.cart;
      if (!count) return '';
      return `<button class="btn" data-goto="#/cart">
                Корзина · ${count} ${count === 1 ? 'позиция' : 'поз.'} · ${money(subtotal)}
              </button>`;
    },
  };
}
