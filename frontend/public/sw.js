const CACHE_NAME = 'yathi-pdi-static-__PDI_RELEASE_ID__';
const APP_SHELL = '/index.html';
const PRECACHE_URLS = [
  APP_SHELL,
  '/manifest.webmanifest',
  '/icons/pdi-icon.svg',
  '/icons/pdi-icon-192.png',
  '/icons/pdi-icon-512.png',
  '/icons/pdi-icon-maskable-512.png',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).then(response => {
        if (response.ok && response.headers.get('content-type')?.includes('text/html')) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(APP_SHELL, copy));
        }
        return response;
      }).catch(async () => {
        const shell = await caches.match(APP_SHELL);
        if (shell) return shell;
        return new Response('Cannot reach the PDI server. Try again when the server is available.', {
          status: 503,
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        });
      })
    );
    return;
  }

  const isPublicAsset =
    url.pathname.startsWith('/assets/') ||
    url.pathname.startsWith('/icons/');
  if (!isPublicAsset) return;

  event.respondWith(
    caches.open(CACHE_NAME).then(async cache => {
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok) await cache.put(request, response.clone());
      return response;
    })
  );
});
