// Spanish UI text: Gmail connected read-only in hosted mode (Settings → «Gmail»). Keys start
// with "mailbox.".
import type { Catalog } from '../index'

export const mailbox = {
  'mailbox.title': 'Gmail',
  'mailbox.lead':
    'Conecta tu Gmail para ver el detalle de tus compras junto a cada cargo. Michelito solo lee, sin poder cambiar nada, los correos de los comercios que conoce (por ahora, los pedidos y envíos de Amazon); no abre ningún otro correo.',
  'mailbox.connect': 'Conectar Gmail',
  'mailbox.opening': 'Abriendo Google…',
  'mailbox.connected': 'Gmail conectado',
  'mailbox.lastRead': 'Última revisión: {date}',
  'mailbox.neverRead': 'Todavía no se ha revisado.',
  'mailbox.reading': 'Revisando tu correo…',
  'mailbox.receipts': {
    zero: 'Todavía no se ha leído ningún correo de comercios.',
    one: '{count} correo de comercios leído',
    other: '{count} correos de comercios leídos',
  },
  'mailbox.hourly': 'Se revisa solo cada hora.',
  'mailbox.syncNow': 'Revisar ahora',
  'mailbox.syncStarted': 'Revisando tu correo. Esto puede tardar un poco.',
  'mailbox.disconnect': 'Desconectar',
  'mailbox.disconnectLead':
    '¿Desconectar Gmail? Michelito deja de leer tu correo y se borra el permiso. Los recibos que ya se leyeron se quedan.',
  'mailbox.disconnectYes': 'Sí, desconectar',
  'mailbox.cancel': 'Cancelar',
  'mailbox.disconnected': 'Gmail quedó desconectado y se quitó el permiso.',
  'mailbox.disconnectedNotRevoked':
    'Gmail quedó desconectado aquí, pero Google no confirmó que quitó el permiso. Puedes quitarlo tú desde tu cuenta de Google.',
  'mailbox.reconnect.title': 'Vuelve a conectar Gmail',
  'mailbox.reconnect.lead':
    'Google ya no deja que Michelito lea tu correo: se quitó el permiso o venció. Vuelve a conectarlo para seguir viendo el detalle de tus compras.',
  'mailbox.reconnect.action': 'Volver a conectar',
  'mailbox.failed': 'La última revisión no se pudo completar. Se intentará de nuevo dentro de un rato.',
  'mailbox.outcome.connected': 'Gmail quedó conectado. Estamos leyendo los correos de tus compras del último año.',
  'mailbox.outcome.denied': 'No se conectó Gmail: no diste el permiso.',
  'mailbox.outcome.scope': 'No se conectó Gmail: hace falta marcar la casilla que permite leer tu correo.',
  'mailbox.outcome.failed': 'No se pudo conectar Gmail. Inténtalo de nuevo.',
  'mailbox.outcome.expired': 'La conexión tardó demasiado. Inténtalo de nuevo.',
  'mailbox.privacy': 'Cómo usamos tus datos',
  'mailbox.what': 'Gmail',
} as const satisfies Catalog
