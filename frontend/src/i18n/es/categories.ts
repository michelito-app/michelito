// Spanish UI text: categories. Keys start with "categories.".
import type { Catalog } from '../index'

export const categories = {
  // System category names as the server seeds them (the user may rename them; the board reads
  // today's name by `builtin_key`, and the server also understands these).
  'categories.builtin.thirdParty': 'Transferencias a terceros',
  'categories.builtin.cash': 'Efectivo',
  // A former name of the cash category: old links may still carry it.
  'categories.legacy.cashAndTransfers': 'Efectivo y transferencias',

  'categories.group.expense': 'Gastos',
  'categories.group.income': 'Ingresos',
  'categories.group.transfer': 'Transferencias',
  'categories.kind.expense': 'Gasto',
  'categories.kind.income': 'Ingreso',
  'categories.kind.transfer': 'Transferencia',

  'categories.countYear': {
    zero: 'Sin transacciones este año',
    one: '{count} transacción este año',
    other: '{count} transacciones este año',
  },
  'categories.preview.none': 'Esto no mueve ninguna transacción',
  'categories.preview.moves': {
    one: 'Esto moverá {count} transacción ({money})',
    other: 'Esto moverá {count} transacciones ({money})',
  },
  'categories.preview.withUnconverted': '{dop} y {usd} sin tasa',
  'categories.conflicts': {
    one: '{count} transacción coincide también con palabras de otra categoría: gana la palabra más larga',
    other:
      '{count} transacciones coinciden también con palabras de otra categoría: gana la palabra más larga',
  },

  'categories.title': 'Categorías',
  'categories.subtitle': 'Las palabras clave mueven transacciones pasadas y futuras.',
  'categories.loadWhat': 'las categorías',
  'categories.loading': 'Cargando las categorías',
  'categories.new': 'Nueva categoría',
  'categories.autoColorTitle': 'Color automático: el de su puesto en el Resumen',
  'categories.autoColor': 'Color automático',
  'categories.hidden': 'Oculta',
  'categories.system': ' · del sistema',
  'categories.keywordsLine': 'Palabras: {words}',
  'categories.edit': 'Editar',
  'categories.editNamed': 'Editar {name}',
  'categories.keywords': 'Palabras clave',
  'categories.keywordsOf': 'Palabras clave de {name}',
  'categories.show': 'Mostrar',
  'categories.hide': 'Ocultar',
  'categories.showNamed': 'Mostrar {name}',
  'categories.hideNamed': 'Ocultar {name}',
  'categories.delete': 'Borrar',
  'categories.deleteNamed': 'Borrar {name}',
  'categories.deleting': 'Borrando…',
  'categories.saveFailed': 'No se pudo guardar: {message}',
  'categories.deleteFailed': 'No se pudo borrar: {message}',
  'categories.createFailed': 'No se pudo crear: {message}',
  'categories.save': 'Guardar',
  'categories.saving': 'Guardando…',
  'categories.cancel': 'Cancelar',
  'categories.create': 'Crear',

  'categories.form.name': 'Nombre',
  'categories.form.kind': 'Tipo',
  'categories.form.color': 'Color',
  'categories.form.automatic': 'Automático',
  'categories.form.colorNamed': 'Color {color}',
  'categories.form.auto': 'Auto',

  'categories.keywordsDialog.label': 'Palabras o frases, separadas por coma',
  'categories.keywordsDialog.placeholder': 'TALLER, LAVADO DE AUTO',
  'categories.keywordsDialog.help':
    'Cuentan como palabra entera, sin importar mayúsculas ni acentos. Una corrección a mano y las transferencias detectadas les ganan.',
  'categories.deleteDialog.moveTo': 'Sus transacciones, reglas y palabras clave pasan a',
} as const satisfies Catalog
