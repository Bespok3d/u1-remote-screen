from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
HTML = (PLUGIN_DIR / "files/html/index.html").read_text()
AUTH_JS = (PLUGIN_DIR / "files/html/auth.js").read_text()
NGINX_CONF = (PLUGIN_DIR / "files/etc/nginx/locations/remote-screen.conf").read_text()

SCREEN_ROUTES = ("/screen/stream.mjpg", "/screen/snapshot.jpg", "/screen/snapshot", "/screen/touch")


def test_stream_renders_via_native_img_not_streaming_fetch() -> None:
    # OrcaSlicer's embedded webview cannot consume a streaming fetch() response body, so the
    # MJPEG stream MUST render through a native <img> multipart element (universally supported).
    # A fetch()+getReader() pump regressed OrcaSlicer to an endless "Reconnecting...".
    assert "getReader" not in HTML
    assert "response.body" not in HTML
    assert "img.src = 'stream.mjpg" in HTML
    assert "oneshot" not in HTML.lower()
    assert "oneshot" not in AUTH_JS.lower()


def test_auth_credential_reaches_stream_via_cookie() -> None:
    # The <img> cannot send an Authorization header and the nginx auth_request subrequest drops
    # the parent query string, so the JWT rides the screen_token cookie that /auth_check turns
    # back into a Bearer header. Login OFF / trusted-IP: no JWT -> the cookie is cleared.
    assert "applyStreamCookie" in AUTH_JS
    assert "screen_token" in AUTH_JS
    assert "applyStreamCookie()" in HTML
    assert "$cookie_screen_token" in NGINX_CONF
    assert "Authorization $screen_cred" in NGINX_CONF


def test_api_key_supported_as_alternative_credential() -> None:
    # Moonraker accepts a static API key via X-Api-Key (bypasses force_logins). The screen takes it
    # from the URL (?api_key=) or the login form; fetches send the header, the <img> stream sends
    # the screen_apikey cookie, /auth_check forwards either. Device-verified 2026-06-28.
    assert "captureApiKeyFromUrl" in AUTH_JS
    assert "api_key" in AUTH_JS
    assert "'X-Api-Key'" in AUTH_JS
    assert "screen_apikey" in AUTH_JS
    assert 'id="login-apikey"' in HTML
    assert "$cookie_screen_apikey" in NGINX_CONF
    assert "X-Api-Key $screen_apikey" in NGINX_CONF


def test_screen_assets_are_not_cached_to_avoid_version_skew() -> None:
    # A heuristically-cached auth.js paired with a fresh index.html threw a ReferenceError and stuck
    # the page on "Connecting..." (only an empty-cache reload recovered, which end users can't do).
    # The page + script load no-store, and index.html requests a version-stamped auth.js, so the two
    # can never mismatch. Regression: 2026-06-28.
    assert 'add_header Cache-Control "no-store"' in NGINX_CONF
    assert "auth.js?v=" in HTML


def test_stale_credential_self_heals_when_screen_is_open() -> None:
    # A past login leaves a stale JWT; with Moonraker login off, Moonraker 401s the explicit bad
    # token even though trusted-IP serves an anonymous request. The client retries with no
    # credential and, if served, drops the stale credential and streams, so a prior login never
    # locks an open screen out (the OrcaSlicer-asks-after-login-off bug). Device-confirmed.
    # The decision flow lives in resolveStreamAccess (auth.js, behaviorally tested in
    # auth.behavior.test.mjs); connect() wires it up. The anonymous retry must carry NO credential -
    # credentials:'omit' drops the stale cookie too, not just the header (sending the cookie was
    # what kept 401ing the "anonymous" retry).
    assert "resolveStreamAccess" in AUTH_JS
    assert "resolveStreamAccess" in HTML
    assert "credentials: 'omit'" in HTML
    assert "clearStoredCredentials" in AUTH_JS
    # the wipe must cover ALL host slugs (getJWT falls back to findStored across every user-token-*,
    # so a leftover from junior's other IP would be re-read) and delete the cookie across paths.
    assert "removeStoredByPrefix('user-token-')" in AUTH_JS
    assert "deleteStreamCookie('screen_token')" in AUTH_JS


def test_auth_status_probed_with_finite_fetch() -> None:
    # The login-vs-live decision uses a finite snapshot fetch (every webview handles a finite
    # body); only the endless stream must avoid fetch.
    assert "fetch('snapshot.jpg'" in HTML
    assert "getAuthHeaders()" in HTML


def test_works_in_both_modes_like_fluidd() -> None:
    # Login OFF: the stream is attempted with no token (trusted-IP serves it), so there is no
    # pre-gate on a missing token. Login ON without a shared session: the screen logs in IN PLACE
    # (like Fluidd), never sending the user elsewhere to reload.
    assert "!headers.Authorization" not in HTML
    assert "login-form" in HTML
    assert "function login(" in AUTH_JS
    assert "function refreshSession(" in AUTH_JS


def test_screen_routes_stay_gated() -> None:
    # The screen controls the printer, so every subresource stays behind Moonraker auth.
    for route in SCREEN_ROUTES:
        block = NGINX_CONF.split(f"location = {route}", 1)[1].split("\nlocation", 1)[0]
        assert "auth_request /auth_check;" in block, route
