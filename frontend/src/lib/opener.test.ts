import { describe, expect, it } from 'vitest'
import { pickOpener, pressedControl } from './opener'

function el(isConnected = true): HTMLElement {
  return { isConnected } as unknown as HTMLElement
}

describe('pickOpener', () => {
  it('returns the focused element when a control has focus', () => {
    const body = el()
    const focused = el()

    expect(pickOpener(focused, body, el())).toBe(focused)
  })

  it('falls back to the last pressed control when focus stayed on the body', () => {
    // Safari does not focus a button when it is clicked or tapped.
    const body = el()
    const pressed = el()

    expect(pickOpener(body, body, pressed)).toBe(pressed)
  })

  it('falls back to the last pressed control when nothing has focus', () => {
    const pressed = el()

    expect(pickOpener(null, el(), pressed)).toBe(pressed)
  })

  it('returns null when the pressed control has left the page', () => {
    const body = el()

    expect(pickOpener(body, body, el(false))).toBeNull()
  })

  it('returns null when nothing has focus and nothing was pressed', () => {
    const body = el()

    expect(pickOpener(body, body, null)).toBeNull()
  })
})

describe('pressedControl', () => {
  it('finds the control around the element that received the press', () => {
    const button = el()
    const icon = { closest: () => button } as unknown as EventTarget

    expect(pressedControl(icon)).toBe(button)
  })

  it('returns null when the press landed outside any control', () => {
    const text = { closest: () => null } as unknown as EventTarget

    expect(pressedControl(text)).toBeNull()
  })

  it('returns null when the target is not an element', () => {
    expect(pressedControl(null)).toBeNull()
    expect(pressedControl({} as EventTarget)).toBeNull()
  })
})
