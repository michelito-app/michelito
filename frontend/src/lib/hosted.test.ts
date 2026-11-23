import { describe, expect, it } from 'vitest'
import { ApiError } from '@/lib/api'
import {
  type NoticeStorage,
  accountDeleted,
  cleanCode,
  confirmsEmail,
  cooldownLeft,
  deviceLabel,
  forgetAccountDeleted,
  linkToken,
  needsStepUp,
  rememberAccountDeleted,
  validCode,
  validEmail,
} from '@/lib/hosted'

describe('hosted sign-in helpers', () => {
  it('accepts plausible emails only', () => {
    expect(validEmail(' ana@example.com ')).toBe(true)
    expect(validEmail('ana@example')).toBe(false)
    expect(validEmail('no email')).toBe(false)
  })

  it('keeps only six digits of what was typed or pasted', () => {
    expect(cleanCode('123 456')).toBe('123456')
    expect(cleanCode('12-34-56-78')).toBe('123456')
    expect(validCode('12345')).toBe(false)
    expect(validCode('123456')).toBe(true)
  })

  it('counts the resend cooldown down in whole seconds', () => {
    expect(cooldownLeft(1000, 1000)).toBe(60)
    expect(cooldownLeft(1000, 1000 + 59_500)).toBe(1)
    expect(cooldownLeft(1000, 1000 + 61_000)).toBe(0)
  })

  it('reads the desktop link token only from a well-formed fragment', () => {
    expect(linkToken('#link=abcdefghijklmnopqrstuvwxyz_-0123')).toBe(
      'abcdefghijklmnopqrstuvwxyz_-0123',
    )
    expect(linkToken('#link=short')).toBeNull()
    expect(linkToken('#other=abcdefghijklmnopqrstuvwxyz')).toBeNull()
  })

  it('names devices, unknown parts included', () => {
    expect(deviceLabel({ browser: 'Chrome', os: 'Android' })).toBe('Chrome en Android') // spanish-ui
    expect(deviceLabel({ browser: '', os: '' })).toBe('Navegador desconocido en sistema desconocido') // spanish-ui
  })

  it('opens the step-up only for the step_up_required reason', () => {
    expect(needsStepUp(new ApiError(403, 'x', 'step_up_required'))).toBe(true)
    expect(needsStepUp(new ApiError(403, 'missing header'))).toBe(false)
    expect(needsStepUp(new ApiError(401, 'x', 'step_up_required'))).toBe(false)
  })
})

describe('deleting the account', () => {
  it('confirms only with the account email, ignoring case and surrounding spaces', () => {
    expect(confirmsEmail('ana@example.com', 'ana@example.com')).toBe(true)
    expect(confirmsEmail('  Ana@example.com ', 'ana@example.com')).toBe(true)
    expect(confirmsEmail('ana@example.com.', 'ana@example.com')).toBe(false)
    expect(confirmsEmail('', 'ana@example.com')).toBe(false)
    expect(confirmsEmail('bob@example.com', 'ana@example.com')).toBe(false)
  })

  it('shows the deleted notice once after the account is deleted', () => {
    const storage = memoryStorage()
    expect(accountDeleted(storage)).toBe(false)
    rememberAccountDeleted(storage)
    expect(accountDeleted(storage)).toBe(true)
    expect(accountDeleted(storage)).toBe(true) // reading does not take it away
    forgetAccountDeleted(storage)
    expect(accountDeleted(storage)).toBe(false)
  })

  it('goes on without the notice when storage is unavailable', () => {
    const broken = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
      removeItem: () => {
        throw new Error('blocked')
      },
    }
    expect(() => rememberAccountDeleted(broken)).not.toThrow()
    expect(() => forgetAccountDeleted(broken)).not.toThrow()
    expect(accountDeleted(broken)).toBe(false)
    expect(accountDeleted(null)).toBe(false)
  })
})

function memoryStorage(): NoticeStorage {
  const items = new Map<string, string>()
  return {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => void items.set(key, value),
    removeItem: (key) => void items.delete(key),
  }
}
