function getJWT() {
    const instanceKey = `user-token-${window.location.host.replace(/[^a-zA-Z0-9]/g, '_')}`;
    const token = localStorage.getItem(instanceKey);
    if (token) return token;
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith('user-token-')) {
            const t = localStorage.getItem(key);
            if (t) return t;
        }
    }
    return null;
}

function getAuthHeaders() {
    const jwt = getJWT();
    return jwt ? { Authorization: `Bearer ${jwt}` } : {};
}

async function getOneshotToken() {
    try {
        const response = await fetch('/access/oneshot_token', { headers: getAuthHeaders() });
        if (response.status === 401) {
            window.location.href = '/';
            return null;
        }
        if (!response.ok) return null;
        const data = await response.json();
        return data.result || null;
    } catch (err) {
        return null;
    }
}
