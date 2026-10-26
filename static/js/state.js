/* Глобальное состояние: пользователь, корзина, кэш меню. */
import api, { auth } from './api.js';

const listeners = new Set();

export const state = {
  user: null,
  cart: { items: [], count: 0, subtotal: 0, bonus_available: 0, max_bonus_applicable: 0 },
  categories: [],
  dishes: [],
  menuLoaded: false,
  activeOrders: [],
  lastOrderId: null,
  offline: false,
};

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function emit() {
  listeners.forEach((fn) => fn(state));
}

export const isStaff = () => !!state.user && ['operator', 'admin'].includes(state.user.role);
export const isAdmin = () => !!state.user && state.user.role === 'admin';

export async function loadUser() {
  if (!auth.token) { state.user = null; emit(); return null; }
  try {
    state.user = await api.get('/api/auth/me', { silent: true });
    state.offline = false;
  } catch (err) {
    state.user = null;
    // без сети токен не трогаем: иначе открыл приложение в метро — и тебя разлогинило
    if (err.status === 0) state.offline = true;
    else auth.token = '';
  }
  emit();
  return state.user;
}

export async function loadMenu(force = false) {
  if (state.menuLoaded && !force) return;
  const [categories, dishes] = await Promise.all([
    api.get('/api/categories'),
    api.get('/api/dishes'),
  ]);
  state.categories = categories;
  state.dishes = dishes;
  state.menuLoaded = true;
  emit();
}

export async function loadCart() {
  if (!state.user) {
    state.cart = { items: [], count: 0, subtotal: 0, bonus_available: 0, max_bonus_applicable: 0 };
    emit();
    return state.cart;
  }
  state.cart = await api.get('/api/cart');
  emit();
  return state.cart;
}

export function setCart(cart) {
  state.cart = cart;
  emit();
}

export function cartQty(dishId) {
  const item = state.cart.items.find((i) => i.dish_id === dishId);
  return item ? item.qty : 0;
}

export async function loadActiveOrders() {
  if (!state.user || state.user.role !== 'student') { state.activeOrders = []; return []; }
  state.activeOrders = await api.get('/api/orders?active_only=true');
  emit();
  return state.activeOrders;
}

export async function logout() {
  try { await api.post('/api/auth/logout'); } catch { /* всё равно чистим локально */ }
  auth.token = '';
  state.user = null;
  state.cart = { items: [], count: 0, subtotal: 0, bonus_available: 0, max_bonus_applicable: 0 };
  state.activeOrders = [];
  emit();
}
