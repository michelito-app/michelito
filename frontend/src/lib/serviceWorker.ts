// Registers the service worker of the built app (see frontend/pwa/sw.ts): it only keeps the
// static interface, never the data. Not in development, nor where the browser lacks it.
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {
      // Without it the app works the same, it just cannot open offline.
    })
  })
}
