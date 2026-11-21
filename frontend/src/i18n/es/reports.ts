// Spanish UI text: reports. Keys start with "reports.".
import type { Catalog } from '../index'

export const reports = {
  'reports.month.title': 'Detalle del mes',
  // lib/insights.ts
  'reports.insight.saved': 'Guardado el {day} de {year}',
  'reports.insight.edited': 'Editado el {day} de {year}',
  'reports.insight.stale': 'Los datos cambiaron desde este análisis',
  // lib/reports.ts
  'reports.cell.notCompared': 'Este mes no se compara',
  'reports.cell.habitual': 'Lo habitual: {habitual}',
  'reports.cell.higher': 'Lo habitual: {habitual} · más alto que lo habitual',
  'reports.cell.lower': 'Lo habitual: {habitual} · más bajo que lo habitual',
  // pages/ReportsPage.tsx
  'reports.page.title': 'Reportes',
  'reports.page.subtitle': 'Mes a mes en {scope} · montos en RD$',
  'reports.page.comparison': 'la comparación',
  'reports.page.empty': 'Todavía no hay meses para comparar.',
  // components/reports/CompareTable.tsx
  'reports.compare.title': 'Comparar meses',
  'reports.compare.from': 'Desde',
  'reports.compare.to': 'Hasta',
  'reports.compare.hint':
    'RD$ por mes. Destacado: se aparta de lo habitual de su fila más de 30 % y de RD$ 1,000 (terracota si subió, borde verde si bajó). Los meses en curso no se comparan.',
  'reports.compare.tableLabel': 'Tabla de meses (se desplaza a lo ancho)',
  'reports.compare.row': 'Fila',
  'reports.compare.incomeByCategory': 'Ingresos por categoría',
  'reports.compare.cellLabel': '{row}, {month}: RD$ {amount}. {title}',
  // components/reports/InsightsSection.tsx
  'reports.insights.title': 'Análisis',
  'reports.insights.hint':
    'Pídele a Claude Code «analiza febrero»: corre {analysis}, escribe el análisis y lo guarda con {save}. O usa «Copiar para Claude» y pega aquí la respuesta.',
  'reports.insights.loadWhat': 'los análisis',
  'reports.insights.savedLabel': 'Análisis guardados',
  'reports.insights.accounts': { one: ' · {count} cuenta', other: ' · {count} cuentas' },
  'reports.insights.editLabel': 'Análisis de {label} (Markdown)',
  'reports.insights.over': 'Sobran {count} caracteres',
  'reports.insights.left': 'Quedan {count} caracteres',
  'reports.insights.editAction': 'Editar el análisis de {label}',
  'reports.insights.edit': 'Editar',
  'reports.insights.confirmDelete': '¿Borrar el análisis?',
  'reports.insights.yesDelete': 'Sí, borrar',
  'reports.insights.deleteAction': 'Borrar el análisis de {label}',
  'reports.insights.delete': 'Borrar',
  'reports.insights.missingTitle': 'Meses sin análisis',
  'reports.insights.copyCommandLabel': 'Copiar comando para analizar {label}',
  'reports.insights.copyCommand': 'Copiar comando para analizar',
  // components/reports/ReviewHistory.tsx
  'reports.history.title': 'Para revisar: historial',
  'reports.history.subtitle': 'Últimos 12 meses · {pending} pendientes de {total}',
  'reports.history.filterLabel': 'Filtrar por tipo',
  'reports.history.all': 'Todos',
  'reports.history.loadWhat': 'el historial',
  'reports.history.empty': 'Nada para revisar en estos meses.',
} as const satisfies Catalog
