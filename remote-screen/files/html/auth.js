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

function removeStoredByPrefix(prefix) {
    Object.keys(localStorage)
        .filter(function(name) { return name.startsWith(prefix); })
        .forEach(function(name) { localStorage.removeItem(name); });
}

// Delete across every path the cookie might have been written at, with both Max-Age and a past expiry,
// so a webview that ignores one form still drops it.
function deleteStreamCookie(name) {
    ['/screen', '/screen/', '/'].forEach(function(path) {
        document.cookie = `${name}=; path=${path}; Max-Age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
    });
}

// Wipe EVERY stored credential, not just this host's: getJWT()/refreshSession() fall back to
// findStored('user-token-'/'refresh-token-') across all keys, so a leftover from another host slug
// (junior flip-flops between .109 and .66) would otherwise be re-read and re-set as the stream cookie.
function clearStoredCredentials() {
    removeStoredByPrefix('user-token-');
    removeStoredByPrefix('refresh-token-');
    removeStoredByPrefix('screen-apikey-');
    deleteStreamCookie('screen_token');
    deleteStreamCookie('screen_apikey');
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

// Decide how the stream should come up by probing the gated snapshot. probeSnapshot(authed) returns the
// fetch Response: authed=true carries the stored credential, authed=false is a TRULY anonymous probe
// (no header AND no cookie). Returns 'stream' (open or authenticated -> render), 'login' (gated, real
// credentials needed), or 'retry' (a transient non-401 failure -> reconnect). The self-heal lives here:
// a stale credential over an open printer makes the authed probe 401 while the anonymous probe is
// served, so we wipe the stale credential and stream instead of prompting. Pure of the DOM (the caller
// owns showStream/showLogin/reconnect), so it is unit-testable.
async function resolveStreamAccess(probeSnapshot, allowRefresh) {
    const authed = await probeSnapshot(true);
    if (authed.ok) return 'stream';
    if (authed.status !== 401) return 'retry';
    if (allowRefresh && await refreshSession()) return resolveStreamAccess(probeSnapshot, false);
    const anonymous = await probeSnapshot(false);
    if (!anonymous.ok) return 'login';
    clearStoredCredentials();
    return 'stream';
}
