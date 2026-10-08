// Network first, so you always get the latest edition when online;
// the last edition you opened is kept for when you are offline.
const CACHE = "newsdesk-{{ version }}";
const SHELL = ["./", "manifest.webmanifest", "icon-192.png", "apple-touch-icon.png", "favicon.png"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith(
    fetch(req, { cache: "no-store" })
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req.mode === "navigate" ? "./" : req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req.mode === "navigate" ? "./" : req).then((r) => r || caches.match("./")))
  );
});

// Daily reminder (see newsdesk/push.py). The payload is encrypted for this device.
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  const options = {
    body: data.body || "",
    icon: "icon-192.png",
    badge: "icon-192.png",
    tag: data.tag || "daily-news",
    renotify: true,
    data: { url: data.url || "./" },
  };
  if (data.image) options.image = data.image;
  event.waitUntil(self.registration.showNotification(data.title || "News", options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data && event.notification.data.url || "./", self.registration.scope).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if (w.url.startsWith(self.registration.scope) && "focus" in w) {
          w.navigate(target).catch(() => {});
          return w.focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});
