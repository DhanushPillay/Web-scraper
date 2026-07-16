// Service Worker — Sniffer
const CACHE_NAME = 'sniffer-v1';
const APP_SHELL = [
    '/',
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

    // Network-first for API calls and dynamic data
    if (url.pathname.startsWith('/api/') || url.pathname === '/bookmark' || url.pathname === '/toggle_read') {
        event.respondWith(
            fetch(event.request).catch(() => caches.match(event.request))
        );
        return;
    }

    // Stale-while-revalidate for app shell
    event.respondWith(
        caches.open(CACHE_NAME).then(cache => {
            return cache.match(event.request).then(cached => {
                const fetched = fetch(event.request).then(response => {
                    if (response.ok) {
                        cache.put(event.request, response.clone());
                    }
                    return response;
                }).catch(() => cached);

                return cached || fetched;
            });
        })
    );
});
