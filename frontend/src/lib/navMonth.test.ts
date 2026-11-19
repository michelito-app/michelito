import { describe, expect, it } from 'vitest'
import { navHref } from './navMonth'

describe('navHref', () => {
  it('sin mes elegido, el enlace va tal cual', () => {
    expect(navHref('/', null)).toBe('/')
    expect(navHref('/transacciones', null)).toBe('/transacciones')
  })
  it('con otro mes, Resumen y Transacciones lo llevan', () => {
    expect(navHref('/', '2025-12')).toBe('/?mes=2025-12')
    expect(navHref('/transacciones', '2025-12')).toBe('/transacciones?mes=2025-12')
  })
  it('las demás pantallas no llevan mes', () => {
    expect(navHref('/pendientes', '2025-12')).toBe('/pendientes')
    expect(navHref('/cuentas', '2025-12')).toBe('/cuentas')
  })
})
