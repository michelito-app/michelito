import { describe, expect, it } from 'vitest'
import type { Account, StatementLine } from './api'
import {
  amountText,
  cutLine,
  cutText,
  dueNote,
  footnote,
  groupAccounts,
  isCreditCard,
  missingMonth,
  movementLabels,
  periodText,
  resolveAccount,
  shortAccountLabel,
  splitLabel,
  statusText,
} from './accounts'

function line(patch: Partial<StatementLine> = {}): StatementLine {
  return {
    period_start: '2026-09-21',
    period_end: '2026-10-20',
    currency: 'DOP',
    charges_cents: 7231000,
    payments_cents: 6600000,
    balance_cents: 7526000,
    due_date: '2026-11-14',
    minimum_payment_cents: 376000,
    paid_full: null,
    left_over_cents: null,
    paid_late: false,
    next_interest_cents: 0,
    printout: false,
    ...patch,
  }
}

function account(patch: Partial<Account> = {}): Account {
  const latest = patch.latest ?? [line()]
  return {
    key: 'popular:credit_card',
    kind: 'credit_card',
    label: 'VISA ···1234',
    cut_day: 20,
    currencies: ['DOP'],
    latest,
    missing_statement: false,
    statements: latest,
    to_pay: null,
    ...patch,
  }
}

const SAVINGS = account({
  key: 'bhd:savings:1',
  kind: 'savings',
  label: 'Ahorro 1',
})
const VISA = account({ key: 'visa', label: 'Visa' })
const MC = account({ key: 'mc', label: 'Mastercard' })

describe('groupAccounts', () => {
  it('separa las tarjetas de crédito del resto, conservando el orden', () => {
    expect(groupAccounts([VISA, SAVINGS, MC])).toEqual({
      cards: [VISA, MC],
      others: [SAVINGS],
    })
  })
  it('deja grupos vacíos si no hay cuentas de ese tipo', () => {
    expect(groupAccounts([VISA])).toEqual({ cards: [VISA], others: [] })
  })
})

describe('resolveAccount', () => {
  it('usa la cuenta pedida si existe', () => {
    expect(resolveAccount([SAVINGS, VISA, MC], 'mc')).toBe(MC)
    expect(resolveAccount([VISA, SAVINGS], 'bhd:savings:1')).toBe(SAVINGS)
  })
  it('sin cuenta (o una desconocida) elige la primera tarjeta de crédito', () => {
    expect(resolveAccount([SAVINGS, VISA, MC], null)).toBe(VISA)
    expect(resolveAccount([SAVINGS, VISA, MC], 'no-existe')).toBe(VISA)
  })
  it('sin tarjetas elige la primera cuenta; sin cuentas, ninguna', () => {
    expect(resolveAccount([SAVINGS], null)).toBe(SAVINGS)
    expect(resolveAccount([], 'visa')).toBeNull()
  })
})

describe('movementLabels', () => {
  it('usa compras y pagos solo en tarjetas de crédito', () => {
    expect(movementLabels(VISA)).toEqual({
      charges: 'Compras',
      payments: 'Pagos',
    })
    expect(movementLabels(SAVINGS)).toEqual({
      charges: 'Débitos',
      payments: 'Créditos',
    })
  })
})

describe('splitLabel', () => {
  it('separa el nombre de los últimos dígitos', () => {
    expect(splitLabel('Visa ···1234')).toEqual({
      name: 'Visa',
      tail: '···1234',
    })
  })
  it('deja intacta una etiqueta sin dígitos', () => {
    expect(splitLabel('Ahorro BHD')).toEqual({ name: 'Ahorro BHD', tail: '' })
  })
})

describe('isCreditCard', () => {
  it('distingue tarjetas de crédito de ahorro y débito', () => {
    expect(isCreditCard(VISA)).toBe(true)
    expect(isCreditCard(SAVINGS)).toBe(false)
  })
})

describe('amountText', () => {
  it('formatea según la moneda de la línea', () => {
    expect(amountText(7526000, 'DOP')).toBe('RD$ 75,260')
    expect(amountText(41230, 'USD')).toBe('US$ 412.30')
  })
  it('muestra una raya cuando el estado no trae el monto', () => {
    expect(amountText(null, 'DOP')).toBe('—')
  })
})

describe('cutLine', () => {
  it('dice el día de corte y las monedas', () => {
    expect(cutLine(account())).toBe('Corta el día 20 · RD$')
    expect(cutLine(account({ cut_day: 5, currencies: ['DOP', 'USD'] }))).toBe(
      'Corta el día 5 · RD$ y US$',
    )
  })
  it('sin estados no inventa un día de corte', () => {
    expect(cutLine(account({ cut_day: null, currencies: [], latest: [] }))).toBe(
      'Sin estados todavía',
    )
  })
})

describe('periodText', () => {
  it('escribe el período del estado con días cortos', () => {
    expect(periodText(line())).toBe('21 sep – 20 oct')
  })
  it('sin inicio conocido (primer estado guardado) dice hasta cuándo', () => {
    expect(periodText(line({ period_start: null }))).toBe('hasta 20 oct')
  })
  it('una impresión dice que lo es y qué días cubre', () => {
    const printout = line({ printout: true, period_start: '2026-10-12', period_end: '2026-10-20' })
    expect(periodText(printout)).toBe('Impresión · 12 oct–20 oct')
  })
})

describe('cutText', () => {
  it('un estado muestra su día de corte', () => {
    expect(cutText(line())).toBe('20 oct')
  })
  it('una impresión del portal no es un corte', () => {
    expect(cutText(line({ printout: true }))).toBe('—')
  })
})

describe('missingMonth', () => {
  it('es el mes siguiente al último corte, con nombre completo', () => {
    expect(missingMonth(account({ missing_statement: true }))).toBe('noviembre')
  })
  it('pasa de diciembre a enero', () => {
    const december = account({
      missing_statement: true,
      latest: [line({ period_end: '2026-12-20' })],
    })
    expect(missingMonth(december)).toBe('enero')
  })
  it('no hay mes faltante si la cuenta está al día', () => {
    expect(missingMonth(account())).toBeNull()
  })
})

describe('statusText', () => {
  it('al día: el último corte', () => {
    expect(statusText(account())).toEqual({
      text: 'Al día · último estado del 20 oct',
      missing: false,
    })
  })
  it('con un estado faltante, avisa cuál', () => {
    expect(statusText(account({ missing_statement: true }))).toEqual({
      text: 'Último estado del 20 oct · falta el estado de noviembre',
      missing: true,
    })
  })
  it('sin estados', () => {
    expect(statusText(account({ latest: [], statements: [] }))).toEqual({
      text: 'Sin estados todavía',
      missing: false,
    })
  })
})

describe('dueNote', () => {
  it('cuenta los días que faltan', () => {
    expect(dueNote('2026-11-30', '2026-11-14')).toBe('en 16 días')
    expect(dueNote('2026-11-15', '2026-11-14')).toBe('mañana')
    expect(dueNote('2026-11-14', '2026-11-14')).toBe('hoy')
  })
  it('una fecha ya pasada solo dice de qué corte es', () => {
    expect(dueNote('2026-11-07', '2026-11-14', '2026-10-13')).toBe('del estado del 13 oct')
  })
})

describe('footnote', () => {
  it('explica el estado que falta', () => {
    expect(footnote(account({ missing_statement: true }))).toBe(
      'El estado de noviembre todavía no llega por correo; los meses que cubre se completan cuando llegue.',
    )
  })
  it('explica las dos monedas', () => {
    expect(footnote(account({ currencies: ['DOP', 'USD'] }))).toBe(
      'Esta cuenta tiene saldo en dos monedas; cada estado se verifica por separado en RD$ y en US$.',
    )
  })
  it('por defecto, la diferencia con el mes de calendario', () => {
    expect(footnote(account())).toBe(
      'Aquí se ve cada estado tal como lo emitió el banco; el Resumen suma por mes de calendario.',
    )
  })
})

describe('shortAccountLabel', () => {
  it('cuenta de ahorro: tipo y últimos 4 del número', () => {
    expect(shortAccountLabel('POPULAR Cuenta de ahorro 100200300')).toBe('Ahorro ···0300')
    expect(shortAccountLabel('BHD Cuenta de ahorro 1234567')).toBe('Ahorro ···4567')
  })

  it('cuenta corriente; el número puede traer guiones', () => {
    expect(shortAccountLabel('POPULAR Cuenta corriente 400500600')).toBe('Corriente ···0600')
    expect(shortAccountLabel('FICTICIO Cuenta corriente 777-0')).toBe('Corriente ···7770')
  })

  it('las tarjetas quedan como están', () => {
    expect(shortAccountLabel('MC BLACK ···0000')).toBe('MC BLACK ···0000')
    expect(shortAccountLabel('VISA DEMO ···4242')).toBe('VISA DEMO ···4242')
  })

  it('lo que no se reconoce (sin tipo o sin número) queda igual', () => {
    expect(shortAccountLabel('Ahorro BHD')).toBe('Ahorro BHD')
    expect(shortAccountLabel('BANCO Préstamo 123456')).toBe('BANCO Préstamo 123456')
    expect(shortAccountLabel('ficticio:checking:1')).toBe('ficticio:checking:1')
  })
})
