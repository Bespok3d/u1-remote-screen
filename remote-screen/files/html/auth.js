function sessionKeys() {
    const host = window.location.host.replace(/[^a-zA-Z0-9]/g, '_');
    return {
        token: `user-token-${host}`,
        refresh: `refresh-token-${host}`,
        apikey: `screen-apikey-${host}`,
    };
}

// A Moonraker API key (the slicer's "API Key / Password") is a static credential that bypasses
// force_logins. It can arrive on the URL (?api_key= / ?apikey=, e.g. set as OrcaSlicer's Device UI)
// or be pasted into the login form; either way it is stored and preferred over a user JWT.
function getApiKey() {
    return localStorage.getItem(sessionKeys().apikey);
}

function storeApiKey(key) {
    localStorage.setItem(sessionKeys().apikey, key);
}

function clearApiKey() {
    localStorage.removeItem(sessionKeys().apikey);
}

function captureApiKeyFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const key = params.get('api_key') || params.get('apikey');
    if (key) storeApiKey(key.trim());
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
    const apiKey = getApiKey();
    if (apiKey) return { 'X-Api-Key': apiKey };
    const jwt = getJWT();
    return jwt ? { Authorization: `Bearer ${jwt}` } : {};
}

function storeSession(token, refreshToken) {
    const keys = sessionKeys();
    localStorage.setItem(keys.token, token);
    if (refreshToken) localStorage.setItem(keys.refresh, refreshToken);
}

function setStreamCookie(name, value) {
    if (value) {
        document.cookie = `${name}=${value}; path=/screen; SameSite=Lax`;
        return;
    }
    document.cookie = `${name}=; path=/screen; Max-Age=0`;
}

// The <img> MJPEG stream cannot send an Authorization / X-Api-Key header and the nginx
// auth_request subrequest drops the parent query string, so the credential travels as a cookie
// that /auth_check turns back into the right header for Moonraker. An API key wins over a user
// JWT; no credential (login off / trusted-IP) clears both, so a stale one never breaks the
// ungated path.
function applyStreamCookie() {
    const apiKey = getApiKey();
    setStreamCookie('screen_apikey', apiKey);
    setStreamCookie('screen_token', apiKey ? '' : getJWT());
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
