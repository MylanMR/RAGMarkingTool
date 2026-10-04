// Fetch wrapper. The session token lives only in memory (never in browser
// storage), so a page refresh signs the user out by design.

let token = null;
let onExpired = () => {};

export function setToken(t) { token = t; }
export function onSessionExpired(fn) { onExpired = fn; }

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, { ...options, headers });
  if (resp.status === 401 && token) { token = null; onExpired(); }
  const isText = (resp.headers.get('content-type') || '').startsWith('text/');
  let body = null;
  try { body = isText ? await resp.text() : await resp.json(); } catch { /* empty */ }
  if (!resp.ok) {
    const d = body && body.detail;
    throw new Error(d ? (typeof d === 'string' ? d : JSON.stringify(d)) : `${resp.status} ${resp.statusText}`);
  }
  return body;
}

const j = (method, body) => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const login = (username, password) => request('/auth/login', j('POST', { username, password }));
export const authProviders = () => request('/auth/providers');
export const windowsSignIn = () => request('/auth/negotiate', { credentials: 'same-origin' });
export const logout = () => request('/auth/logout', j('POST'));
export const changePassword = (current_password, new_password) =>
  request('/auth/password', j('POST', { current_password, new_password }));

export const ingestDocument = (p) => request('/ingest/documents', j('POST', p));
export const embedDocument = (id) => request(`/ingest/documents/${encodeURIComponent(id)}/embed`, j('POST'));
export const runQuery = (p) => request('/query', j('POST', p));

export const getPolicy = () => request('/policy');
export const putPolicy = (settings, justification) => request('/policy', j('PUT', { settings, justification }));
export const policyHistory = () => request('/policy/history');

export const listAdapters = () => request('/models/adapters');
export const listModels = () => request('/models');
export const addModel = (p) => request('/models', j('POST', p));
export const editModel = (id, p) => request(`/models/${id}`, j('PATCH', p));
export const approveModel = (id) => request(`/models/${id}/approve`, j('POST'));
export const revokeModel = (id) => request(`/models/${id}/revoke`, j('POST'));

export const listProducts = (view) => request(`/products?view=${view}`);
export const getProduct = (id) => request(`/products/${id}`);
export const draftProduct = (p) => request('/products', j('POST', p));
export const editClaim = (pid, cid, p) => request(`/products/${pid}/claims/${cid}`, j('PATCH', p));
export const deleteClaim = (pid, cid) => request(`/products/${pid}/claims/${cid}`, j('DELETE'));
export const productAction = (pid, action, body) => request(`/products/${pid}/${action}`, j('POST', body));
export const dispositionClaim = (pid, cid, disposition, note) =>
  request(`/products/${pid}/claims/${cid}/disposition`, j('POST', { disposition, note }));
export const exportProduct = (pid) => request(`/products/${pid}/export`);

export const listUsers = () => request('/users');
export const addUser = (p) => request('/users', j('POST', p));
export const editUser = (id, p) => request(`/users/${id}`, j('PATCH', p));
export const unlockUser = (id) => request(`/users/${id}/unlock`, j('POST'));
export const resetPassword = (id, new_password) => request(`/users/${id}/reset-password`, j('POST', { new_password }));

export const govEvents = (q = '') => request(`/governance/events${q}`);
export const govVerify = () => request('/governance/verify');
