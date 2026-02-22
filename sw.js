const CACHE = "lol-counter-quiz-v20";
const ASSETS = [
  "./",
  "./index.html",
  "./manifest.json",
  "./sw.js",
  "./data/log_builds.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.map(k => k === CACHE ? null : caches.delete(k))))
  );
});

// Network-first pro HTML, cache-first pro ostatní.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  const isHTML =
    event.request.mode === "navigate" ||
    (event.request.headers.get("accept") || "").includes("text/html") ||
    url.pathname.endsWith("/index.html") ||
    url.pathname.endsWith("/");

  if (isHTML) {
    event.respondWith(
      fetch(event.request).then(resp => {
        const copy = resp.clone();
        caches.open(CACHE).then(c => c.put(event.request, copy)).catch(()=>{});
        return resp;
      }).catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(hit => hit || fetch(event.request).then(resp => {
      const copy = resp.clone();
      caches.open(CACHE).then(c => c.put(event.request, copy)).catch(()=>{});
      return resp;
    }))
  );
});











