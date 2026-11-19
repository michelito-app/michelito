import { describe, expect, it } from 'vitest'
import type { DuePayment, Interest, StatementLine } from './api'
import {
  interestYear,
  minimumText,
  nextDueText,
  payNote,
  payText,
  verdictText,
  yearTotalText,
} from './interest'

function toPay(patch: Partial<DuePayment> = {}): DuePayment {
  return {
    due_date: '2026-12-14',
    amounts: [
      { currency: 'DOP', cents: 4512345 },
      { currency: 'USD', cents: 3197 },
    ],
    minimums: [
      { currency: 'DOP', cents: 225000 },
      { currency: 'USD', cents: 2500 },
    ],
    text: 'VISA ···1234: paga RD$ 45,123 y US$ 31.97 antes del 14 dic para no pagar intereses',
    ...patch,
  }
}

function line(patch: Partial<StatementLine> = {}): StatementLine {
  return {
    period_start: '2026-10-21',
    period_end: '2026-11-20',
    currency: 'DOP',
    charges_cents: 1000000,
    payments_cents: 0,
    balance_cents: 1415000,
    due_date: '2026-12-14',
    minimum_payment_cents: 71000,
    paid_full: null,
    left_over_cents: null,
    paid_late: false,
    next_interest_cents: 0,
    printout: false,
    ...patch,
  }
}

function interest(patch: Partial<Interest> = {}): Interest {
  return {
    year: 2026,
    lines: [],
    total_dop_cents: 0,
    unconverted_usd_cents: 0,
    next_due: null,
    ...patch,
  }
}

describe('payText', () => {
  it('dice cuánto pagar en cada moneda y antes de cuándo', () => {
    expect(payText(toPay(), '2026-12-01')).toBe(
      'Para no pagar intereses: RD$ 45,123 y US$ 31.97 antes del 14 dic',
    )
  })

  it('el mismo día de la fecha límite todavía es "antes del"', () => {
    expect(payText(toPay(), '2026-12-14')).toMatch(/antes del 14 dic$/)
  })

  it('si la fecha límite ya pasó, dice que venció', () => {
    expect(payText(toPay(), '2026-12-15')).toBe(
      'Para no pagar intereses: RD$ 45,123 y US$ 31.97 · venció el 14 dic',
    )
  })

  it('con una moneda que no sabe mostrar usa la frase del servidor', () => {
    const odd = toPay({ amounts: [{ currency: 'EUR', cents: 1000 }], text: 'frase del servidor' })
    expect(payText(odd, '2026-12-01')).toBe('frase del servidor')
  })
})

describe('payNote', () => {
  it('línea corta para la lista de cuentas', () => {
    expect(payNote(toPay(), '2026-12-01')).toBe('Paga RD$ 45,123 y US$ 31.97 antes del 14 dic')
    expect(payNote(toPay(), '2026-12-20')).toBe('RD$ 45,123 y US$ 31.97 · venció el 14 dic')
  })
})

describe('minimumText', () => {
  it('une los mínimos de cada moneda', () => {
    expect(minimumText(toPay())).toBe('Mínimo: RD$ 2,250 y US$ 25.00')
  })

  it('sin mínimos impresos no dice nada', () => {
    expect(minimumText(toPay({ minimums: [] }))).toBeNull()
  })
})

describe('verdictText', () => {
  it('el último corte no tiene veredicto', () => {
    expect(verdictText(line())).toBeNull()
  })

  it('pagado completo', () => {
    expect(verdictText(line({ paid_full: true }))).toEqual({
      text: 'Completo',
      tone: 'paid',
      interest: null,
    })
  })

  it('pagado tarde: el saldo se cubrió pero fuera de plazo', () => {
    expect(
      verdictText(
        line({
          paid_full: false,
          paid_late: true,
          left_over_cents: 1415000,
          next_interest_cents: 28740,
        }),
      ),
    ).toEqual({ text: 'Pagado tarde', tone: 'owed', interest: '+RD$ 287 de intereses' })
  })

  it('lo que quedó sin pagar y los intereses que cobró el corte siguiente', () => {
    expect(
      verdictText(line({ paid_full: false, left_over_cents: 615000, next_interest_cents: 28740 })),
    ).toEqual({ text: 'Quedó RD$ 6,150', tone: 'owed', interest: '+RD$ 287 de intereses' })
  })

  it('en dólares con dos decimales', () => {
    const usd = line({
      currency: 'USD',
      paid_full: false,
      left_over_cents: 1050,
      next_interest_cents: 123,
    })
    expect(verdictText(usd)).toEqual({ text: 'Quedó US$ 10.50', tone: 'owed', interest: '+US$ 1.23 de intereses' })
  })

  it('intereses sin veredicto (saldo a favor) solo muestran los intereses', () => {
    expect(verdictText(line({ balance_cents: 0, next_interest_cents: 5000 }))).toEqual({
      text: null,
      tone: 'owed',
      interest: '+RD$ 50 de intereses',
    })
  })
})

describe('interestYear', () => {
  it('el año del mes que se está viendo', () => {
    expect(interestYear('2026-01')).toBe(2026)
  })
})

describe('yearTotalText', () => {
  it('total en RD$ del año', () => {
    expect(yearTotalText(interest({ total_dop_cents: 2350700 }))).toBe('RD$ 23,507')
  })
})

describe('nextDueText', () => {
  it('el próximo pago para no generar intereses', () => {
    const next = { ...toPay(), key: 'popular:credit_card', label: 'VISA ···1234' }
    expect(nextDueText(next)).toBe('Próximo: paga RD$ 45,123 y US$ 31.97 antes del 14 dic')
  })
})
