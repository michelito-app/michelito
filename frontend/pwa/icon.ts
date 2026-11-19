// The app icon as PNG, drawn at build time (no binary files in the repository): the same mark as
// the sidebar logo, a green rounded square with a white rising line. `maskable` fills the square
// edge to edge and keeps the line inside the central safe zone.
import { deflateSync } from 'node:zlib'

const GREEN: readonly [number, number, number] = [0x1f, 0x6f, 0x5c]
const WHITE: readonly [number, number, number] = [0xff, 0xff, 0xff]
/** The logo, in its 28-unit box: corner radius, the line's points and its width. */
const RADIUS = 8
const LINE: readonly (readonly [number, number])[] = [
  [8, 18],
  [13, 12],
  [17, 15],
  [21, 9],
]
const STROKE = 2.2
/** Samples per pixel side (antialiasing). */
const SAMPLES = 4

function insideRoundedRect(x: number, y: number, size: number, radius: number): boolean {
  const cx = Math.min(Math.max(x, radius), size - radius)
  const cy = Math.min(Math.max(y, radius), size - radius)
  return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2
}

function distanceToSegment(
  px: number,
  py: number,
  [ax, ay]: readonly [number, number],
  [bx, by]: readonly [number, number],
): number {
  const dx = bx - ax
  const dy = by - ay
  const along = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
  return Math.hypot(px - (ax + along * dx), py - (ay + along * dy))
}

function onLine(x: number, y: number): boolean {
  for (let i = 1; i < LINE.length; i++) {
    if (distanceToSegment(x, y, LINE[i - 1], LINE[i]) <= STROKE / 2) return true
  }
  return false
}

/** RGBA pixels of the icon, `size` pixels square. */
export function iconPixels(size: number, maskable = false): Uint8Array {
  const pixels = new Uint8Array(size * size * 4)
  // A maskable icon is cropped to a circle of 80%: the mark shrinks to fit inside it.
  const scale = maskable ? 0.72 : 1
  const unit = 28 / size
  for (let row = 0; row < size; row++) {
    for (let col = 0; col < size; col++) {
      let background = 0
      let line = 0
      for (let sy = 0; sy < SAMPLES; sy++) {
        for (let sx = 0; sx < SAMPLES; sx++) {
          const x = (col + (sx + 0.5) / SAMPLES) * unit
          const y = (row + (sy + 0.5) / SAMPLES) * unit
          if (!maskable && !insideRoundedRect(x, y, 28, RADIUS)) continue
          background++
          const mx = 14 + (x - 14) / scale
          const my = 14 + (y - 14) / scale
          if (onLine(mx, my)) line++
        }
      }
      const total = SAMPLES * SAMPLES
      const share = background === 0 ? 0 : line / background
      const offset = (row * size + col) * 4
      for (let c = 0; c < 3; c++) {
        pixels[offset + c] = Math.round(GREEN[c] + (WHITE[c] - GREEN[c]) * share)
      }
      pixels[offset + 3] = Math.round((background / total) * 255)
    }
  }
  return pixels
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})

export function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

function chunk(type: string, data: Uint8Array): Buffer {
  const head = Buffer.alloc(8)
  head.writeUInt32BE(data.length, 0)
  head.write(type, 4, 'ascii')
  const body = Buffer.concat([head.subarray(4), Buffer.from(data)])
  const tail = Buffer.alloc(4)
  tail.writeUInt32BE(crc32(body), 0)
  return Buffer.concat([head.subarray(0, 4), body, tail])
}

/** A PNG file (8-bit RGBA, no interlace) from RGBA pixels. */
export function encodePng(size: number, pixels: Uint8Array): Buffer {
  const header = Buffer.alloc(13)
  header.writeUInt32BE(size, 0)
  header.writeUInt32BE(size, 4)
  header[8] = 8 // bit depth
  header[9] = 6 // RGBA
  const raw = Buffer.alloc(size * (size * 4 + 1))
  for (let row = 0; row < size; row++) {
    raw[row * (size * 4 + 1)] = 0 // filter: none
    Buffer.from(pixels.buffer, pixels.byteOffset + row * size * 4, size * 4).copy(
      raw,
      row * (size * 4 + 1) + 1,
    )
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', new Uint8Array()),
  ])
}

export function iconPng(size: number, maskable = false): Buffer {
  return encodePng(size, iconPixels(size, maskable))
}
