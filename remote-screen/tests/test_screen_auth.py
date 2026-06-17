from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
HTML = (PLUGIN_DIR / "files/html/index.html").read_text()
AUTH_JS = (PLUGIN_DIR / "files/html/auth.js").read_text()
NGINX_CONF = (PLUGIN_DIR / "files/etc/nginx/locations/remote-screen.conf").read_text()

SCREEN_ROUTES = ("/screen/stream.mjpg", "/screen/snapshot.jpg", "/screen/snapshot", "/screen/touch")


def test_stream_authenticates_with_header_not_query_token() -> None:
    # The view must carry its credential in the Authorization header (the only path nginx
    # auth_request forwards to Moonraker); a ?token= query param is dropped, so it 401s under
    # force_logins. Device-verified 2026-06-17.
    assert "fetch('stream.mjpg'" in HTML
    assert "getAuthHeaders()" in HTML
    assert "token=" not in HTML
    assert "oneshot" not in HTML.lower()
    assert "oneshot" not in AUTH_JS.lower()


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
