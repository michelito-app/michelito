/** What a dialog returns focus to when it closes.
 *
 * `document.activeElement` is not enough: Safari does not focus a button when it is clicked or
 * tapped, so focus stays on the body and the opener is lost. The control being pressed fills in:
 * it is remembered only while its click is handled, so a dialog that opens later on its own never
 * takes an unrelated control. */

const CONTROLS = 'button, a[href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])'

let lastPressed: HTMLElement | null = null

/** The control around the element that received a press, if any. */
export function pressedControl(target: EventTarget | null): HTMLElement | null {
  const closest = (target as Partial<Element> | null)?.closest
  if (typeof closest !== 'function') return null
  return closest.call(target, CONTROLS) as HTMLElement | null
}

/** The focused control, or else the pressed one while it is still on the page. */
export function pickOpener(
  active: HTMLElement | null,
  body: HTMLElement | null,
  pressed: HTMLElement | null,
): HTMLElement | null {
  if (active && active !== body) return active
  return pressed?.isConnected ? pressed : null
}

/** Call when a dialog opens, before it takes focus. */
export function currentOpener(): HTMLElement | null {
  const active = document.activeElement instanceof HTMLElement ? document.activeElement : null
  return pickOpener(active, document.body, lastPressed)
}

if (typeof document !== 'undefined') {
  document.addEventListener(
    'click',
    (event) => {
      lastPressed = pressedControl(event.target)
      // React renders and runs effects for a click before the next task.
      setTimeout(() => {
        lastPressed = null
      }, 0)
    },
    true,
  )
}
