import { describe, expect, it } from 'vitest'
import type { ExchangeInfo, GroupExpense, GroupRef, LinkedTx, SharedInfo, Tx } from './api'
import {
  backPath,
  categoryLocked,
  exchangeLine,
  expenseStatus,
  groupLabel,
  linkBadges,
  linkedAmount,
  linkedLabel,
  linkPagePath,
  linkSummaries,
  listPath,
  moneyList,
  overWarning,
  parseCents,
  sharedBody,
  sharedStats,
  showExchange,
  showReimbursement,
  showShared,
  splitDraftOf,
  splitText,
  unconvertedWarning,
} from './links'

function expense(overrides: Partial<GroupExpense> = {}): GroupExpense {
  return {
    fingerprint: 'e',
    day: '2026-02-02',
    merchant: 'RESTAURANTE',
    account_label: 'Visa',
    amount_cents: 185_000,
    currency: 'DOP',
    people: 3,
    my_share_cents: null,
    for_other: false,
    share_cents: 61_667,
    counted_cents: 61_667,
    reimbursed_cents: 61_667,
    pending_cents: 61_666,
    written_off_cents: 0,
    ...overrides,
  }
}

function shared(overrides: Partial<SharedInfo> = {}): SharedInfo {
  return {
    id: 1,
    title: 'Ana y Luis',
    name: '',
    with_whom: 'Ana y Luis',
    first_fingerprint: 'e',
    expense_count: 1,
    pending: [{ currency: 'DOP', cents: 61_666 }],
    last_split: { people: 3, my_share_cents: null, for_other: false },
    written_off: false,
    expenses: [expense()],
    totals: [
      {
        currency: 'DOP',
        share_cents: 61_667,
        reimbursed_cents: 61_667,
        pending_cents: 61_666,
        written_off_cents: 0,
      },
    ],
    excess: [],
    unconverted: [],
    reimbursements: [],
    manual: [],
    ...overrides,
  }
}

function tx(overrides: Partial<Tx> = {}): Tx {
  return {
    fingerprint: 'f',
    day: '2026-02-02',
    merchant: 'RESTAURANTE',
    description: 'RESTAURANTE',
    category: 'Restaurantes',
    category_id: 2,
    kind: 'gasto',
    original_category: 'Restaurantes',
    account: 'visa',
    account_label: 'Visa',
    amount_cents: 300_000,
    currency: 'DOP',
    amount_dop_cents: 300_000,
    one_off: false,
    corrected: false,
    merchant_year_count: 1,
    suggested_one_off: false,
    one_off_reasons: [],
    one_off_dismissed: false,
    note: '',
    link: '',
    gross_cents: null,
    pending_cents: 0,
    shared: null,
    reimbursement_of: null,
    suggested_group: null,
    exchange: null,
    suggested_exchange_with: null,
    can_invest: false,
    can_invest_credit: false,
    investment: null,
    investment_role: '',
    investment_capital_cents: null,
    suggested_investment: null,
    can_store: false,
    can_deposit: false,
    cash_box_role: '',
    cash_box_currency: null,
    cash_box_amount_cents: null,
    cash_entry_id: null,
    link_id: null,
    can_share: false,
    can_reimburse: false,
    can_exchange: false,
    ...overrides,
  }
}

const LINKED: LinkedTx = {
  fingerprint: 'e',
  day: '2026-02-02',
  merchant: 'RESTAURANTE',
  account_label: 'Visa',
  amount_cents: -100_000,
  currency: 'DOP',
}

describe('splitText / sharedStats', () => {
  it('dice cómo se repartió cada gasto', () => {
    expect(splitText(expense(), 'DOP')).toBe('Éramos 3')
    expect(splitText(expense({ people: null, my_share_cents: 40_000 }), 'DOP')).toBe(
      'Mi parte: RD$ 400',
    )
    expect(splitText(expense({ people: null, for_other: true }), 'USD')).toBe(
      'Lo pagaste por otra persona',
    )
  })

  it('tu parte, lo devuelto y lo pendiente del grupo', () => {
    expect(sharedStats(shared())).toEqual([
      { label: 'Tu parte', value: 'RD$ 617' },
      { label: 'Devuelto', value: 'RD$ 617' },
      { label: 'Te deben', value: 'RD$ 617' },
    ])
    const lost = shared({
      written_off: true,
      totals: [
        {
          currency: 'DOP',
          share_cents: 61_667,
          reimbursed_cents: 61_667,
          pending_cents: 0,
          written_off_cents: 61_666,
        },
      ],
    })
    expect(sharedStats(lost)[2]).toEqual({ label: 'No pagarán', value: 'RD$ 617' })
  })

  it('por moneda cuando el grupo tiene gastos en RD$ y US$', () => {
    const both = shared({
      totals: [
        {
          currency: 'DOP',
          share_cents: 600_000,
          reimbursed_cents: 300_000,
          pending_cents: 300_000,
          written_off_cents: 0,
        },
        {
          currency: 'USD',
          share_cents: 0,
          reimbursed_cents: 10_000,
          pending_cents: 12_000,
          written_off_cents: 0,
        },
      ],
    })
    expect(sharedStats(both)).toEqual([
      { label: 'Tu parte', value: 'RD$ 6,000' },
      { label: 'Devuelto', value: 'RD$ 3,000 + US$ 100.00' },
      { label: 'Te deben', value: 'RD$ 3,000 + US$ 120.00' },
    ])
    expect(moneyList([{ currency: 'USD', cents: 0 }])).toBe('US$ 0.00')
  })

  it('el estado de cada gasto tras imputar los reembolsos', () => {
    expect(expenseStatus(expense())).toBe('Pendiente RD$ 617')
    expect(expenseStatus(expense({ pending_cents: 0 }))).toBe('Saldado')
    expect(expenseStatus(expense({ pending_cents: 0, written_off_cents: 50_000 }))).toBe(
      'No pagarán RD$ 500',
    )
  })

  it('avisa si te devolvieron de más o si falta una tasa', () => {
    expect(overWarning(shared())).toBeNull()
    expect(overWarning(shared({ excess: [{ currency: 'DOP', cents: 10_000 }] }))).toBe(
      'Te devolvieron RD$ 100 más de lo que te debían: eso no cuenta. ¿Hay un reembolso repetido (uno a mano y el mismo importado)? Quita uno.',
    )
    expect(unconvertedWarning(shared())).toBeNull()
    expect(unconvertedWarning(shared({ unconverted: ['c'] }))).toBe(
      'Un reembolso no cuenta (o no del todo): falta la tasa de su mes para pasarlo a la moneda del gasto.',
    )
  })

  it('un grupo en una lista: título y lo que te deben', () => {
    const ref: GroupRef = {
      ...shared(),
      title: 'Carola y Rafael',
      pending: [{ currency: 'USD', cents: 91_237 }],
    }
    expect(groupLabel(ref)).toBe('Carola y Rafael · te deben US$ 912.37')
    expect(groupLabel({ ...ref, pending: [] })).toBe('Carola y Rafael · saldado')
  })
})

describe('linkBadges', () => {
  it('compartido con lo que te deben, reembolso, cambio y sugerencias', () => {
    expect(linkBadges(tx())).toEqual([])
    const labels = (row: Tx) => linkBadges(row).map((b) => b.label)
    expect(labels(tx({ link: 'shared', shared: shared(), pending_cents: 200_000 }))).toEqual([
      'Compartido',
      'te deben RD$ 2,000',
    ])
    expect(labels(tx({ link: 'shared', shared: shared(), pending_cents: 0 }))).toEqual([
      'Compartido',
    ])
    // Un reembolso lleva su grupo, pero no es «Compartido».
    expect(labels(tx({ link: 'reimbursement', shared: shared() }))).toEqual(['Reembolso'])
    expect(labels(tx({ link: 'reimbursement', reimbursement_of: LINKED }))).toEqual(['Reembolso'])
    expect(labels(tx({ suggested_group: shared() }))).toEqual(['¿Reembolso?'])
    expect(labels(tx({ suggested_exchange_with: LINKED }))).toEqual(['¿Cambio?'])
  })
})

describe('linkedLabel / linkedAmount', () => {
  it('nombre con el día y monto con signo', () => {
    expect(linkedLabel(LINKED)).toBe('RESTAURANTE (2 de febrero)')
    expect(linkedAmount(LINKED)).toBe('+RD$ 1,000')
    expect(linkedAmount({ ...LINKED, amount_cents: 100_000, currency: 'USD' })).toBe('US$ 1,000.00')
  })

  it('un crédito en la otra moneda del gasto lleva lo que vale en ella', () => {
    const pesos = { ...LINKED, amount_cents: -60_000, converted_currency: 'USD' }
    expect(linkedAmount({ ...pesos, converted_cents: 1_000 })).toBe('+RD$ 600 ≈ US$ 10.00')
    expect(linkedAmount({ ...pesos, converted_cents: null })).toBe('+RD$ 600 · sin tasa del mes')
  })
})

describe('exchangeLine', () => {
  const exchange: ExchangeInfo = {
    id: 1,
    rate: '62.5000',
    implied_rate: '80.0000',
    agreed_rate: '62.5000',
    closed: false,
    base: 'DOP',
    totals: [
      { currency: 'DOP', cents: 12_000_000 },
      { currency: 'USD', cents: 150_000 },
    ],
    pending_cents: 42_000,
    pending_currency: 'USD',
    pending_dop_cents: 2_625_000,
    needs_agreed_rate: false,
    legs: [],
  }

  it('lados, tasa y pendiente', () => {
    expect(exchangeLine(exchange)).toBe(
      'Cambio: RD$ 120,000 ↔ US$ 1,500.00 · tasa 62.50 · pendiente US$ 420.00 ≈ RD$ 26,250',
    )
  })

  it('completo o sin pendiente', () => {
    expect(exchangeLine({ ...exchange, closed: true, pending_cents: 0 })).toMatch(/· completo$/)
    expect(exchangeLine({ ...exchange, pending_cents: 0 })).toMatch(/· sin pendiente$/)
    expect(
      exchangeLine({ ...exchange, base: 'USD', pending_currency: 'DOP', pending_cents: 500_000 }),
    ).toBe('Cambio: US$ 1,500.00 ↔ RD$ 120,000 · tasa 62.50 · pendiente RD$ 5,000')
  })
})

describe('parseCents / sharedBody', () => {
  it('lee montos con comas, signo de moneda y hasta dos decimales', () => {
    expect(parseCents('1,850.50')).toBe(185_050)
    expect(parseCents('RD$ 400')).toBe(40_000)
    expect(parseCents('0')).toBeNull()
    expect(parseCents('1.234')).toBeNull()
    expect(parseCents('abc')).toBeNull()
  })

  it('arma el reparto o dice qué falta', () => {
    const draft = splitDraftOf(null)
    expect(sharedBody({ ...draft, people: '3' }, 300_000)).toEqual({ body: { people: 3 } })
    expect(sharedBody({ ...draft, people: '1' }, 300_000)).toEqual({
      error: 'Pon cuántos eran: de 2 a 100',
    })
    expect(sharedBody({ ...draft, mode: 'share', share: '400' }, 300_000)).toEqual({
      body: { my_share_cents: 40_000 },
    })
    expect(sharedBody({ ...draft, mode: 'share', share: '4000' }, 300_000)).toEqual({
      error: 'Tu parte no puede pasar el gasto',
    })
    expect(sharedBody({ ...draft, mode: 'other' }, 300_000)).toEqual({
      body: { for_other: true },
    })
  })

  it('el formulario parte de lo guardado', () => {
    expect(splitDraftOf(expense({ people: null, my_share_cents: 40_000 }))).toEqual({
      mode: 'share',
      people: '2',
      share: '400.00',
    })
  })
})

describe('secciones del detalle', () => {
  it('siguen las reglas del servidor y muestran también los vínculos dormidos', () => {
    expect(showShared(tx())).toBe(false)
    expect(showShared(tx({ can_share: true }))).toBe(true)
    expect(showShared(tx({ link: 'shared' }))).toBe(true) // dormido: se puede dejar de compartir
    expect(showReimbursement(tx({ can_reimburse: true }))).toBe(true)
    expect(showReimbursement(tx({ link: 'reimbursement' }))).toBe(true)
    expect(showReimbursement(tx({ amount_cents: -100, kind: 'ingreso' }))).toBe(false)
    expect(showExchange(tx({ can_exchange: true }))).toBe(true)
    expect(showExchange(tx({ link: 'exchange' }))).toBe(true)
  })

  it('la categoría de un crédito o una pata enlazados la define el vínculo', () => {
    expect(categoryLocked(tx({ link: 'reimbursement' }))).toBe(true)
    expect(categoryLocked(tx({ link: 'exchange' }))).toBe(true)
    expect(categoryLocked(tx({ link: 'cash_box' }))).toBe(true)
    expect(categoryLocked(tx({ link: 'shared' }))).toBe(false)
    expect(categoryLocked(tx())).toBe(false)
  })

  it('la insignia de un vínculo dormido sigue', () => {
    expect(linkBadges(tx({ link: 'reimbursement' })).map((b) => b.label)).toEqual(['Reembolso'])
    expect(linkBadges(tx({ link: 'exchange' })).map((b) => b.label)).toEqual(['Cambio'])
  })
})

describe('linkSummaries', () => {
  const texts = (row: Tx) => linkSummaries(row).map((s) => `${s.text} [${s.action}]`)

  it('un gasto que se puede compartir ofrece «Compartir…»', () => {
    expect(texts(tx({ can_share: true }))).toEqual([
      'Cuenta solo tu parte; lo demás queda como «te deben» [Compartir…]',
    ])
  })

  it('un gasto compartido: de qué grupo es, lo que te deben y cuántos reembolsos', () => {
    const row = tx({ link: 'shared', shared: shared({ reimbursements: [LINKED] }) })
    expect(texts(row)).toEqual([
      'Parte de Ana y Luis · te deben RD$ 617 · 1 reembolso [Gestionar…]',
    ])
    const both = shared({
      pending: [
        { currency: 'DOP', cents: 300_000 },
        { currency: 'USD', cents: 12_000 },
      ],
    })
    expect(texts(tx({ link: 'shared', shared: both }))).toEqual([
      'Parte de Ana y Luis · te deben RD$ 3,000 + US$ 120.00 · 0 reembolsos [Gestionar…]',
    ])
    expect(texts(tx({ link: 'shared', shared: shared({ pending: [] }) }))).toEqual([
      'Parte de Ana y Luis · saldado · 0 reembolsos [Gestionar…]',
    ])
  })

  it('un crédito: enlazado o por enlazar; y si puede ser un cambio', () => {
    expect(texts(tx({ link: 'reimbursement', reimbursement_of: LINKED }))).toEqual([
      'Es reembolso de RESTAURANTE (2 de febrero) [Gestionar…]',
    ])
    expect(texts(tx({ link: 'reimbursement', shared: shared() }))).toEqual([
      'Es reembolso de Ana y Luis · te deben RD$ 617 [Gestionar…]',
    ])
    expect(texts(tx({ can_reimburse: true, can_exchange: true }))).toEqual([
      '¿Es reembolso de un gasto compartido? [Gestionar…]',
      '¿Es un cambio de divisas? [Gestionar…]',
    ])
  })

  it('un cambio: pendiente, sin pendiente, completo o incompleto', () => {
    const exchange: ExchangeInfo = {
      id: 1,
      rate: '63.7000',
      implied_rate: '63.7000',
      agreed_rate: null,
      closed: false,
      base: 'DOP',
      totals: [],
      pending_cents: 100_000,
      pending_currency: 'USD',
      pending_dop_cents: 6_370_000,
      needs_agreed_rate: false,
      legs: [],
    }
    const row = (e: Partial<ExchangeInfo>) =>
      linkSummaries(tx({ link: 'exchange', exchange: { ...exchange, ...e } }))[0].text
    expect(row({})).toBe('Cambio: pendiente US$ 1,000.00')
    expect(row({ pending_cents: 0 })).toBe('Cambio: sin pendiente')
    expect(row({ closed: true, pending_cents: 0 })).toBe('Cambio: completo')
    expect(linkSummaries(tx({ link: 'exchange' }))[0].text).toBe(
      'Cambio incompleto: le falta una pata',
    )
  })
})

describe('backPath', () => {
  const row = { fingerprint: 'f 1', day: '2026-02-02' }

  it('vuelve a la lista de la que se vino', () => {
    expect(backPath(row, '/transacciones?mes=2026-02&q=cafe&tx=f')).toBe(
      '/transacciones?mes=2026-02&q=cafe&tx=f',
    )
  })

  it('si se entró directo, al mes de la transacción con ella elegida', () => {
    expect(backPath(row, undefined)).toBe('/transacciones?mes=2026-02&tx=f+1')
    expect(backPath(row, 'https://otro.sitio/')).toBe('/transacciones?mes=2026-02&tx=f+1')
    expect(linkPagePath('f 1')).toBe('/transacciones/f%201')
  })

  it('vuelve a Pendientes si se vino de ahí', () => {
    expect(backPath(row, '/pendientes')).toBe('/pendientes')
    expect(backPath(row, '/pendientes?cuentas=a')).toBe('/pendientes?cuentas=a')
    expect(backPath(row, '/pendientes-falsas')).toBe('/transacciones?mes=2026-02&tx=f+1')
    expect(listPath('/pendientes')).toBe('/pendientes')
  })

  it('vuelve a Compartidos con el chip, la búsqueda y el grupo desplegado', () => {
    const from = '/compartidos?estado=saldados&q=ropa&grupo=2'
    expect(backPath(row, from)).toBe(from)
    expect(listPath('/compartidos')).toBe('/compartidos')
  })

  it('sin la transacción, a la lista de la que se vino o a Transacciones', () => {
    expect(listPath('/transacciones?mes=2026-02')).toBe('/transacciones?mes=2026-02')
    expect(listPath('//otro.sitio/transacciones')).toBe('/transacciones')
    expect(listPath(undefined)).toBe('/transacciones')
  })
})
