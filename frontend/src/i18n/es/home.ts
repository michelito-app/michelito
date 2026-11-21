// Spanish UI text: the Summary's cards (home). Keys start with "home.".
import type { Catalog } from '../index'

export const home = {
  'home.cards.label': 'Resumen del mes',
  // What did not load (common.loadError: «No se pudo cargar {what}.»)
  'home.what.pace': 'la curva del mes',
  'home.what.budget': 'el presupuesto',
  'home.what.review': 'lo que hay por revisar',
  'home.what.recurring': 'los recurrentes',
  'home.what.latest': 'los movimientos',
  'home.what.shared': 'los compartidos',
  'home.what.pending': 'los pendientes',
  // Coverage pill and sheet
  'home.coverage.inProgress': 'En curso · {closed} de {total} cuentas cerradas',
  'home.coverage.allClosed': { one: '{count} cuenta al día', other: '{count} cuentas al día' },
  'home.coverage.sheetTitle': 'Datos por cuenta',
  'home.coverage.sheetNote':
    'Lo que aún no tiene estado viene de las alertas del banco y ya está contado.',
  // Month spending
  'home.spending.title': 'Gasto del mes',
  'home.spending.regular': 'Sin gastos únicos: {amount}',
  'home.spending.less': '{percent} % menos que el mes pasado a esta fecha',
  'home.spending.more': '{percent} % más que el mes pasado a esta fecha',
  'home.spending.same': 'Igual que el mes pasado a esta fecha',
  'home.spending.lessWhole': '{percent} % menos que el mes pasado',
  'home.spending.moreWhole': '{percent} % más que el mes pasado',
  'home.spending.sameWhole': 'Igual que el mes pasado',
  'home.spending.empty': 'Aún sin gastos este mes · el mes pasado a esta fecha: {amount}',
  'home.spending.emptyNoPrevious': 'Aún sin gastos este mes',
  'home.spending.chart':
    'Gasto acumulado sin gastos únicos: {current} hasta el día {day}; el mes pasado a esta fecha, {previous}',
  'home.spending.chartWhole':
    'Gasto acumulado sin gastos únicos: {current} en el mes; el mes pasado entero, {previous}',
  'home.spending.oneOff': 'Gasto único: {merchant}, {amount}, {day}',
  'home.spending.thisMonth': 'Este mes',
  'home.spending.lastMonth': 'Mes pasado',
  // Flow
  'home.flow.title': 'Flujo',
  'home.flow.in': 'Entró',
  'home.flow.out': 'Salió',
  'home.flow.kept': 'Te quedó',
  'home.flow.overspent': 'Salió más de lo que entró',
  // Budget
  'home.budget.title': 'Presupuesto',
  'home.budget.line': '{spent} de {cap}',
  'home.budget.over': 'Pasado por {amount}',
  'home.budget.noCaps': 'Ninguna categoría con tope todavía',
  // To review
  'home.review.title': 'Para revisar',
  'home.review.count': { one: '{count} por revisar', other: '{count} por revisar' },
  'home.review.none': 'Nada por revisar este mes',
  'home.review.more': { one: 'y {count} más', other: 'y {count} más' },
  // Upcoming
  'home.upcoming.title': 'Próximos',
  'home.upcoming.none': 'Nada vence en los próximos 7 días',
  'home.upcoming.alerts': { one: '{count} aviso en Recurrentes', other: '{count} avisos en Recurrentes' },
  'home.upcoming.today': 'hoy',
  'home.upcoming.tomorrow': 'mañana',
  'home.upcoming.inDays': { one: 'en {count} día', other: 'en {count} días' },
  // Latest transactions
  'home.latest.title': 'Últimos movimientos',
  'home.latest.none': 'Sin movimientos este mes',
  // Shared
  'home.shared.title': 'Compartidos',
  'home.shared.owedToMe': 'Te deben',
  'home.shared.iOwe': 'Debes',
  'home.shared.settled': 'Todo saldado',
  'home.shared.pending': 'Pendientes con cambios incluidos: te deben {owed} · debes {owe}',
  // Categories
  'home.categories.title': 'Categorías',
  'home.categories.others': 'Otras',
  'home.categories.none': 'Sin gastos este mes',
  'home.categories.percent': '{percent} %',
  'home.categories.slice': '{category}: {amount}',
  // Invitations
  'home.invite.budget.text': 'Pon un tope a tus 3 categorías más grandes',
  'home.invite.budget.action': 'Proponer presupuesto',
  'home.invite.recurring.text': 'Marca tus pagos fijos para verlos venir',
  'home.invite.recurring.action': 'Ver recurrentes',
  'home.invite.shared.text': '¿Divides gastos con alguien?',
  'home.invite.shared.action': 'Crear grupo',
  'home.invite.dismiss': 'Descartar: {text}',
  // The review list (the "To review" card's destination)
  'home.reviewPage.title': 'Para revisar',
} as const satisfies Catalog
