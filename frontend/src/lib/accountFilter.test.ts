import { describe, expect, it } from 'vitest'
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
  { key: 'aho', kind: 'savings', label: 'BHD Cuenta de ahorro 999-1' },
  { key: 'cte', kind: 'checking', label: 'FICTICIO Cuenta corriente 777-0' },
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
    throw new Error('bloqueado')
  },
  setItem: () => {
    throw new Error('bloqueado')
  },
  removeItem: () => {
    throw new Error('bloqueado')
  },
}

describe('parseKeys / selectionFromParams', () => {
  it('separa por coma, quita vacíos y repetidos y ordena', () => {
    expect(parseKeys(' visa,,mc ,visa')).toEqual(['mc', 'visa'])
    expect(parseKeys('')).toBeNull()
    expect(parseKeys(null)).toBeNull()
  })

  it('lee `cuentas` y, si falta, la `cuenta` de antes', () => {
    expect(selectionFromParams(new URLSearchParams('cuentas=visa,mc'))).toEqual(['mc', 'visa'])
    expect(selectionFromParams(new URLSearchParams('cuenta=aho'))).toEqual(['aho'])
    expect(selectionFromParams(new URLSearchParams('cuentas=visa&cuenta=aho'))).toEqual(['visa'])
    expect(selectionFromParams(new URLSearchParams('mes=2026-01'))).toBeNull()
  })
})

describe('normalize / resolveSelection', () => {
  it('todas las cuentas o ninguna conocida es "Todas" (null)', () => {
    expect(normalize(['visa', 'mc', 'aho', 'cte'], ACCOUNTS)).toBeNull()
    expect(normalize(['vieja'], ACCOUNTS)).toBeNull()
    expect(normalize(['visa', 'vieja'], ACCOUNTS)).toEqual(['visa'])
  })

  it('sin cuentas cargadas conserva las claves', () => {
    expect(normalize(['visa', 'zzz'])).toEqual(['visa', 'zzz'])
  })

  it('la URL gana sobre lo recordado; sin URL, lo recordado', () => {
    expect(resolveSelection(['visa'], 'aho,cte', ACCOUNTS)).toEqual(['visa'])
    expect(resolveSelection(null, 'aho,cte', ACCOUNTS)).toEqual(['aho', 'cte'])
    expect(resolveSelection(null, null, ACCOUNTS)).toBeNull()
  })
})

describe('atajos', () => {
  it('solo tarjetas y solo cuentas bancarias', () => {
    expect(shortcutSelection('cards', ACCOUNTS)).toEqual(['mc', 'visa'])
    expect(shortcutSelection('banks', ACCOUNTS)).toEqual(['aho', 'cte'])
    expect(shortcutSelection('all', ACCOUNTS)).toBeNull()
  })

  it('reconoce el atajo vigente', () => {
    expect(isShortcut('cards', ['mc', 'visa'], ACCOUNTS)).toBe(true)
    expect(isShortcut('cards', ['visa'], ACCOUNTS)).toBe(false)
    expect(isShortcut('all', null, ACCOUNTS)).toBe(true)
  })

  it('no ofrece un atajo sin cuentas de ese tipo', () => {
    const cardsOnly = ACCOUNTS.filter((a) => a.kind === 'credit_card')
    expect(hasShortcut('banks', cardsOnly)).toBe(false)
    expect(hasShortcut('cards', cardsOnly)).toBe(false) // serían todas: es "Todas"
    expect(hasShortcut('cards', ACCOUNTS)).toBe(true)
  })
})

describe('toggle', () => {
  it('desde "Todas" quita una; volver a marcarla regresa a "Todas"', () => {
    const without = toggle('mc', null, ACCOUNTS)
    expect(without).toEqual(['aho', 'cte', 'visa'])
    expect(toggle('mc', without, ACCOUNTS)).toBeNull()
  })

  it('la última cuenta elegida no se puede quitar', () => {
    expect(toggle('visa', ['visa'], ACCOUNTS)).toEqual(['visa'])
  })
})

describe('textos', () => {
  it('botón: Todas, n de m o la cuenta sola (nombre corto)', () => {
    expect(buttonLabel(null, ACCOUNTS)).toBe('Cuentas: Todas')
    expect(buttonLabel(['aho', 'visa'], ACCOUNTS)).toBe('Cuentas: 2 de 4')
    expect(buttonLabel(['visa'], ACCOUNTS)).toBe('VISA DEMO ···4242')
    expect(buttonLabel(['aho'], ACCOUNTS)).toBe('Ahorro ···9991')
  })

  it('alcance para el subtítulo', () => {
    expect(scopeText(null, ACCOUNTS)).toBe('todas tus cuentas')
    expect(scopeText(['visa'], ACCOUNTS)).toBe('VISA DEMO ···4242')
    expect(scopeText(['visa', 'mc'], ACCOUNTS)).toBe('2 de 4 cuentas')
    expect(scopeText(null, ACCOUNTS, 'todas las cuentas')).toBe('todas las cuentas')
  })

  it('¿hay alguna tarjeta elegida?', () => {
    expect(includesCard(null, ACCOUNTS)).toBe(true)
    expect(includesCard(['aho', 'cte'], ACCOUNTS)).toBe(false)
    expect(includesCard(['aho', 'mc'], ACCOUNTS)).toBe(true)
  })
})

describe('rutas', () => {
  it('agrega accounts= a la API solo con selección', () => {
    expect(withAccounts('/api/summary?month=2026-01', null)).toBe('/api/summary?month=2026-01')
    expect(withAccounts('/api/summary?month=2026-01', ['mc', 'visa'])).toBe(
      '/api/summary?month=2026-01&accounts=mc%2Cvisa',
    )
    expect(withAccounts('/api/months', ['visa'])).toBe('/api/months?accounts=visa')
  })

  it('los enlaces a Transacciones llevan la selección', () => {
    expect(transactionsHref({ mes: '2026-01', categoria: 'Salud' }, null)).toBe(
      '/transacciones?mes=2026-01&categoria=Salud',
    )
    expect(transactionsHref({ mes: '2026-01' }, ['visa'])).toBe(
      '/transacciones?mes=2026-01&cuentas=visa',
    )
  })
})

describe('almacenamiento', () => {
  it('recuerda la selección y "Todas" la olvida', () => {
    const storage = memoryStorage()
    writeStored(['mc', 'visa'], storage)
    expect(storage.data.get(STORAGE_KEY)).toBe('mc,visa')
    expect(readStored(storage)).toBe('mc,visa')
    writeStored(null, storage)
    expect(readStored(storage)).toBeNull()
  })

  it('si el navegador no deja leer ni escribir, sigue sin recordar', () => {
    expect(readStored(broken)).toBeNull()
    expect(() => writeStored(['visa'], broken)).not.toThrow()
    expect(readStored(undefined)).toBeNull()
  })
})

describe('storedUpdate', () => {
  it('recuerda la selección válida de la URL si difiere de la recordada', () => {
    expect(storedUpdate(['visa'], 'aho,cte', ACCOUNTS)).toEqual(['visa'])
    expect(storedUpdate(['visa', 'vieja'], null, ACCOUNTS)).toEqual(['visa'])
  })

  it('una URL con todas las cuentas olvida lo recordado', () => {
    expect(storedUpdate(['aho', 'cte', 'mc', 'visa'], 'visa', ACCOUNTS)).toBeNull()
  })

  it('nada que escribir sin URL, sin cuentas cargadas o si ya es igual', () => {
    expect(storedUpdate(null, 'visa', ACCOUNTS)).toBeUndefined()
    expect(storedUpdate(['visa'], null, undefined)).toBeUndefined()
    expect(storedUpdate(['visa'], 'visa', ACCOUNTS)).toBeUndefined()
    expect(storedUpdate(['vieja'], null, ACCOUNTS)).toBeUndefined() // nada válido: todas = nada
  })
})

describe('hrefWithSelection', () => {
  it('lleva la selección a Recurrentes; sin nada queda la ruta sola', () => {
    expect(hrefWithSelection('/recurrentes', {}, null)).toBe('/recurrentes')
    expect(hrefWithSelection('/recurrentes', {}, ['mc', 'visa'])).toBe(
      '/recurrentes?cuentas=mc%2Cvisa',
    )
  })
})
