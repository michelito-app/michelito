// Spanish UI text: demo. Keys start with "demo.".
import type { Catalog } from '../index'

export const demo = {
  'demo.titleSuffix': '{name} · demo',
  'demo.opinion.empty': 'Escribe tu opinión.',
  'demo.opinion.tooLong': 'Máximo {max} letras.',
  'demo.opinion.badEmail': 'El correo no parece válido.',

  'demo.banner.label': 'Aviso de la demo',
  'demo.banner.notice': 'Demo con datos inventados · tus cambios se borran en 24 h',
  'demo.banner.openSource': 'Código abierto',
  'demo.banner.restart': 'Empezar de nuevo',
  'demo.banner.feedback': 'Opinar',

  'demo.feedback.thanks': '¡Gracias!',
  'demo.feedback.received': 'Tu opinión llegó. Cada una se lee.',
  'demo.feedback.close': 'Cerrar',
  'demo.feedback.title': 'Opinar',
  'demo.feedback.question': '¿Qué te pareció? ¿Qué falta o sobra?',
  'demo.feedback.counter': '{length} / {max}',
  'demo.feedback.email': 'Correo (opcional, solo si quieres respuesta)',
  'demo.feedback.context':
    'Se envía también la pantalla en que estás, el ancho de la ventana, la versión y la fecha. Nada más.',
  'demo.feedback.sending': 'Enviando…',
  'demo.feedback.send': 'Enviar opinión',

  'demo.gate.loading': 'Cargando…',
  'demo.gate.failed': 'No se pudo abrir la app.',
  'demo.gate.retry': 'Reintentar',

  'demo.restart.title': 'Empezar de nuevo',
  'demo.restart.body': 'Se borran tus cambios en la demo y vuelves a los datos inventados del principio.',
  'demo.restart.cancel': 'Cancelar',
  'demo.restart.starting': 'Empezando…',
  'demo.restart.confirm': 'Borrar mis cambios',
} as const satisfies Catalog
