// The service worker's source, written at build time with this build's version and files.
//
// It keeps only the static interface (the "app shell"): index.html, the hashed JS/CSS/fonts and
// the icons. Nothing under /api is ever answered from a cache or stored (neither Cache Storage nor
// IndexedDB): those requests are not even handled here, nor is the share target (/share-target,
// the PDFs shared from the phone), which always goes to the network. Pages are fetched from the network first,
// so after a deploy the next load gets the new interface; the cached shell only answers offline.
// A new build has a new version: it installs, takes over at once and deletes the old caches.

export const CACHE_PREFIX = 'michelito-shell-'

/** The worker's code for this build. */
export function serviceWorkerSource(version: string, precache: readonly string[]): string {
  return `// Generated at build time (frontend/pwa/sw.ts). Do not edit.
'use strict'
const CACHE = ${JSON.stringify(CACHE_PREFIX + version)}
const PRECACHE = ${JSON.stringify(precache)}
const SHELL = new Set(PRECACHE)

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(${JSON.stringify(CACHE_PREFIX)}) && key !== CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  // The shared PDFs: network only, whatever the method.
  if (url.pathname === '/share-target') return
  if (request.method !== 'GET') return
  if (url.origin !== self.location.origin) return
  // The data never goes through here: no cache, no copy.
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        caches.open(CACHE).then((cache) => cache.match('/')).then((page) => page || Response.error()),
      ),
    )
    return
  }
  if (!SHELL.has(url.pathname)) return
  event.respondWith(
    caches
      .open(CACHE)
      .then((cache) => cache.match(url.pathname))
      .then((cached) => cached || fetch(request)),
  )
})
`
}
