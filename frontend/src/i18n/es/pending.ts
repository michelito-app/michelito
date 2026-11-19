// Spanish UI text: pending. Keys start with "pending.".
import type { Catalog } from '../index'

export const pending = {
  'pending.empty': 'Nadie te debe y no debes nada',
  'pending.age.today': 'hoy',
  'pending.age.daysAgo': { one: 'hace {count} día', other: 'hace {count} días' },
  'pending.meta.expenses': { one: '{count} gasto', other: '{count} gastos' },
  'pending.agreedRate': 'a {rate}',
  'pending.approx': '≈ {amount}',
  'pending.unconverted': '+ {amount} sin tasa',
  'pending.figure.owed': 'Te deben',
  'pending.figure.owe': 'Debes',
  'pending.figure.net': 'Neto',
  'pending.rateNote': 'Compartidos en US$ a la tasa de {month} ({value})',
  'pending.load': 'los pendientes',
  'pending.title': 'Pendientes',
  'pending.subtitle': 'Gastos compartidos y cambios de divisas sin cerrar, de todos los meses',
  'pending.totalsLabel': 'Totales',
  'pending.owedEmpty': 'Nadie te debe',
  'pending.oweEmpty': 'No debes nada',
  'pending.emptyHelp':
    'Aquí aparecen los gastos compartidos que te deben y los cambios de divisas sin completar.',
  'pending.loading': 'Cargando los pendientes',
} as const satisfies Catalog
