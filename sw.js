// sw.js
const CACHE_VERSION = "2026-02-24-libdpsspells13meta";
const CACHE_NAME = `lol-counter-${CACHE_VERSION}`;

// Precache stabilní soubory. Index řešíme network-first (a ukládáme jako fallback).
const PRECACHE = [
  "./manifest.json",
  "./data/log_builds.json",
  "./data/meta.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      try { await cache.addAll(PRECACHE); } catch (_) {}
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const fresh = await fetch(request, { cache: "no-store" });
    cache.put(request, fresh.clone());
    return fresh;
  } catch (e) {
    const cached = await cache.match(request);
    if (cached) return cached;
    const cachedIndex = await cache.match("./index.html");
    if (cachedIndex) return cachedIndex;
    throw e;
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const fetchPromise = fetch(request).then((res) => {
    cache.put(request, res.clone());
    return res;
  }).catch(() => null);
  return cached || fetchPromise;
}

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  const isNavigation = event.request.mode === "navigate";
  const isIndex = url.pathname.endsWith("/index.html") || url.pathname.endsWith("/");

  // index/navigace: network-first, cache jen jako fallback
  if (isNavigation || isIndex) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // ostatní statické: SWR
  event.respondWith(staleWhileRevalidate(event.request));
});