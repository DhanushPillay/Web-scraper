// Service Worker — Sniffer
const CACHE_NAME = 'sniffer-v2';
const APP_SHELL = [
    '/static/css/app.css',
    '/static/js/app.js',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(APP_SHELL);
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(names =>
            Promise.all(names
                .filter(name => name !== CACHE_NAME)
                .map(name => caches.delete(name))
            )
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    const isGet = event.request.method === 'GET';

    // Network-first for dynamic content (API, actions, HTML pages)
    if (!isGet || url.pathname.startsWith('/api/') || url.pathname === '/bookmark' || url.pathname === '/toggle_read'
        || url.pathname === '/' || url.pathname === '/saved' || url.pathname.startsWith('/download') || url.pathname.startsWith('/export')) {
        event.respondWith(
            fetch(event.request).catch(() => caches.match(event.request))
        );
        return;
    }

    // Cache-first for static assets (css/js/images) — stale-while-revalidate
    event.respondWith(
        caches.open(CACHE_NAME).then(cache => {
            return cache.match(event.request).then(cached => {
                const fetched = fetch(event.request).then(response => {
                    if (response.ok && response.type === 'basic') {
                        cache.put(event.request, response.clone());
                    }
                    return response;
                }).catch(() => cached);

                return cached || fetched;
            });
        })
    );
});
