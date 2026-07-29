# Attributions - remote-screen

**Plugin author:** Bespok3d, with the web app from the Extended Firmware overlay `61-app-remote-screen` by @horzadome; the framebuffer server here is written from scratch

Mirrors and controls the printer's screen from a browser.

| Upstream project | Author | Licence | Needed at runtime | Code ships in this package |
| --- | --- | --- | --- | --- |
| Extended Firmware overlay `61-app-remote-screen` | the PWA by @horzadome, packaged by paxx12 | GPL-3.0 | no | yes |

The web app in this package comes from the Extended Firmware overlay `61-app-remote-screen`,
GPL-3.0, whose PWA is credited to @horzadome and whose framebuffer double-buffering in
`fb-http-server.py` is credited to @suchmememanyskill; packaging by paxx12. `html/manifest.json`
ships with one value changed (`start_url`) and `html/icon.svg` with its comments removed, and parts
of `html/index.html`, `html/auth.js` and the nginx location file match that overlay. Each of those
files carries a dated note of what changed, except `manifest.json`, which is JSON and cannot hold a
comment.

The framebuffer server, the touch input path and the watchdog are written from scratch.
