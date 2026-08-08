const CACHE = 'contract-brain-browser-v1';
const CORE = [
  './contract-brain.html',
  './contract-brain.css',
  './contract-brain-search.css',
  './contract-brain.js',
  './contract-brain-search.js',
  './contract-brain-progress.js',
  './contract-brain-analysis-status.js',
  './contract-brain-ontology.js',
  './contract-brain-browser-pipeline.js',
  './contract-brain-browser-worker.js',
];
const CDN_HOSTS = new Set(['cdn.jsdelivr.net']);

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(CORE)).catch(() => null));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith('contract-brain-browser-') && key !== CACHE).map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  const sameOrigin = url.origin === self.location.origin;
  const engineAsset = CDN_HOSTS.has(url.hostname);
  if (!sameOrigin && !engineAsset) return;

  if (engineAsset) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      const hit = await cache.match(request);
      if (hit) return hit;
      const response = await fetch(request);
      if (response.ok || response.type === 'opaque') cache.put(request, response.clone()).catch(() => null);
      return response;
    })());
    return;
  }

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await fetch(request);
      if (response.ok && ['script','style','worker','document'].includes(request.destination)) cache.put(request, response.clone()).catch(() => null);
      return response;
    } catch {
      const hit = await cache.match(request);
      if (hit) return hit;
      throw new Error('offline and no cached response');
    }
  })());
});
