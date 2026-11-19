// Spanish UI text: shell. Keys start with "shell.".
import type { Catalog } from '../index'

export const shell = {
  'shell.notFound': 'Página no encontrada',
  'shell.publicDemo': 'Demo pública',
  'shell.localOnly': 'Solo en esta máquina',

  // Main menu.
  'shell.nav.label': 'Principal',
  'shell.nav.summary': 'Resumen',
  'shell.nav.budget': 'Presupuesto',
  'shell.nav.transactions': 'Transacciones',
  'shell.nav.pending': 'Pendientes',
  'shell.nav.shared': 'Compartidos',
  'shell.nav.investments': 'Inversiones',
  'shell.nav.recurring': 'Recurrentes',
  'shell.nav.reports': 'Reportes',
  'shell.nav.accounts': 'Cuentas',
  'shell.nav.categories': 'Categorías',
  'shell.nav.log': 'Bitácora',
  'shell.nav.import': 'Importar',

  // Account picker.
  'shell.accounts.pick': 'Elegir cuentas ({label})',
  'shell.accounts.title': 'Cuentas',
  'shell.accounts.shortcuts': 'Atajos',
  'shell.accounts.all': 'Todas',
  'shell.accounts.cardsOnly': 'Solo tarjetas',
  'shell.accounts.banksOnly': 'Solo cuentas bancarias',
  'shell.accounts.buttonAll': 'Cuentas: Todas',
  // `count` of `total` accounts selected (no plural form: "Cuentas: 1 de 3").
  'shell.accounts.buttonSome': 'Cuentas: {count} de {total}',
  'shell.accounts.scopeSome': '{count} de {total} cuentas',
  'shell.accounts.lastHint': 'Siempre queda al menos una cuenta',
} as const satisfies Catalog
