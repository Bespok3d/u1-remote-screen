const SW_VERSION = 'v2';

self.addEventListener('install', function() { self.skipWaiting(); });

self.addEventListener('activate', function(event) {
    console.info('remote-screen service worker', SW_VERSION);
    event.waitUntil(self.clients.claim());
});

function isAppAsset(request) {
    if (request.method !== 'GET') return false;
    const path = new URL(request.url).pathname;
    return path.endsWith('/') || path.endsWith('.html') || path.endsWith('.js') || path.endsWith('.json');
}

self.addEventListener('fetch', function(event) {
    const options = isAppAsset(event.request) ? { cache: 'no-store' } : undefined;
    event.respondWith(fetch(event.request, options));
});
