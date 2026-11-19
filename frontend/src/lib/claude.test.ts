import { describe, expect, it, vi } from 'vitest'
import { accountsText, composeForClaude, copyText, dossierPath, hashFrom, pastedBody, sizeText } from '@/lib/claude'

describe('dossierPath', () => {
  it('lleva solo el mes y las cuentas', () => {
    expect(dossierPath('2026-02', null)).toBe('/api/dossier?mes=2026-02')
    expect(dossierPath('2026-02', ['bhd:1', 'card:2'])).toBe('/api/dossier?mes=2026-02&cuentas=bhd%3A1%2Ccard%3A2')
  })
})

describe('composeForClaude', () => {
  it('pone la instrucción arriba y el dossier debajo', () => {
    expect(composeForClaude('  Analiza.  ', '# Dossier\n')).toBe('Analiza.\n\n---\n\n# Dossier\n')
  })
  it('sin instrucción va solo el dossier', () => {
    expect(composeForClaude('   ', '# Dossier')).toBe('# Dossier\n')
  })
})

describe('sizeText', () => {
  it('bytes y palabras', () => {
    expect(sizeText('hola mundo')).toBe('10 B · 2 palabras')
    expect(sizeText('a '.repeat(1024))).toBe('2.0 KB · 1,024 palabras')
  })
})

describe('copyText', () => {
  it('copia con el portapapeles en un contexto seguro', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    expect(await copyText('x', { isSecureContext: true, clipboard: { writeText } })).toBe('copiado')
    expect(writeText).toHaveBeenCalledWith('x')
  })
  it('a mano si el navegador lo niega', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denegado'))
    expect(await copyText('x', { isSecureContext: true, clipboard: { writeText } })).toBe('manual')
  })
  it('a mano sin contexto seguro o sin portapapeles (sin intentarlo)', async () => {
    const writeText = vi.fn()
    expect(await copyText('x', { isSecureContext: false, clipboard: { writeText } })).toBe('manual')
    expect(await copyText('x', { isSecureContext: true })).toBe('manual')
    expect(writeText).not.toHaveBeenCalled()
  })
})

describe('pastedBody', () => {
  it('es un análisis nuevo con las cuentas copiadas', () => {
    expect(pastedBody('Texto', null, null)).toEqual({ text: 'Texto', fresh: true, accounts: null })
    expect(pastedBody('Texto', ['a'], 'abcdef0123456789')).toEqual({
      text: 'Texto',
      fresh: true,
      accounts: ['a'],
      huella: 'abcdef0123456789',
    })
  })
})

describe('hashFrom', () => {
  it('toma la huella de la cabecera solo si tiene la forma esperada', () => {
    expect(hashFrom(new Headers({ 'X-Finanzas-Huella': '0123456789abcdef' }))).toBe('0123456789abcdef')
    expect(hashFrom(new Headers({ 'X-Finanzas-Huella': 'otra-cosa' }))).toBeNull()
    expect(hashFrom(new Headers())).toBeNull()
  })
})

describe('accountsText', () => {
  it('todas o los nombres', () => {
    expect(accountsText(null, new Map())).toBe('todas')
    expect(accountsText(['a', 'b'], new Map([['a', 'Visa']]))).toBe('Visa, b')
  })
})
