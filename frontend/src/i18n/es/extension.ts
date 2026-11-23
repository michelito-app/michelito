// Spanish UI text: the Amazon browser extension in Settings. Keys start with "extension.".
import type { Catalog } from '../index'

export const extension = {
  'extension.title': 'Extensión de Amazon',
  'extension.lead':
    'Trae los nombres de los artículos de tus pedidos de Amazon a los recibos que ya llegan por Gmail. Funciona en Chrome de computadora, con tu sesión de Amazon.',
  'extension.what': 'la extensión',
  'extension.notLinked': 'Ningún Chrome vinculado.',
  'extension.linkedTitle': 'Vinculada',
  'extension.linkedOn': 'Vinculada el {date}.',
  'extension.neverUsed': 'Aún no ha enviado nombres.',
  'extension.lastUsed': 'Último envío: {date} · {orders}.',
  'extension.orders': {
    one: '{count} pedido con nombres',
    other: '{count} pedidos con nombres',
  },
  'extension.makeCode': 'Generar código',
  'extension.makeAnother': 'Generar otro código',
  'extension.codeLabel': 'Código para pegar en la extensión',
  'extension.expires': 'Vence a las {time}.',
  'extension.codeHint': 'Sirve una sola vez. Al usarlo, el Chrome que estaba vinculado deja de estarlo.',
  'extension.copy': 'Copiar',
  'extension.copied': 'Copiado',
  'extension.revoke': 'Revocar',
  'extension.revokeLead':
    'La extensión dejará de poder enviar nombres de inmediato. Los nombres que ya envió se quedan en tus recibos.',
  'extension.revokeYes': 'Sí, revocar',
  'extension.cancel': 'Cancelar',
  'extension.revoked': 'Listo: la extensión ya no puede enviar nombres.',
  'extension.download': 'Descargar la extensión (.zip)',
  'extension.stepsTitle': 'Cómo instalarla',
  'extension.step1': 'Descarga el .zip y descomprímelo en una carpeta que no vayas a borrar.',
  'extension.step2': 'En Chrome, abre chrome://extensions y activa «Modo de desarrollador» (arriba a la derecha).',
  'extension.step3': 'Pulsa «Cargar descomprimida» y elige esa carpeta.',
  'extension.step4': 'Abre la extensión (el ícono de la M verde), pega el código y pulsa «Vincular».',
  'extension.step5': 'Con tu sesión de Amazon abierta en ese Chrome, pulsa «Últimos 12 meses».',
  'extension.reads':
    'Solo lee tus páginas de pedidos de Amazon y solo envía el número de cada pedido y los nombres de sus artículos (con cantidad y precio si la página los muestra). Nunca direcciones ni datos de pago.',
  'extension.privacy': 'Qué lee y qué guarda',
} as const satisfies Catalog
