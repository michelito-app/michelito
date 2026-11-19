import { describe, expect, it } from 'vitest'
import {
  afterReservesNote,
  asideNotes,
  barShare,
  bodyFromSuggestion,
  capInput,
  dueText,
  membersResultText,
  missingText,
  overviewText,
  parsePesos,
  scheduleMonths,
  scheduleOf,
  scheduleText,
  shiftMonth,
  spentText,
  suggestionText,
  warningText,
  yearText,
  type ReserveSuggestion,
} from './budget'

describe('presupuesto', () => {
  it('dice lo gastado frente al tope y el ancho de la barra', () => {
    expect(spentText({ spent_cents: 1_200_000, cap_cents: 1_000_000 })).toBe(
      'RD$ 12,000 de RD$ 10,000',
    )
    expect(spentText({ spent_cents: 400_000, cap_cents: null })).toBe('RD$ 4,000 · sin presupuesto')
    expect(barShare({ spent_cents: 500_000, cap_cents: 1_000_000 })).toEqual({ share: 50, over: false })
    expect(barShare({ spent_cents: 1_500_000, cap_cents: 1_000_000 })).toEqual({ share: 100, over: true })
    expect(barShare({ spent_cents: 100, cap_cents: 0 })).toEqual({ share: 100, over: true })
    expect(barShare({ spent_cents: 100, cap_cents: null })).toEqual({ share: 0, over: false })
  })

  it('pone aparte los gastos únicos, lo cubierto y lo que no tiene tasa', () => {
    expect(asideNotes({ one_offs_cents: 4_500_000, covered_cents: 340_000, without_rate: 2 })).toEqual([
      '+ RD$ 45,000 en gastos únicos',
      'RD$ 3,400 cubiertos por reservas',
      '2 gastos en US$ sin tasa',
    ])
    expect(asideNotes({ one_offs_cents: 0, covered_cents: 0, without_rate: 0 })).toEqual([])
  })

  it('avisa cuando lo habitual cambió', () => {
    const warning = { habitual_cents: 2_500_000, basis_cents: 2_000_000, up: true }
    expect(warningText({ category: 'Delivery', warning, cap_cents: 2_000_000 })).toBe(
      'Lo habitual de Delivery subió a RD$ 25,000; ¿actualizar el tope?',
    )
    expect(warningText({ category: 'Cine', warning, cap_cents: null })).toBe(
      'Lo habitual de Cine subió a RD$ 25,000; ¿poner ese tope?',
    )
    expect(warningText({ category: 'Cine', warning: null, cap_cents: null })).toBe('')
  })

  it('lee los montos escritos y los vuelve a escribir', () => {
    expect(parsePesos('16,500')).toBe(1_650_000)
    expect(parsePesos('RD$ 3500.5')).toBe(350_050)
    expect(parsePesos('')).toBeNull()
    expect(parsePesos('mil')).toBeNull()
    expect(capInput(1_650_000)).toBe('16500')
    expect(capInput(null)).toBe('')
  })

  it('resume el mes para el Resumen', () => {
    expect(overviewText({ over_count: 0, over_cents: 0 })).toBe('Presupuesto: todo dentro del tope')
    expect(overviewText({ over_count: 1, over_cents: 480_000 })).toBe(
      'Presupuesto: 1 categoría pasada (+RD$ 4,800)',
    )
    expect(overviewText({ over_count: 3, over_cents: 100 })).toBe(
      'Presupuesto: 3 categorías pasadas (+RD$ 1)',
    )
    // Con filtro de cuentas no se cuentan; con datos parciales no se afirma «todo dentro».
    expect(overviewText({ over_count: null, over_cents: 0 })).toBe(
      'Presupuesto: con filtro de cuentas no se cuentan las pasadas',
    )
    expect(overviewText({ over_count: 0, over_cents: 0, missing: ['VISA ···4242'] })).toBe(
      'Presupuesto: nada pasado por ahora (datos parciales)',
    )
    expect(missingText(['VISA ···4242', 'MC ···5151'])).toBe(
      'Datos parciales: falta el estado de VISA ···4242, MC ···5151.',
    )
    expect(missingText([])).toBeNull()
  })

  it('las devoluciones de más van aparte', () => {
    expect(
      asideNotes({ one_offs_cents: 0, covered_cents: 0, without_rate: 0, refunds_cents: 1_073_700 }),
    ).toEqual(['devoluciones: RD$ 10,737'])
  })

  it('«después de apartar» resta lo de las reservas sin cambiar el número principal', () => {
    expect(afterReservesNote(1_700_000, 260_000)).toBe(
      'después de apartar para tus reservas (RD$ 2,600/mes): RD$ 14,400',
    )
    expect(afterReservesNote(100_000, 260_000)).toBe(
      'después de apartar para tus reservas (RD$ 2,600/mes): −RD$ 1,600',
    )
    expect(afterReservesNote(null, 260_000)).toBeNull()
    expect(afterReservesNote(1_700_000, 0)).toBeNull()
  })
})

describe('reservas', () => {
  it('dice cada cuánto vence', () => {
    expect(scheduleText({ every_months: 12, due_month: '2027-01' })).toBe('Cada año en enero')
    expect(scheduleText({ every_months: 6, due_month: '2026-09' })).toBe(
      'Cada 6 meses (marzo y septiembre)',
    )
    expect(scheduleText({ every_months: null, due_month: '2026-12' })).toBe(
      'Una vez, en diciembre 2026',
    )
    expect(scheduleText({ every_months: 3, due_month: '2026-02' })).toBe(
      'Cada 3 meses desde febrero 2026',
    )
    expect(shiftMonth('2026-11', 3)).toBe('2027-02')
    expect(scheduleMonths('anual')).toBe(12)
    expect(scheduleMonths('una')).toBeNull()
    expect(scheduleOf(6)).toBe('semestral')
    expect(scheduleOf(null)).toBe('una')
  })

  it('dice el vencimiento y este año', () => {
    expect(dueText({ next_due: '2026-03' })).toBe('Vence en marzo 2026')
    expect(dueText({ next_due: null })).toBe('Ya venció')
    expect(yearText({ year_spent_cents: 340_000, year_estimated_cents: 350_000 })).toBe(
      'Este año: RD$ 3,400 de RD$ 3,500',
    )
  })

  it('arma la sugerencia y la reserva que crea', () => {
    const item: ReserveSuggestion = {
      key: 'pico:Entretenimiento:12',
      name: 'Diciembre: Entretenimiento',
      amount_cents: 1_800_000,
      category_id: 7,
      category: 'Entretenimiento',
      due_month: '2026-12',
      every_months: 12,
      multiple: true,
      reason: 'Pico en diciembre en 2 años (2024, 2025)',
    }
    expect(suggestionText(item)).toBe(
      '¿Crear reserva “Diciembre: Entretenimiento” por ≈ RD$ 18,000 (vence en diciembre)?',
    )
    expect(bodyFromSuggestion(item)).toEqual({
      name: 'Diciembre: Entretenimiento',
      amount_cents: 1_800_000,
      category_id: 7,
      due_month: '2026-12',
      every_months: 12,
      multiple: true,
      source: 'pico:Entretenimiento:12',
    })
  })

  it('dice el resultado de vincular varios', () => {
    const skipped = [
      { fingerprint: 'a', reason: 'vinculo', message: 'ya está en un vínculo' },
      { fingerprint: 'b', reason: 'vinculo', message: 'ya está en un vínculo' },
    ]
    expect(membersResultText({ applied: ['x', 'y'], skipped, entry_id: 3 }, 'Navidad')).toBe(
      '2 vinculadas a «Navidad». 2 no se vincularon: ya está en un vínculo.',
    )
    expect(membersResultText({ applied: ['x'], skipped: [], entry_id: 3 }, 'Navidad')).toBe(
      '1 vinculada a «Navidad».',
    )
  })
})
