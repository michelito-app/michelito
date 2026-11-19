import { describe, expect, it } from 'vitest'
import { lockScroll } from './scrollLock'

function fakeRoot(overflow: string): HTMLElement {
  return { style: { overflow } } as unknown as HTMLElement
}

describe('lockScroll', () => {
  it('locks once and restores the saved value when the last lock is released', () => {
    const root = fakeRoot('auto')
    const outer = lockScroll(root)
    expect(root.style.overflow).toBe('hidden')
    const inner = lockScroll(root)
    inner()
    expect(root.style.overflow).toBe('hidden')
    // Releasing twice does not count twice.
    inner()
    expect(root.style.overflow).toBe('hidden')
    outer()
    expect(root.style.overflow).toBe('auto')
  })
})
