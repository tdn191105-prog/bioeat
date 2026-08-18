/* Меню столовой: поиск, категории, фильтры по диете.

   Категории не фильтруют список, а прокручивают к своей секции — меню читается
   как меню ресторана, а не как поисковая выдача. Активный чипс подсвечивается
   по той секции, что сейчас на экране. */
import api from '../api.js';
import { state, loadMenu, subscribe } from '../state.js';
import { esc, money, debounce, empty, skeletonList, TAG_LABELS, go } from '../ui.js';
import { dishRow, bindDishList } from '../components.js';

const DIET_TAGS = ['pp', 'veg', 'no_lactose', 'no_gluten', 'spicy'];

export default async function menuView(ctx) {
  const filters = {
    tag: ctx.query.get('tag') || '',
    q: '',
  };
  const startCategory = ctx.query.get('category') || '';
  let popular = [];

  return {
    title: 'Меню',
    html: `
      <div class="stack">
        <div class="searchbar">
          <span>🔍</span>
          <input id="search" type="search" placeholder="Найти блюдо" autocomplete="off" enterkeyhint="search">
        </div>
        <div class="menu-sticky">
          <div class="chips" id="cats"></div>
        </div>
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

      // подсказки для пустого поиска: реальные хиты, с откатом на тег
      api.get('/api/dishes/popular?limit=4')
        .then((list) => { popular = list; })
        .catch(() => {
          popular = state.dishes.filter((d) => (d.tags || []).includes('hit')).slice(0, 4);
        });

      let activeSlug = '';
      let onScroll = null;
      let ticking = false;

      const renderChips = () => {
        catsHost.innerHTML = state.categories
          .map(
            (c) => `<button class="chip ${activeSlug === c.slug ? 'is-active' : ''}" data-cat="${esc(c.slug)}">
                      ${esc(c.icon)} ${esc(c.name)}
                    </button>`,
          )
          .join('');

        tagsHost.innerHTML = DIET_TAGS.map(
          (t) => `<button class="chip chip--filter ${filters.tag === t ? 'is-active' : ''}" data-tag="${t}">
                    ${esc(TAG_LABELS[t])}
                  </button>`,
        ).join('');
      };

      /** Подсветить чипс активной категории и подтянуть его в видимую часть ленты. */
      const setActiveChip = (slug) => {
        if (slug === activeSlug) return;
        activeSlug = slug;
        catsHost.querySelectorAll('[data-cat]').forEach((chip) => {
          const on = chip.dataset.cat === slug;
          chip.classList.toggle('is-active', on);
          if (on) chip.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
        });
      };

      const filtered = () => {
        const query = filters.q.trim().toLowerCase();
        return state.dishes.filter((d) => {
          if (!d.is_active) return false;
          if (filters.tag && !(d.tags || []).includes(filters.tag)) return false;
          if (query && !d.name.toLowerCase().includes(query)
              && !(d.description || '').toLowerCase().includes(query)) {
            return false;
          }
          return true;
        });
      };

      const emptyStateHtml = () => `
        ${empty(
          '🔍',
          'Ничего не нашлось',
          'Попробуйте другой запрос или загляните в то, что чаще всего берут',
          '<button class="btn btn--ghost btn--sm mt-8" data-reset>Сбросить фильтры</button>',
        )}
        ${
          popular.length
            ? `<div class="suggest">
                 <div class="suggest__title">Часто заказывают</div>
                 ${popular.map(dishRow).join('')}
               </div>`
            : ''
        }`;

      const renderList = () => {
        const dishes = filtered();
        const searching = !!(filters.q.trim() || filters.tag);
        countHost.textContent = searching && dishes.length ? `Найдено: ${dishes.length}` : '';

        if (!dishes.length) {
          listHost.innerHTML = emptyStateHtml();
          const reset = listHost.querySelector('[data-reset]');
          if (reset) {
            reset.onclick = () => {
              filters.tag = '';
              filters.q = '';
              search.value = '';
              renderChips();
              renderList();
            };
          }
          return;
        }

        const groups = state.categories
          .map((cat) => ({ cat, items: dishes.filter((d) => d.category_id === cat.id) }))
          .filter((g) => g.items.length);

        listHost.innerHTML = groups
          .map(
            (g) => `
            <section class="cat-group" data-section="${esc(g.cat.slug)}">
              <div class="cat-head">
                <span>${esc(g.cat.icon)} ${esc(g.cat.name)}</span>
                <span class="cat-head__count">${g.items.length}</span>
              </div>
              ${g.items.map(dishRow).join('')}
            </section>`,
          )
          .join('');

        watchSections();
      };

      /* Активна та секция, которая пересекает линию под липкими чипсами:
         так подсветка всегда совпадает с тем заголовком, что виден сверху. */
      const LINE = 128;

      const pickActive = () => {
        const groups = [...listHost.querySelectorAll('[data-section]')];
        if (!groups.length) return;
        let current = groups[0];
        for (const group of groups) {
          if (group.getBoundingClientRect().top <= LINE) current = group;
        }
        setActiveChip(current.dataset.section);
      };

      const watchSections = () => {
        if (!onScroll) {
          onScroll = () => {
            if (ticking) return;
            ticking = true;
            requestAnimationFrame(() => { ticking = false; pickActive(); });
          };
          window.addEventListener('scroll', onScroll, { passive: true });
        }
        pickActive();
      };

      const scrollToCategory = (slug) => {
        const head = listHost.querySelector(`[data-section="${CSS.escape(slug)}"]`);
        if (!head) return;
        const top = head.getBoundingClientRect().top + window.scrollY - 104;
        window.scrollTo({ top, behavior: 'smooth' });
        setActiveChip(slug);
      };

      renderChips();
      renderList();
      if (startCategory) requestAnimationFrame(() => scrollToCategory(startCategory));

      catsHost.onclick = (e) => {
        const btn = e.target.closest('[data-cat]');
        if (btn) scrollToCategory(btn.dataset.cat);
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

      bindDishList(listHost, { onOpen: (id) => go(`#/dish/${id}`) });

      // перерисовываем степперы при изменении корзины
      const unsubscribe = subscribe(() => {
        if (!document.body.contains(listHost)) {
          if (onScroll) window.removeEventListener('scroll', onScroll);
          unsubscribe();
          return;
        }
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
