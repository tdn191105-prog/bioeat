/* Админ-панель: меню, категории, окна выдачи, сотрудники, отчёты. */
import api, { auth, ApiError } from '../api.js';
import { loadMenu, state } from '../state.js';
import { dishThumb } from '../components.js';
import {
  esc, money, toast, openSheet, closeSheet, confirmSheet, skeletonList, empty,
  TAG_LABELS, isoDate, dateLabel,
} from '../ui.js';

const TABS = [
  { key: 'menu', label: 'Меню', icon: '🍲' },
  { key: 'categories', label: 'Категории', icon: '🗂' },
  { key: 'slots', label: 'Окна выдачи', icon: '🕐' },
  { key: 'stats', label: 'Отчёты', icon: '📊' },
  { key: 'staff', label: 'Сотрудники', icon: '👥' },
];

const ALL_TAGS = ['pp', 'veg', 'no_lactose', 'no_gluten', 'spicy', 'hit'];

/** Загрузка фото — multipart, поэтому мимо обёртки api (она шлёт JSON). */
async function uploadDishImage(dishId, file) {
  const body = new FormData();
  body.append('file', file);
  const headers = {};
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;

  let response;
  try {
    response = await fetch(`/api/admin/dishes/${dishId}/image`, { method: 'POST', headers, body });
  } catch {
    throw new ApiError('Нет связи с сервером. Проверьте подключение.', 0);
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError((payload && payload.detail) || 'Не удалось загрузить фото', response.status);
  }
  return payload;
}

const ICONS = ['🍲','🍗','🥗','🍚','🥐','☕','🍰','🍱','🍜','🥘','🍕','🌭','🥞','🍎','🥛','💧','🍪','🐟','🥩','🍟','🥦','🥕','🫒','🍫','🍹','🧀','🥟','🍳','🥙','🎃'];

export default async function adminView() {
  let tab = 'menu';
  let categories = [];
  // справочник аллергенов тянем с сервера, чтобы названия не дублировались
  let allergenBook = [];
  try {
    allergenBook = await api.get('/api/reference/allergens');
  } catch {
    allergenBook = [];
  }

  return {
    title: 'Админ-панель',
    wide: true,
    requiresAuth: true,
    roles: ['admin'],
    html: `
      <div class="stack">
        <div class="chips" id="tabs"></div>
        <div id="panel">${skeletonList(4, 70)}</div>
      </div>`,

    async mount(root) {
      const tabsHost = root.querySelector('#tabs');
      const panel = root.querySelector('#panel');

      const renderTabs = () => {
        tabsHost.innerHTML = TABS.map(
          (t) => `<button class="chip ${tab === t.key ? 'is-active' : ''}" data-tab="${t.key}">${t.icon} ${esc(t.label)}</button>`,
        ).join('');
      };

      /* ----------------------------- Меню ---------------------------------- */
      const dishForm = (dish = null) => {
        const allergens = allergenBook;
        const isNew = !dish;
        const value = dish || {
          category_id: categories[0]?.id, name: '', description: '', price: '',
          weight_g: 0, kcal: 0, protein: 0, fat: 0, carbs: 0, icon: '🍲',
          tags: [], stock_qty: 50, is_active: true, sort_order: 0,
        };
        let selectedTags = [...(value.tags || [])];
        let selectedAllergens = [...(value.allergens || [])];
        let selectedIcon = value.icon;
        let current = dish;

        openSheet(
          `<div class="stack">
            <h2 class="section__title" style="font-size:21px">${isNew ? 'Новое блюдо' : 'Редактирование'}</h2>
            <div class="field">
              <span class="field__label">Иконка</span>
              <div class="chips" id="icons">
                ${ICONS.map((i) => `<button type="button" class="chip ${i === selectedIcon ? 'is-active' : ''}" data-icon="${i}" style="font-size:19px">${i}</button>`).join('')}
              </div>
            </div>
            <div class="field">
              <label class="field__label" for="f-name">Название</label>
              <input class="input" id="f-name" value="${esc(value.name)}" placeholder="Борщ с говядиной">
            </div>
            <div class="field">
              <label class="field__label" for="f-cat">Категория</label>
              <select class="input" id="f-cat">
                ${categories.map((c) => `<option value="${c.id}" ${c.id === value.category_id ? 'selected' : ''}>${esc(c.icon)} ${esc(c.name)}</option>`).join('')}
              </select>
            </div>
            <div class="field">
              <label class="field__label" for="f-desc">Описание</label>
              <textarea class="input" id="f-desc" placeholder="Состав и особенности">${esc(value.description)}</textarea>
            </div>
            <div class="grid-2">
              <div class="field">
                <label class="field__label" for="f-price">Цена, ₽</label>
                <input class="input" id="f-price" type="number" inputmode="decimal" min="0" step="1" value="${Number(value.price) || ''}">
              </div>
              <div class="field">
                <label class="field__label" for="f-stock">Порций на день</label>
                <input class="input" id="f-stock" type="number" inputmode="numeric" min="0" value="${value.stock_qty}">
              </div>
            </div>
            <div class="grid-2">
              <div class="field">
                <label class="field__label" for="f-weight">Вес, г</label>
                <input class="input" id="f-weight" type="number" inputmode="numeric" min="0" value="${value.weight_g}">
              </div>
              <div class="field">
                <label class="field__label" for="f-kcal">Ккал</label>
                <input class="input" id="f-kcal" type="number" inputmode="numeric" min="0" value="${value.kcal}">
              </div>
            </div>
            <div class="grid-3">
              <div class="field">
                <label class="field__label" for="f-p">Белки</label>
                <input class="input" id="f-p" type="number" inputmode="decimal" min="0" step="0.1" value="${Number(value.protein)}">
              </div>
              <div class="field">
                <label class="field__label" for="f-f">Жиры</label>
                <input class="input" id="f-f" type="number" inputmode="decimal" min="0" step="0.1" value="${Number(value.fat)}">
              </div>
              <div class="field">
                <label class="field__label" for="f-c">Углеводы</label>
                <input class="input" id="f-c" type="number" inputmode="decimal" min="0" step="0.1" value="${Number(value.carbs)}">
              </div>
            </div>
            ${
              isNew
                ? `<div class="small muted" style="padding-left:2px">
                     Фотографию можно будет загрузить сразу после сохранения блюда.
                   </div>`
                : `<div class="field">
                     <span class="field__label">Фотография</span>
                     <div class="img-upload" id="f-image">
                       <div class="img-upload__preview" id="f-image-preview"></div>
                       <div class="img-upload__actions">
                         <input type="file" id="f-image-file" accept="image/jpeg,image/png,image/webp">
                         <button type="button" class="btn btn--ghost btn--sm" id="f-image-pick" style="width:100%">
                           Загрузить фото
                         </button>
                         <button type="button" class="btn btn--danger btn--sm" id="f-image-del" style="width:100%">
                           Убрать фото
                         </button>
                         <div class="img-upload__hint">
                           JPEG, PNG или WebP до 8 МБ. Обрежем по центру до 4:3
                           и сохраним в WebP двумя размерами.
                         </div>
                       </div>
                     </div>
                   </div>`
            }
            <div class="field">
              <span class="field__label">Метки диеты</span>
              <div class="chips" id="f-tags">
                ${ALL_TAGS.map((t) => `<button type="button" class="chip chip--filter ${selectedTags.includes(t) ? 'is-active' : ''}" data-tag="${t}">${esc(TAG_LABELS[t])}</button>`).join('')}
              </div>
            </div>
            <div class="field">
              <label class="field__label" for="f-ingredients">Состав — по одному ингредиенту в строке</label>
              <textarea class="input" id="f-ingredients" rows="5"
                placeholder="говядина&#10;свёкла&#10;картофель">${esc((value.ingredients || []).join('\n'))}</textarea>
            </div>
            <div class="field">
              <span class="field__label">Аллергены по ТР ТС 022/2011</span>
              <div class="chips" id="f-allergens">
                ${allergens
                  .map(
                    (a) => `<button type="button" class="chip ${selectedAllergens.includes(a.code) ? 'is-active' : ''}"
                                    data-allergen="${esc(a.code)}">${esc(a.icon)} ${esc(a.short)}</button>`,
                  )
                  .join('')}
              </div>
            </div>
            <button class="btn" id="f-save">${isNew ? 'Добавить в меню' : 'Сохранить'}</button>
            <button class="btn btn--ghost" id="f-cancel">Отмена</button>
          </div>`,
          (sheet) => {
            sheet.querySelector('#icons').onclick = (e) => {
              const btn = e.target.closest('[data-icon]');
              if (!btn) return;
              selectedIcon = btn.dataset.icon;
              sheet.querySelectorAll('[data-icon]').forEach((b) =>
                b.classList.toggle('is-active', b.dataset.icon === selectedIcon));
            };
            /* --- фотография --- */
            const imageHost = sheet.querySelector('#f-image-preview');
            const renderImage = () => {
              if (!imageHost) return;
              imageHost.innerHTML = dishThumb(current, { width: 400, height: 300 });
              const del = sheet.querySelector('#f-image-del');
              if (del) del.disabled = !current.image_url;
            };
            renderImage();

            const fileInput = sheet.querySelector('#f-image-file');
            const pick = sheet.querySelector('#f-image-pick');
            if (pick && fileInput) {
              pick.onclick = () => fileInput.click();
              fileInput.onchange = async () => {
                const file = fileInput.files && fileInput.files[0];
                if (!file) return;
                pick.disabled = true;
                pick.textContent = 'Загружаем…';
                try {
                  current = await uploadDishImage(current.id, file);
                  renderImage();
                  toast('Фотография обновлена', 'ok');
                  await loadMenu(true);
                } catch (err) {
                  toast(err.message, 'err');
                } finally {
                  pick.disabled = false;
                  pick.textContent = 'Загрузить фото';
                  fileInput.value = '';
                }
              };
            }

            const delImage = sheet.querySelector('#f-image-del');
            if (delImage) {
              delImage.onclick = async () => {
                delImage.disabled = true;
                try {
                  current = await api.del(`/api/admin/dishes/${current.id}/image`);
                  renderImage();
                  toast('Фото убрано — покажем иконку категории', 'ok');
                  await loadMenu(true);
                } catch (err) {
                  toast(err.message, 'err');
                  delImage.disabled = false;
                }
              };
            }

            const allergensHost = sheet.querySelector('#f-allergens');
            if (allergensHost) {
              allergensHost.onclick = (e) => {
                const btn = e.target.closest('[data-allergen]');
                if (!btn) return;
                const code = btn.dataset.allergen;
                selectedAllergens = selectedAllergens.includes(code)
                  ? selectedAllergens.filter((x) => x !== code)
                  : [...selectedAllergens, code];
                btn.classList.toggle('is-active');
              };
            }

            sheet.querySelector('#f-tags').onclick = (e) => {
              const btn = e.target.closest('[data-tag]');
              if (!btn) return;
              const t = btn.dataset.tag;
              selectedTags = selectedTags.includes(t)
                ? selectedTags.filter((x) => x !== t)
                : [...selectedTags, t];
              btn.classList.toggle('is-active');
            };
            sheet.querySelector('#f-cancel').onclick = closeSheet;
            sheet.querySelector('#f-save').onclick = async (e) => {
              const num = (id) => Number(sheet.querySelector(id).value || 0);
              const payload = {
                category_id: Number(sheet.querySelector('#f-cat').value),
                name: sheet.querySelector('#f-name').value.trim(),
                description: sheet.querySelector('#f-desc').value.trim(),
                price: num('#f-price'),
                weight_g: num('#f-weight'),
                kcal: num('#f-kcal'),
                protein: num('#f-p'),
                fat: num('#f-f'),
                carbs: num('#f-c'),
                icon: selectedIcon,
                tags: selectedTags,
                ingredients: sheet.querySelector('#f-ingredients').value
                  .split('\n').map((x) => x.trim()).filter(Boolean),
                allergens: selectedAllergens,
                stock_qty: num('#f-stock'),
              };
              if (!payload.name) { toast('Введите название', 'err'); return; }
              if (payload.price <= 0) { toast('Укажите цену', 'err'); return; }
              e.target.disabled = true;
              try {
                if (isNew) await api.post('/api/admin/dishes', payload);
                else await api.patch(`/api/admin/dishes/${dish.id}`, payload);
                toast(isNew ? 'Блюдо добавлено' : 'Изменения сохранены', 'ok');
                closeSheet();
                await loadMenu(true);
                renderPanel();
              } catch (err) {
                toast(err.message, 'err');
                e.target.disabled = false;
              }
            };
          },
        );
      };

      const renderMenu = async () => {
        const dishes = await api.get('/api/admin/dishes');
        const byCat = categories.map((c) => ({ cat: c, items: dishes.filter((d) => d.category_id === c.id) }));

        panel.innerHTML = `
          <div class="stack">
            <button class="btn" id="add-dish">＋ Добавить блюдо</button>
            <div class="small muted" style="padding-left:4px">
              Всего ${dishes.length} позиций · активных ${dishes.filter((d) => d.is_active).length}.
              «Скрыть» убирает блюдо из меню и сохраняет историю заказов, «Удалить» стирает запись из базы.
            </div>
            ${byCat
              .map(
                ({ cat, items }) => `
              <section class="section">
                <div class="section__head">
                  <h2 class="section__title" style="font-size:19px">${esc(cat.icon)} ${esc(cat.name)}</h2>
                  <span class="small muted">${items.length}</span>
                </div>
                ${
                  items.length
                    ? `<div class="table-wrap"><table class="data">
                        <thead><tr>
                          <th>Блюдо</th><th>Цена</th><th>Остаток</th><th>Метки</th><th>В меню</th><th></th>
                        </tr></thead>
                        <tbody>
                        ${items
                          .map(
                            (d) => `
                          <tr data-row="${d.id}">
                            <td>
                              <div class="hstack">
                                <span style="font-size:20px">${esc(d.icon)}</span>
                                <div>
                                  <div class="bold">${esc(d.name)}</div>
                                  <div class="small muted">${d.weight_g} г · ${d.kcal} ккал</div>
                                </div>
                              </div>
                            </td>
                            <td class="bold nowrap">${money(d.price)}</td>
                            <td>
                              <input class="input" style="width:76px;padding:7px" type="number" min="0"
                                     value="${d.stock_qty}" data-stock="${d.id}">
                            </td>
                            <td>${(d.tags || []).map((t) => `<span class="tag tag--${esc(t)}">${esc(TAG_LABELS[t] || t)}</span>`).join(' ') || '<span class="muted small">—</span>'}</td>
                            <td><span class="switch ${d.is_active ? 'is-on' : ''}" data-toggle="${d.id}"></span></td>
                            <td class="nowrap">
                              <button class="btn btn--sm btn--ghost" data-edit="${d.id}">Изм.</button>
                              <button class="btn btn--sm btn--danger" data-del="${d.id}">Удал.</button>
                            </td>
                          </tr>`,
                          )
                          .join('')}
                        </tbody></table></div>`
                    : '<div class="small muted center" style="padding:14px">В категории пока нет блюд</div>'
                }
              </section>`,
              )
              .join('')}
          </div>`;

        panel.querySelector('#add-dish').onclick = () => dishForm();

        panel.querySelectorAll('[data-edit]').forEach((btn) => {
          btn.onclick = () => dishForm(dishes.find((d) => d.id === Number(btn.dataset.edit)));
        });

        panel.querySelectorAll('[data-del]').forEach((btn) => {
          btn.onclick = async () => {
            const dish = dishes.find((d) => d.id === Number(btn.dataset.del));
            const choice = await confirmSheet({
              title: `Удалить «${dish.name}»?`,
              text: 'Блюдо будет полностью стёрто из базы. Если нужно просто убрать его из меню на время — используйте переключатель «В меню».',
              confirmLabel: 'Удалить навсегда',
              danger: true,
            });
            if (!choice) return;
            try {
              await api.del(`/api/admin/dishes/${dish.id}?hard=true`);
              toast('Блюдо удалено', 'ok');
              await loadMenu(true);
              renderPanel();
            } catch (err) {
              toast(err.message, 'err');
            }
          };
        });

        panel.querySelectorAll('[data-toggle]').forEach((sw) => {
          sw.onclick = async () => {
            const id = Number(sw.dataset.toggle);
            const next = !sw.classList.contains('is-on');
            sw.classList.toggle('is-on', next);
            try {
              await api.patch(`/api/admin/dishes/${id}`, { is_active: next });
              toast(next ? 'Блюдо снова в меню' : 'Блюдо скрыто из меню');
              await loadMenu(true);
            } catch (err) {
              toast(err.message, 'err');
              sw.classList.toggle('is-on', !next);
            }
          };
        });

        panel.querySelectorAll('[data-stock]').forEach((input) => {
          input.onchange = async () => {
            const id = Number(input.dataset.stock);
            const qty = Math.max(0, Number(input.value || 0));
            try {
              await api.post(`/api/admin/dishes/${id}/stock?qty=${qty}`);
              toast(qty === 0 ? 'Блюдо в стоп-листе' : `Остаток: ${qty} порц.`);
              await loadMenu(true);
            } catch (err) {
              toast(err.message, 'err');
            }
          };
        });
      };

      /* -------------------------- Категории -------------------------------- */
      const renderCategories = async () => {
        panel.innerHTML = `
          <div class="stack">
            <button class="btn" id="add-cat">＋ Добавить категорию</button>
            <section class="section">
              <div class="table-wrap"><table class="data">
                <thead><tr><th>Категория</th><th>Адрес</th><th>Порядок</th><th>Видна</th></tr></thead>
                <tbody>
                  ${categories
                    .map(
                      (c) => `
                    <tr>
                      <td class="hstack"><span style="font-size:20px">${esc(c.icon)}</span><span class="bold">${esc(c.name)}</span></td>
                      <td class="muted small">${esc(c.slug)}</td>
                      <td><input class="input" style="width:72px;padding:7px" type="number" value="${c.sort_order}" data-sort="${c.id}"></td>
                      <td><span class="switch ${c.is_active ? 'is-on' : ''}" data-cat-toggle="${c.id}"></span></td>
                    </tr>`,
                    )
                    .join('')}
                </tbody>
              </table></div>
            </section>
          </div>`;

        panel.querySelector('#add-cat').onclick = () => {
          openSheet(
            `<div class="stack">
              <h2 class="section__title" style="font-size:21px">Новая категория</h2>
              <div class="field"><label class="field__label" for="c-name">Название</label>
                <input class="input" id="c-name" placeholder="Например: Завтраки"></div>
              <div class="field"><span class="field__label">Иконка</span>
                <div class="chips" id="c-icons">${ICONS.map((i) => `<button type="button" class="chip" data-icon="${i}" style="font-size:19px">${i}</button>`).join('')}</div>
              </div>
              <button class="btn" id="c-save">Добавить</button>
              <button class="btn btn--ghost" id="c-cancel">Отмена</button>
            </div>`,
            (sheet) => {
              let icon = '🍽';
              sheet.querySelector('#c-icons').onclick = (e) => {
                const btn = e.target.closest('[data-icon]');
                if (!btn) return;
                icon = btn.dataset.icon;
                sheet.querySelectorAll('[data-icon]').forEach((b) => b.classList.toggle('is-active', b === btn));
              };
              sheet.querySelector('#c-cancel').onclick = closeSheet;
              sheet.querySelector('#c-save').onclick = async () => {
                const name = sheet.querySelector('#c-name').value.trim();
                if (!name) { toast('Введите название', 'err'); return; }
                try {
                  await api.post('/api/admin/categories', {
                    name, icon, color: '#4a7dff', sort_order: (categories.length + 1) * 10,
                  });
                  toast('Категория добавлена', 'ok');
                  closeSheet();
                  categories = await api.get('/api/admin/categories');
                  await loadMenu(true);
                  renderPanel();
                } catch (err) {
                  toast(err.message, 'err');
                }
              };
            },
          );
        };

        panel.querySelectorAll('[data-cat-toggle]').forEach((sw) => {
          sw.onclick = async () => {
            const id = Number(sw.dataset.catToggle);
            const next = !sw.classList.contains('is-on');
            sw.classList.toggle('is-on', next);
            try {
              await api.patch(`/api/admin/categories/${id}`, { is_active: next });
              categories = await api.get('/api/admin/categories');
              await loadMenu(true);
            } catch (err) {
              toast(err.message, 'err');
              sw.classList.toggle('is-on', !next);
            }
          };
        });

        panel.querySelectorAll('[data-sort]').forEach((input) => {
          input.onchange = async () => {
            try {
              await api.patch(`/api/admin/categories/${input.dataset.sort}`, {
                sort_order: Number(input.value || 0),
              });
              categories = await api.get('/api/admin/categories');
              await loadMenu(true);
              toast('Порядок обновлён');
            } catch (err) {
              toast(err.message, 'err');
            }
          };
        });
      };

      /* -------------------------- Окна выдачи ------------------------------ */
      const renderSlots = async () => {
        const slots = await api.get('/api/admin/slots');
        panel.innerHTML = `
          <div class="stack">
            <button class="btn" id="add-slot">＋ Добавить окно выдачи</button>
            <div class="small muted" style="padding-left:4px">
              Окна привязаны к расписанию перемен. Приём заказов закрывается за N минут до начала выдачи —
              столько кухне нужно, чтобы собрать все заказы перемены разом.
            </div>
            <section class="section">
              <div class="table-wrap"><table class="data">
                <thead><tr><th>Окно</th><th>Время</th><th>Точка</th><th>Вместимость</th><th>Приём закрывается за, мин</th><th>Занято сегодня</th><th>Активно</th></tr></thead>
                <tbody>
                  ${slots
                    .map(
                      (s) => `
                    <tr>
                      <td class="bold">${esc(s.label)}</td>
                      <td class="nowrap">${esc(s.time_range)}</td>
                      <td class="small muted">${esc(s.point)}</td>
                      <td><input class="input" style="width:80px;padding:7px" type="number" min="1" value="${s.capacity}" data-cap="${s.id}"></td>
                      <td class="nowrap"><input class="input" style="width:80px;padding:7px" type="number" min="0" max="1440" step="5"
                            value="${s.order_cutoff_minutes}" data-cutoff="${s.id}" aria-label="Приём закрывается за N минут">
                          <div class="small muted">до ${esc(s.deadline_time)}</div></td>
                      <td>${s.taken} / ${s.capacity}</td>
                      <td><span class="switch ${s.is_active ? 'is-on' : ''}" data-slot-toggle="${s.id}"></span></td>
                    </tr>`,
                    )
                    .join('')}
                </tbody>
              </table></div>
            </section>
          </div>`;

        panel.querySelector('#add-slot').onclick = () => {
          openSheet(
            `<div class="stack">
              <h2 class="section__title" style="font-size:21px">Новое окно выдачи</h2>
              <div class="field"><label class="field__label" for="s-label">Название</label>
                <input class="input" id="s-label" placeholder="Например: Перемена 5"></div>
              <div class="grid-2">
                <div class="field"><label class="field__label" for="s-from">Начало</label>
                  <input class="input" id="s-from" type="time" value="15:00"></div>
                <div class="field"><label class="field__label" for="s-to">Конец</label>
                  <input class="input" id="s-to" type="time" value="15:20"></div>
              </div>
              <div class="grid-2">
                <div class="field"><label class="field__label" for="s-cap">Сколько заказов принимаем</label>
                  <input class="input" id="s-cap" type="number" min="1" value="50"></div>
                <div class="field"><label class="field__label" for="s-cutoff">Приём заказов закрывается за N минут</label>
                  <input class="input" id="s-cutoff" type="number" min="0" max="1440" step="5" value="60"></div>
              </div>
              <div class="field"><label class="field__label" for="s-point">Точка выдачи</label>
                <input class="input" id="s-point" value="Окно «Экспресс-выдача», корпус А"></div>
              <button class="btn" id="s-save">Добавить</button>
              <button class="btn btn--ghost" id="s-cancel">Отмена</button>
            </div>`,
            (sheet) => {
              sheet.querySelector('#s-cancel').onclick = closeSheet;
              sheet.querySelector('#s-save').onclick = async () => {
                const payload = {
                  label: sheet.querySelector('#s-label').value.trim(),
                  starts_at: sheet.querySelector('#s-from').value,
                  ends_at: sheet.querySelector('#s-to').value,
                  capacity: Number(sheet.querySelector('#s-cap').value || 50),
                  order_cutoff_minutes: Number(sheet.querySelector('#s-cutoff').value || 0),
                  point: sheet.querySelector('#s-point').value.trim(),
                  sort_order: (slots.length + 1) * 10,
                };
                if (!payload.label) { toast('Введите название', 'err'); return; }
                try {
                  await api.post('/api/admin/slots', payload);
                  toast('Окно добавлено', 'ok');
                  closeSheet();
                  renderPanel();
                } catch (err) {
                  toast(err.message, 'err');
                }
              };
            },
          );
        };

        panel.querySelectorAll('[data-slot-toggle]').forEach((sw) => {
          sw.onclick = async () => {
            const next = !sw.classList.contains('is-on');
            sw.classList.toggle('is-on', next);
            try {
              await api.patch(`/api/admin/slots/${sw.dataset.slotToggle}`, { is_active: next });
              toast(next ? 'Окно включено' : 'Окно отключено');
            } catch (err) {
              toast(err.message, 'err');
              sw.classList.toggle('is-on', !next);
            }
          };
        });

        panel.querySelectorAll('[data-cutoff]').forEach((input) => {
          input.onchange = async () => {
            try {
              await api.patch(`/api/admin/slots/${input.dataset.cutoff}`, {
                order_cutoff_minutes: Math.min(1440, Math.max(0, Number(input.value || 0))),
              });
              toast('Время приёма заказов обновлено');
              renderPanel();
            } catch (err) {
              toast(err.message, 'err');
            }
          };
        });

        panel.querySelectorAll('[data-cap]').forEach((input) => {
          input.onchange = async () => {
            try {
              await api.patch(`/api/admin/slots/${input.dataset.cap}`, {
                capacity: Math.max(1, Number(input.value || 1)),
              });
              toast('Вместимость обновлена');
            } catch (err) {
              toast(err.message, 'err');
            }
          };
        });
      };

      /* ---------------------------- Отчёты --------------------------------- */
      const renderStats = async () => {
        let day = isoDate(0);
        const draw = async () => {
          const s = await api.get(`/api/admin/stats?date=${day}`);
          const maxQty = Math.max(1, ...s.top_dishes.map((d) => d.qty));
          panel.innerHTML = `
            <div class="stack">
              <div class="chips" id="stat-days">
                ${[0, -1, -2, 1, 2]
                  .map((o) => {
                    const iso = isoDate(o);
                    return `<button class="chip ${day === iso ? 'is-active' : ''}" data-d="${iso}">${esc(dateLabel(iso))}</button>`;
                  })
                  .join('')}
              </div>
              <div class="kpi-grid">
                <div class="kpi"><div class="kpi__label">Заказов</div><div class="kpi__value">${s.orders_today}</div></div>
                <div class="kpi"><div class="kpi__label">Выручка</div><div class="kpi__value">${money(s.revenue_today)}</div></div>
                <div class="kpi"><div class="kpi__label">Средний чек</div><div class="kpi__value">${money(s.avg_check)}</div></div>
                <div class="kpi"><div class="kpi__label">Выдано</div><div class="kpi__value">${s.issued_today}</div></div>
              </div>
              <section class="section">
                <div class="section__head"><h2 class="section__title" style="font-size:19px">Топ блюд</h2></div>
                ${
                  s.top_dishes.length
                    ? s.top_dishes
                        .map(
                          (d) => `
                    <div class="bar-row">
                      <span style="font-size:17px">${esc(d.icon)}</span>
                      <span class="bar-row__name">${esc(d.name)}</span>
                      <span class="bar-row__bar" style="width:${Math.round((d.qty / maxQty) * 90) + 10}px"></span>
                      <span class="bold nowrap">${d.qty} шт.</span>
                    </div>`,
                        )
                        .join('')
                    : '<div class="small muted center" style="padding:14px">Нет продаж за этот день</div>'
                }
              </section>
              <section class="section">
                <div class="section__head"><h2 class="section__title" style="font-size:19px">По окнам выдачи</h2></div>
                ${
                  s.by_slot.length
                    ? `<div class="rows">${s.by_slot
                        .map(
                          (r) => `<div class="row"><span class="row__label">${esc(r.slot)}</span>
                                    <span class="bold">${r.orders} зак. · ${money(r.sum)}</span></div>`,
                        )
                        .join('')}</div>`
                    : '<div class="small muted center" style="padding:14px">Нет данных</div>'
                }
              </section>
              <div class="grid-2">
                <div class="kpi"><div class="kpi__label">Пользователей</div><div class="kpi__value">${s.users_total}</div></div>
                <div class="kpi"><div class="kpi__label">Блюд в меню</div><div class="kpi__value">${s.dishes_active}</div></div>
              </div>
            </div>`;
          panel.querySelector('#stat-days').onclick = (e) => {
            const btn = e.target.closest('[data-d]');
            if (!btn) return;
            day = btn.dataset.d;
            draw();
          };
        };
        await draw();
      };

      /* -------------------------- Сотрудники ------------------------------- */
      const renderStaff = async () => {
        const users = await api.get('/api/admin/users');
        const roleName = { student: 'Обучающийся', operator: 'Оператор', admin: 'Администратор' };
        panel.innerHTML = `
          <div class="stack">
            <button class="btn" id="add-user">＋ Создать учётную запись</button>
            <div class="small muted" style="padding-left:4px">
              Операторская учётная запись открывает экран кухни и выдачу заказов, но не даёт доступ к редактированию меню.
            </div>
            <section class="section">
              <div class="table-wrap"><table class="data">
                <thead><tr><th>Пользователь</th><th>Почта</th><th>Группа</th><th>Бонусы</th><th>Роль</th></tr></thead>
                <tbody>
                  ${users
                    .map(
                      (u) => `
                    <tr>
                      <td class="bold">${esc(u.full_name)}</td>
                      <td class="small muted">${esc(u.email)}</td>
                      <td class="small muted">${esc(u.group_name || '—')}</td>
                      <td>${money(u.bonus_balance)}</td>
                      <td>
                        <select class="input" style="padding:7px;width:150px" data-role="${u.id}"
                          ${u.id === state.user.id ? 'disabled' : ''}>
                          ${Object.entries(roleName)
                            .map(([k, v]) => `<option value="${k}" ${u.role === k ? 'selected' : ''}>${v}</option>`)
                            .join('')}
                        </select>
                      </td>
                    </tr>`,
                    )
                    .join('')}
                </tbody>
              </table></div>
            </section>
          </div>`;

        panel.querySelectorAll('[data-role]').forEach((select) => {
          select.onchange = async () => {
            try {
              await api.patch(`/api/admin/users/${select.dataset.role}/role?role=${select.value}`);
              toast('Роль обновлена', 'ok');
            } catch (err) {
              toast(err.message, 'err');
              renderPanel();
            }
          };
        });

        panel.querySelector('#add-user').onclick = () => {
          openSheet(
            `<div class="stack">
              <h2 class="section__title" style="font-size:21px">Новая учётная запись</h2>
              <div class="field"><label class="field__label" for="u-name">Имя</label>
                <input class="input" id="u-name" placeholder="Иванова Мария"></div>
              <div class="field"><label class="field__label" for="u-email">Почта</label>
                <input class="input" id="u-email" type="email" placeholder="kitchen@rosbiotech.ru"></div>
              <div class="field"><label class="field__label" for="u-pass">Пароль</label>
                <input class="input" id="u-pass" placeholder="минимум 4 символа"></div>
              <div class="field"><label class="field__label" for="u-role">Роль</label>
                <select class="input" id="u-role">
                  <option value="operator">Оператор столовой</option>
                  <option value="admin">Администратор</option>
                  <option value="student">Обучающийся</option>
                </select></div>
              <button class="btn" id="u-save">Создать</button>
              <button class="btn btn--ghost" id="u-cancel">Отмена</button>
            </div>`,
            (sheet) => {
              sheet.querySelector('#u-cancel').onclick = closeSheet;
              sheet.querySelector('#u-save').onclick = async () => {
                const params = new URLSearchParams({
                  email: sheet.querySelector('#u-email').value.trim(),
                  password: sheet.querySelector('#u-pass').value,
                  full_name: sheet.querySelector('#u-name').value.trim(),
                  role: sheet.querySelector('#u-role').value,
                });
                if (!params.get('email') || !params.get('full_name')) {
                  toast('Заполните имя и почту', 'err');
                  return;
                }
                try {
                  await api.post(`/api/admin/users?${params}`);
                  toast('Учётная запись создана', 'ok');
                  closeSheet();
                  renderPanel();
                } catch (err) {
                  toast(err.message, 'err');
                }
              };
            },
          );
        };
      };

      /* ---------------------------- Роутинг вкладок ------------------------- */
      const renderPanel = async () => {
        panel.innerHTML = skeletonList(4, 70);
        try {
          if (tab === 'menu') await renderMenu();
          else if (tab === 'categories') await renderCategories();
          else if (tab === 'slots') await renderSlots();
          else if (tab === 'stats') await renderStats();
          else if (tab === 'staff') await renderStaff();
        } catch (err) {
          toast(err.message, 'err');
          panel.innerHTML = empty('⚠️', 'Не удалось загрузить', err.message);
        }
      };

      categories = await api.get('/api/admin/categories');
      renderTabs();
      await renderPanel();

      tabsHost.onclick = (e) => {
        const btn = e.target.closest('[data-tab]');
        if (!btn) return;
        tab = btn.dataset.tab;
        renderTabs();
        renderPanel();
      };
    },
  };
}
