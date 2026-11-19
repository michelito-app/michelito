// Vite plugin: the installable app (PWA). At build time it writes the icons, the manifest and the
// service worker (`sw.js`, with the list of this build's files and a version that changes with
// them). In development nothing is written and no worker is registered.
import { createHash } from 'node:crypto'
import type { Plugin } from 'vite'
import { iconPng } from './icon.ts'
import { serviceWorkerSource } from './sw.ts'

export const THEME_COLOR = '#1f6f5c'
export const BACKGROUND_COLOR = '#f7f7f5'

const ICONS = [
  { file: 'icons/icon-192.png', size: 192, maskable: false },
  { file: 'icons/icon-512.png', size: 512, maskable: false },
  { file: 'icons/icon-maskable-512.png', size: 512, maskable: true },
  // iOS ignores transparency and rounds the corners itself: the full-bleed version.
  { file: 'icons/apple-touch-icon.png', size: 180, maskable: true },
] as const

/** The web app manifest (the product name is not translated). */
export function manifest(): Record<string, unknown> {
  return {
    name: 'Michelito',
    short_name: 'Michelito',
    lang: 'es',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    background_color: BACKGROUND_COLOR,
    theme_color: THEME_COLOR,
    icons: ICONS.filter((icon) => icon.file !== 'icons/apple-touch-icon.png').map((icon) => ({
      src: `/${icon.file}`,
      sizes: `${icon.size}x${icon.size}`,
      type: 'image/png',
      purpose: icon.maskable ? 'maskable' : 'any',
    })),
  }
}

/** Does a built file belong to the cached app shell? */
export function isShell(name: string): boolean {
  if (name === 'index.html' || name === 'manifest.webmanifest') return true
  if (name.startsWith('icons/')) return true
  if (/\.(js|css)$/.test(name)) return true
  return /(^|\/)inter-latin-\d+-normal-[\w-]+\.woff2$/.test(name)
}

export function pwa(): Plugin {
  return {
    name: 'michelito-pwa',
    apply: 'build',
    // After the HTML plugin, so index.html is already in the bundle.
    enforce: 'post',
    generateBundle(_options, bundle) {
      for (const icon of ICONS) {
        this.emitFile({ type: 'asset', fileName: icon.file, source: iconPng(icon.size, icon.maskable) })
      }
      this.emitFile({
        type: 'asset',
        fileName: 'manifest.webmanifest',
        source: `${JSON.stringify(manifest(), null, 2)}\n`,
      })
      // The shell: index.html (as "/"), JS, CSS, the icons, the manifest and the Latin fonts
      // (the other alphabets and the old .woff copies load from the network if ever needed).
      // (What this plugin emits is not in `bundle` yet: it is added by name.)
      const emitted = [...ICONS.map((icon) => icon.file), 'manifest.webmanifest']
      const files = [...new Set([...Object.keys(bundle), ...emitted])].filter(isShell).sort()
      const hash = createHash('sha256')
      for (const name of files) {
        const item = bundle[name] as (typeof bundle)[string] | undefined
        hash.update(name)
        // index.html is not hashed by name: its content decides.
        if (item?.type === 'asset' && name === 'index.html') hash.update(item.source)
      }
      const precache = [
        '/',
        ...files.filter((name) => name !== 'index.html').map((name) => `/${name}`),
      ]
      this.emitFile({
        type: 'asset',
        fileName: 'sw.js',
        source: serviceWorkerSource(hash.digest('hex').slice(0, 16), precache),
      })
    },
  }
}
