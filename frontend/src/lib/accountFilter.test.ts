import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { shortAccountLabel } from './accounts'
import {
  type AccountRef,
  buttonLabel,
  hasShortcut,
  hrefWithSelection,
  includesCard,
  isShortcut,
  normalize,
  parseKeys,
  readStored,
  resolveSelection,
  scopeText,
  selectionFromParams,
  shortcutSelection,
  LEGACY_STORAGE_KEY,
  STORAGE_KEY,
  storedUpdate,
  toggle,
  transactionsHref,
  withAccounts,
  writeStored,
} from './accountFilter'

const ACCOUNTS: AccountRef[] = [
  { key: 'visa', kind: 'credit_card', label: 'VISA DEMO ···4242' },
  { key: 'mc', kind: 'credit_card', label: 'MC BLACK ···9999' },
  { key: 'aho', kind: 'savings', label: 'BHD Cuenta de ahorro 999-1' }, // spanish-data
  { key: 'cte', kind: 'checking', label: 'FICTICIO Cuenta corriente 777-0' }, // spanish-data
]

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  }
}

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

describe('parseKeys / selectionFromParams', () => {
  it('splits on commas, drops empties and repeats, and sorts', () => {
    expect(parseKeys(' visa,,mc ,visa')).toEqual(['mc', 'visa'])
    expect(parseKeys('')).toBeNull()
    expect(parseKeys(null)).toBeNull()
  })

  it('reads `accounts` and, if missing, the older `account`', () => {
    expect(selectionFromParams(new URLSearchParams('accounts=visa,mc'))).toEqual(['mc', 'visa'])
    expect(selectionFromParams(new URLSearchParams('account=aho'))).toEqual(['aho'])
    expect(selectionFromParams(new URLSearchParams('accounts=visa&account=aho'))).toEqual(['visa'])
    expect(selectionFromParams(new URLSearchParams('month=2026-01'))).toBeNull()
  })
})

describe('normalize / resolveSelection', () => {
  it('all accounts or no known one is "All" (null)', () => {
    expect(normalize(['visa', 'mc', 'aho', 'cte'], ACCOUNTS)).toBeNull()
    expect(normalize(['old'], ACCOUNTS)).toBeNull()
    expect(normalize(['visa', 'old'], ACCOUNTS)).toEqual(['visa'])
  })

  it('without loaded accounts it keeps the keys', () => {
    expect(normalize(['visa', 'zzz'])).toEqual(['visa', 'zzz'])
  })

  it('the URL wins over the remembered one; without a URL, the remembered one', () => {
    expect(resolveSelection(['visa'], 'aho,cte', ACCOUNTS)).toEqual(['visa'])
    expect(resolveSelection(null, 'aho,cte', ACCOUNTS)).toEqual(['aho', 'cte'])
    expect(resolveSelection(null, null, ACCOUNTS)).toBeNull()
  })
})

describe('shortcuts', () => {
  it('cards only and bank accounts only', () => {
    expect(shortcutSelection('cards', ACCOUNTS)).toEqual(['mc', 'visa'])
    expect(shortcutSelection('banks', ACCOUNTS)).toEqual(['aho', 'cte'])
    expect(shortcutSelection('all', ACCOUNTS)).toBeNull()
  })

  it('recognizes the current shortcut', () => {
    expect(isShortcut('cards', ['mc', 'visa'], ACCOUNTS)).toBe(true)
    expect(isShortcut('cards', ['visa'], ACCOUNTS)).toBe(false)
    expect(isShortcut('all', null, ACCOUNTS)).toBe(true)
  })

  it('offers no shortcut without accounts of that kind', () => {
    const cardsOnly = ACCOUNTS.filter((a) => a.kind === 'credit_card')
    expect(hasShortcut('banks', cardsOnly)).toBe(false)
    expect(hasShortcut('cards', cardsOnly)).toBe(false) // that would be all of them: it is "All"
    expect(hasShortcut('cards', ACCOUNTS)).toBe(true)
  })
})

describe('toggle', () => {
  it('from "All" it removes one; checking it again goes back to "All"', () => {
    const without = toggle('mc', null, ACCOUNTS)
    expect(without).toEqual(['aho', 'cte', 'visa'])
    expect(toggle('mc', without, ACCOUNTS)).toBeNull()
  })

  it('the last selected account cannot be removed', () => {
    expect(toggle('visa', ['visa'], ACCOUNTS)).toEqual(['visa'])
  })
})

describe('texts', () => {
  it('button: All, n of m or the single account (short name)', () => {
    expect(buttonLabel(null, ACCOUNTS)).toBe(t('shell.accounts.buttonAll'))
    expect(buttonLabel(['aho', 'visa'], ACCOUNTS)).toBe(
      t('shell.accounts.buttonSome', { count: 2, total: 4 }),
    )
    expect(buttonLabel(['visa'], ACCOUNTS)).toBe('VISA DEMO ···4242')
    expect(buttonLabel(['aho'], ACCOUNTS)).toBe(shortAccountLabel(ACCOUNTS[2].label))
  })

  it('scope for the subtitle', () => {
    expect(scopeText(null, ACCOUNTS)).toBe(t('common.allYourAccounts'))
    expect(scopeText(['visa'], ACCOUNTS)).toBe('VISA DEMO ···4242')
    expect(scopeText(['visa', 'mc'], ACCOUNTS)).toBe(
      t('shell.accounts.scopeSome', { count: 2, total: 4 }),
    )
    expect(scopeText(null, ACCOUNTS, 'everything')).toBe('everything')
  })

  it('is any card selected?', () => {
    expect(includesCard(null, ACCOUNTS)).toBe(true)
    expect(includesCard(['aho', 'cte'], ACCOUNTS)).toBe(false)
    expect(includesCard(['aho', 'mc'], ACCOUNTS)).toBe(true)
  })
})

describe('paths', () => {
  it('adds accounts= to the API only with a selection', () => {
    expect(withAccounts('/api/summary?month=2026-01', null)).toBe('/api/summary?month=2026-01')
    expect(withAccounts('/api/summary?month=2026-01', ['mc', 'visa'])).toBe(
      '/api/summary?month=2026-01&accounts=mc%2Cvisa',
    )
    expect(withAccounts('/api/months', ['visa'])).toBe('/api/months?accounts=visa')
  })

  it('links to Transactions carry the selection', () => {
    expect(transactionsHref({ month: '2026-01', category: 'Health' }, null)).toBe(
      '/transactions?month=2026-01&category=Health',
    )
    expect(transactionsHref({ month: '2026-01' }, ['visa'])).toBe(
      '/transactions?month=2026-01&accounts=visa',
    )
  })
})

describe('storage', () => {
  it('remembers the selection and "All" forgets it', () => {
    const storage = memoryStorage()
    writeStored(['mc', 'visa'], storage)
    expect(storage.data.get(STORAGE_KEY)).toBe('mc,visa')
    expect(readStored(storage)).toBe('mc,visa')
    writeStored(null, storage)
    expect(readStored(storage)).toBeNull()
  })

  it('falls back to the legacy key until the next write removes it', () => {
    const storage = memoryStorage({ [LEGACY_STORAGE_KEY]: 'visa' })
    expect(readStored(storage)).toBe('visa')
    writeStored(['mc'], storage)
    expect(storage.data.has(LEGACY_STORAGE_KEY)).toBe(false)
    expect(readStored(storage)).toBe('mc')
    const forgotten = memoryStorage({ [LEGACY_STORAGE_KEY]: 'visa' })
    writeStored(null, forgotten)
    expect(readStored(forgotten)).toBeNull()
  })

  it('translates the renamed cash box key read from the legacy storage key', () => {
    const storage = memoryStorage({ [LEGACY_STORAGE_KEY]: 'manual:caja-fuerte,visa' }) // spanish-data: pre-rename value
    const accounts = [
      { key: 'manual:cash-box', kind: 'cash', label: 'Cash box' },
      { key: 'visa', kind: 'credit_card', label: 'Visa' },
      { key: 'mc', kind: 'credit_card', label: 'MC' },
    ]
    expect(resolveSelection(null, readStored(storage), accounts)).toEqual(['manual:cash-box', 'visa'])
  })

  it('if the browser allows neither reading nor writing, it goes on without remembering', () => {
    expect(readStored(broken)).toBeNull()
    expect(() => writeStored(['visa'], broken)).not.toThrow()
    expect(readStored(undefined)).toBeNull()
  })
})

describe('storedUpdate', () => {
  it('remembers the URL’s valid selection if it differs from the remembered one', () => {
    expect(storedUpdate(['visa'], 'aho,cte', ACCOUNTS)).toEqual(['visa'])
    expect(storedUpdate(['visa', 'old'], null, ACCOUNTS)).toEqual(['visa'])
  })

  it('a URL with all accounts forgets the remembered one', () => {
    expect(storedUpdate(['aho', 'cte', 'mc', 'visa'], 'visa', ACCOUNTS)).toBeNull()
  })

  it('nothing to write without a URL, without loaded accounts or if already equal', () => {
    expect(storedUpdate(null, 'visa', ACCOUNTS)).toBeUndefined()
    expect(storedUpdate(['visa'], null, undefined)).toBeUndefined()
    expect(storedUpdate(['visa'], 'visa', ACCOUNTS)).toBeUndefined()
    expect(storedUpdate(['old'], null, ACCOUNTS)).toBeUndefined() // nothing valid: all = nothing
  })
})

describe('hrefWithSelection', () => {
  it('carries the selection to Recurring; with nothing it is just the path', () => {
    expect(hrefWithSelection('/recurring', {}, null)).toBe('/recurring')
    expect(hrefWithSelection('/recurring', {}, ['mc', 'visa'])).toBe(
      '/recurring?accounts=mc%2Cvisa',
    )
  })
})
