import { describe, expect, it } from 'vitest'
import { crc32, iconPixels, iconPng } from './icon.ts'
import { isShell, manifest, SHARE_TARGET, THEME_COLOR } from './plugin.ts'
import { CACHE_PREFIX, serviceWorkerSource } from './sw.ts'

describe('icon', () => {
  it('is a PNG of the requested size', () => {
    const png = iconPng(48)
    expect([...png.subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    expect(png.subarray(12, 16).toString('ascii')).toBe('IHDR')
    expect(png.readUInt32BE(16)).toBe(48)
    expect(png.readUInt32BE(20)).toBe(48)
    expect(png.subarray(-8, -4).toString('ascii')).toBe('IEND')
  })

  it('computes the standard CRC-32', () => {
    expect(crc32(new TextEncoder().encode('IEND'))).toBe(0xae426082)
  })

  it('has transparent corners, except the maskable one', () => {
    const corner = (pixels: Uint8Array) => pixels[3]
    const center = (pixels: Uint8Array, size: number) =>
      pixels[(Math.floor(size / 2) * size + 2) * 4 + 3]
    expect(corner(iconPixels(32))).toBe(0)
    expect(center(iconPixels(32), 32)).toBe(255)
    expect(corner(iconPixels(32, true))).toBe(255)
  })
})

describe('manifest', () => {
  it('is installable: name, standalone, start URL and 192/512 icons (one maskable)', () => {
    const value = manifest() as {
      name: string
      display: string
      start_url: string
      theme_color: string
      icons: { sizes: string; purpose: string }[]
    }
    expect(value.name).toBe('Michelito')
    expect(value.display).toBe('standalone')
    expect(value.start_url).toBe('/')
    expect(value.theme_color).toBe(THEME_COLOR)
    expect(value.icons.map((icon) => icon.sizes)).toEqual(['192x192', '512x512', '512x512'])
    expect(value.icons.some((icon) => icon.purpose === 'maskable')).toBe(true)
  })

  it('receives PDFs shared from the phone (Web Share Target) as a multipart POST', () => {
    const value = manifest() as {
      share_target: {
        action: string
        method: string
        enctype: string
        params: { files: { name: string; accept: string[] }[] }
      }
    }
    expect(value.share_target).toMatchObject({
      action: SHARE_TARGET,
      method: 'POST',
      enctype: 'multipart/form-data',
    })
    expect(value.share_target.params.files[0].accept).toContain('application/pdf')
  })
})

describe('app shell', () => {
  it('keeps the interface files, never the other font alphabets', () => {
    expect(isShell('index.html')).toBe(true)
    expect(isShell('assets/index-abc.js')).toBe(true)
    expect(isShell('assets/index-abc.css')).toBe(true)
    expect(isShell('icons/icon-192.png')).toBe(true)
    expect(isShell('assets/inter-latin-400-normal-abc.woff2')).toBe(true)
    expect(isShell('assets/inter-cyrillic-400-normal-abc.woff2')).toBe(false)
    expect(isShell('assets/inter-latin-400-normal-abc.woff')).toBe(false)
  })

  it('the worker carries its version and list, and leaves /api alone', () => {
    const source = serviceWorkerSource('v1', ['/', '/assets/a.js'])
    expect(source).toContain(JSON.stringify(`${CACHE_PREFIX}v1`))
    expect(source).toContain('["/","/assets/a.js"]')
    expect(source).toContain("url.pathname.startsWith('/api/')")
    expect(source).not.toMatch(/indexedDB/i)
  })

  it('leaves the share target to the network, before looking at the method', () => {
    const source = serviceWorkerSource('v1', ['/'])
    const share = source.indexOf("url.pathname === '/share-target'")
    expect(share).toBeGreaterThan(0)
    expect(share).toBeLessThan(source.indexOf("request.method !== 'GET'"))
  })
})
