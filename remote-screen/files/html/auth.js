function sessionKeys() {
    const host = window.location.host.replace(/[^a-zA-Z0-9]/g, '_');
    return { token: `user-token-${host}`, refresh: `refresh-token-${host}` };
}

function findStored(prefix) {
    const key = Object.keys(localStorage).find(function(name) {
        return name.startsWith(prefix) && localStorage.getItem(name);
    });
    return key ? localStorage.getItem(key) : null;
}

function getJWT() {
    return localStorage.getItem(sessionKeys().token) || findStored('user-token-');
}

function getAuthHeaders() {
    const jwt = getJWT();
    return jwt ? { Authorization: `Bearer ${jwt}` } : {};
}

function storeSession(token, refreshToken) {
    const keys = sessionKeys();
    localStorage.setItem(keys.token, token);
    if (refreshToken) localStorage.setItem(keys.refresh, refreshToken);
}

async function postJson(path, body) {
    const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return response.ok ? response.json() : null;
}

async function login(username, password) {
    const data = await postJson('/access/login', { username: username, password: password });
    if (!data) return false;
    storeSession(data.result.token, data.result.refresh_token);
    return true;
}

async function refreshSession() {
    const refreshToken = localStorage.getItem(sessionKeys().refresh) || findStored('refresh-token-');
    if (!refreshToken) return false;
    const data = await postJson('/access/refresh_jwt', { refresh_token: refreshToken });
    if (!data) return false;
    storeSession(data.result.token, refreshToken);
    return true;
}
