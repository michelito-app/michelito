// Spanish UI text: import. Keys start with "import.".
import type { Catalog } from '../index'

export const importing = {
  'import.title': 'Importar',
  'import.upload.label': 'Subir un estado',
  'import.upload.file': 'Estado de cuenta en PDF',
  'import.upload.demoHint':
    'En la demo no se suben archivos: tus estados reales nunca salen de tu máquina. Prueba con uno de ejemplo.',
  'import.upload.localHint':
    'Por ahora los estados se importan desde la terminal: michelito import ARCHIVO.pdf',
  'import.sample.title': 'Estado de ejemplo',
  'import.sample.body':
    'Importa el siguiente corte de la tarjeta inventada, por el mismo camino que un PDF: se interpreta, se valida contra sus totales y solo entra si cuadra.',
  'import.sample.importing': 'Importando…',
  'import.sample.try': 'Probar con un estado de ejemplo',
  'import.outcome.balanced': 'Cuadra: {count} transacciones nuevas',
  'import.outcome.rejected': 'No entró ({status}): {detail}',
  'import.outcome.noDetail': 'sin detalle',
  'import.outcome.period': '{account} · del {start} al {end}',
  'import.outcome.review': 'Ver «Para revisar»',
  'import.outcome.transactions': 'Ver las transacciones',
} as const satisfies Catalog
