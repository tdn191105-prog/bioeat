/* Вход и регистрация. */
import api, { auth } from '../api.js';
import { loadUser, loadCart, state } from '../state.js';
import { esc, toast, go } from '../ui.js';

const DEMO = [
  { email: 'student@rosbiotech.ru', password: 'student', title: 'Обучающийся', icon: '🎓', sub: 'Заказ, корзина, оплата, QR' },
  { email: 'operator@rosbiotech.ru', password: 'operator', title: 'Оператор столовой', icon: '👨‍🍳', sub: 'Очередь заказов и выдача' },
  { email: 'admin@rosbiotech.ru', password: 'admin', title: 'Администратор', icon: '⚙️', sub: 'Меню, окна выдачи, отчёты' },
];

export default async function authView() {
  let mode = 'login';

  return {
    title: 'Вход',
    bare: true,
    html: `
      <div class="stack" style="padding-top:8px">
        <div class="center" style="padding:22px 0 6px">
          <div style="width:76px;height:76px;border-radius:24px;margin:0 auto 14px;
                      background:linear-gradient(135deg,#1f5bff,#4a86ff);display:grid;place-items:center;font-size:36px">
            🍱
          </div>
          <h1 style="font-size:29px;font-weight:900;letter-spacing:-0.8px;margin:0">BioEat</h1>
          <p class="muted small" style="margin:6px 0 0">Предзаказ питания в столовой РОСБИОТЕХ</p>
        </div>

        <section class="section">
          <div class="chips" style="margin-bottom:16px">
            <button class="chip is-active" data-mode="login">Вход</button>
            <button class="chip" data-mode="register">Регистрация</button>
          </div>
          <form class="stack" id="auth-form" novalidate>
            <div id="extra-fields"></div>
            <div class="field">
              <label class="field__label" for="email">Почта</label>
              <input class="input" id="email" type="email" inputmode="email" autocomplete="email"
                     placeholder="student@rosbiotech.ru" required>
            </div>
            <div class="field">
              <label class="field__label" for="password">Пароль</label>
              <input class="input" id="password" type="password" autocomplete="current-password"
                     placeholder="Минимум 4 символа" required>
            </div>
            <button class="btn" type="submit" id="submit">Войти</button>
          </form>
        </section>

        <section class="section">
          <div class="section__head"><h2 class="section__title" style="font-size:19px">Демо-доступы</h2></div>
          <div class="stack stack--sm">
            ${DEMO.map(
              (d) => `
              <button class="option" data-demo="${esc(d.email)}" data-pass="${esc(d.password)}">
                <span class="option__ico">${d.icon}</span>
                <span class="option__body">
                  <span class="option__title">${esc(d.title)}</span>
                  <span class="option__sub">${esc(d.email)} · ${esc(d.password)}</span>
                </span>
                <span class="option__right">→</span>
              </button>`,
            ).join('')}
          </div>
          <p class="small muted mt-16" style="margin-bottom:0">
            ${esc(DEMO[0].sub)}. Нажмите на карточку — данные подставятся и вход выполнится автоматически.
          </p>
        </section>
      </div>`,

    async mount(root) {
      const form = root.querySelector('#auth-form');
      const extra = root.querySelector('#extra-fields');
      const submit = root.querySelector('#submit');
      const emailInput = root.querySelector('#email');
      const passwordInput = root.querySelector('#password');

      const setMode = (next) => {
        mode = next;
        root.querySelectorAll('[data-mode]').forEach((b) =>
          b.classList.toggle('is-active', b.dataset.mode === mode),
        );
        submit.textContent = mode === 'login' ? 'Войти' : 'Создать аккаунт';
        passwordInput.autocomplete = mode === 'login' ? 'current-password' : 'new-password';
        extra.innerHTML =
          mode === 'register'
            ? `<div class="stack">
                 <div class="field">
                   <label class="field__label" for="full_name">Фамилия и имя</label>
                   <input class="input" id="full_name" autocomplete="name" placeholder="Иванов Иван" required>
                 </div>
                 <div class="field">
                   <label class="field__label" for="group_name">Учебная группа</label>
                   <input class="input" id="group_name" placeholder="23о-380302-УБ/1">
                 </div>
               </div>`
            : '';
      };
      setMode('login');

      root.querySelectorAll('[data-mode]').forEach((btn) => {
        btn.onclick = () => setMode(btn.dataset.mode);
      });

      const finish = async (result) => {
        auth.token = result.token;
        state.user = result.user;
        await Promise.all([loadUser(), loadCart()]);
        toast(`Здравствуйте, ${result.user.full_name.split(' ')[0]}!`, 'ok');
        const target = result.user.role === 'operator' ? '#/operator' : '#/';
        go(target);
      };

      form.onsubmit = async (event) => {
        event.preventDefault();
        const email = emailInput.value.trim();
        const password = passwordInput.value;
        if (!email || password.length < 4) {
          toast('Заполните почту и пароль (от 4 символов)', 'err');
          return;
        }
        submit.disabled = true;
        submit.textContent = 'Подождите…';
        try {
          if (mode === 'login') {
            finish(await api.post('/api/auth/login', { email, password }));
          } else {
            finish(
              await api.post('/api/auth/register', {
                email,
                password,
                full_name: root.querySelector('#full_name').value.trim(),
                group_name: root.querySelector('#group_name').value.trim() || null,
              }),
            );
          }
        } catch (err) {
          toast(err.message, 'err');
          submit.disabled = false;
          setMode(mode);
        }
      };

      root.querySelectorAll('[data-demo]').forEach((btn) => {
        btn.onclick = async () => {
          setMode('login');
          emailInput.value = btn.dataset.demo;
          passwordInput.value = btn.dataset.pass;
          form.requestSubmit();
        };
      });
    },
  };
}
