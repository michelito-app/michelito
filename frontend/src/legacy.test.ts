import { describe, expect, it } from 'vitest'
import { LEGACY_STORAGE_KEY, legacyRedirect, translateAccountKeys, translateFingerprint } from './legacy'

describe('legacyRedirect', () => {
  it.each([
    ['/transacciones', '', '/transactions'],
    ['/presupuesto', '', '/budget'],
    ['/pendientes', '', '/pending'],
    ['/compartidos', '', '/shared'],
    ['/inversiones', '', '/investments'],
    ['/recurrentes', '', '/recurring'],
    ['/reportes', '', '/reports'],
    ['/cuentas', '', '/accounts'],
    ['/categorias', '', '/categories'],
    ['/bitacora', '', '/log'],
    ['/importar', '', '/import'],
    ['/pendientes/', '', '/pending'],
  ])('%s → %s', (path, search, target) => {
    expect(legacyRedirect(path, search)).toBe(target)
  })

  it('keeps the query string, translating parameter names and values', () => {
    expect(
      legacyRedirect('/transacciones', '?mes=2026-02&cuentas=bhd:1,manual:caja-fuerte&tipo=gastos&agrupar=comercio&q=cafe'),
    ).toBe('/transactions?month=2026-02&accounts=bhd%3A1%2Cmanual%3Acash-box&kind=expense&group=merchant&q=cafe')
    expect(legacyRedirect('/transacciones', '?mes=2026-01&tx=caja-7')).toBe('/transactions?month=2026-01&tx=cash-7')
    expect(legacyRedirect('/presupuesto', '?mes=2026-03&cuentas=visa')).toBe('/budget?month=2026-03&accounts=visa')
  })

  it('redirects a transaction link with its fingerprint', () => {
    expect(legacyRedirect('/transacciones/abc123', '?mes=2026-02')).toBe('/transactions/abc123?month=2026-02')
    expect(legacyRedirect('/transacciones/caja-3', '')).toBe('/transactions/cash-3')
  })

  it('ignores paths that are not old ones', () => {
    expect(legacyRedirect('/transactions', '?month=2026-02')).toBeNull()
    expect(legacyRedirect('/', '')).toBeNull()
    expect(legacyRedirect('/nada', '')).toBeNull()
    expect(legacyRedirect('/presupuesto/extra', '')).toBeNull()
  })
})

describe('translations', () => {
  it('translates renamed account keys and cash fingerprints only', () => {
    expect(translateAccountKeys('manual:caja-fuerte,bhd:1')).toBe('manual:cash-box,bhd:1')
    expect(translateFingerprint('caja-12')).toBe('cash-12')
    expect(translateFingerprint('a1b2c3')).toBe('a1b2c3')
  })

  it('names the pre-rename storage key', () => {
    expect(LEGACY_STORAGE_KEY).toBe('finanzas.cuentas')
  })
})
