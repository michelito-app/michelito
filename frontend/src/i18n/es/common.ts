// Spanish UI text: common. Keys start with "common.".
import type { Catalog } from '../index'

export const common = {
  'common.cancel': 'Cancelar',
  'common.save': 'Guardar',
  'common.close': 'Cerrar',
  'common.retry': 'Reintentar',
  'common.loadError': 'No se pudo cargar {what}.',
  'common.allYourAccounts': 'todas tus cuentas',
  // aria-label of the Transactions list (also used to find its checkboxes).
  'common.transactionListLabel': 'Lista de transacciones',
  'common.transactions': {
    one: '{count} transacción',
    other: '{count} transacciones',
  },

  // Multiple selection in Transactions.
  'common.selection.count': { one: '{count} seleccionada', other: '{count} seleccionadas' },
  'common.selection.inOut': 'entran {incoming} · salen {outgoing}',
  'common.selection.unrated': {
    one: '{count} sin tasa (no suma)',
    other: '{count} sin tasa (no suman)',
  },
  'common.selection.mixedNotice':
    'Hay débitos y créditos: las categorías de ingreso no se ofrecen (un débito no es ingreso).',
  'common.selection.linked': {
    one: '{count} está en un vínculo que fija su categoría: no se cambiará.',
    other: '{count} están en un vínculo que fija su categoría: no se cambiarán.',
  },
  'common.selection.applied': {
    zero: 'Ninguna cambió',
    one: '{count} pasó a {category}',
    other: '{count} pasaron a {category}',
  },
  'common.selection.skipped.cashBox': {
    one: '{count} no se cambió: es de la caja fuerte (una entrada va a un ingreso; una salida, a un gasto)',
    other:
      '{count} no se cambiaron: son de la caja fuerte (una entrada va a un ingreso; una salida, a un gasto)',
  },
  'common.selection.skipped.linked': {
    one: '{count} no se cambió: está en un vínculo',
    other: '{count} no se cambiaron: están en un vínculo',
  },
  'common.selection.skipped.direction': {
    one: '{count} no se cambió: es un débito (no puede ser ingreso)',
    other: '{count} no se cambiaron: son débitos (no pueden ser ingreso)',
  },
  'common.selection.skipped.unchanged': {
    one: '{count} no se cambió: ya estaba en esa categoría',
    other: '{count} no se cambiaron: ya estaban en esa categoría',
  },
  'common.selection.skipped.unknown': {
    one: '{count} no se cambió: ya no existe',
    other: '{count} no se cambiaron: ya no existen',
  },
} as const satisfies Catalog
