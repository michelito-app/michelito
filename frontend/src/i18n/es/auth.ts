// Spanish UI text: hosted mode (signed-out page, sign-in, devices, step-up). Keys start with
// "auth.".
import type { Catalog } from '../index'

export const auth = {
  'auth.landing.title': 'Tus estados de cuenta, en claro',
  'auth.landing.lead':
    'Michelito lee los estados de tus bancos, comprueba que cuadran y te muestra a dónde se va el dinero.',
  'auth.landing.demo': 'Ver datos de ejemplo',
  'auth.landing.enter': 'Entrar',
  'auth.landing.privacy': 'Privacidad',
  'auth.landing.invite': 'Por ahora solo se entra con invitación.',

  'auth.signIn.title': 'Entrar',
  'auth.signIn.email': 'Tu correo',
  'auth.signIn.sendCode': 'Enviarme un código',
  'auth.signIn.sending': 'Enviando…',
  'auth.signIn.sent':
    'Si tienes cuenta o invitación, te llegó un código de 6 cifras a {email}. Vence en 10 minutos.',
  'auth.signIn.inviteOnly':
    'Michelito es solo con invitación por ahora: si no te invitaron, no llegará ningún correo.',
  'auth.signIn.code': 'Código de 6 cifras',
  'auth.signIn.verify': 'Entrar',
  'auth.signIn.verifying': 'Comprobando…',
  'auth.signIn.resend': 'Reenviar el código',
  'auth.signIn.resendIn': 'Reenviar en {seconds} s',
  'auth.signIn.otherEmail': 'Usar otro correo',
  'auth.signIn.back': 'Atrás',
  'auth.signIn.badEmail': 'El correo no parece válido.',
  'auth.signIn.badCode': 'El código tiene 6 cifras.',
  'auth.signIn.linkFailed': 'El enlace ya no sirve: pide un código nuevo.',

  'auth.link.confirm': '¿Entrar como {email}?',
  'auth.link.lead': 'Abriste el enlace de tu correo. Si no lo pediste tú, no entres.',
  'auth.link.enter': 'Sí, entrar',
  'auth.link.cancel': 'No, volver',

  'auth.settings.title': 'Ajustes',
  'auth.settings.account': 'Cuenta',
  'auth.settings.signedInAs': 'Entraste como {email}',
  'auth.devices.title': 'Dispositivos',
  'auth.devices.what': 'tus dispositivos',
  'auth.devices.lead': 'Dónde tienes la sesión abierta. No guardamos la dirección IP.',
  'auth.devices.thisOne': 'Este dispositivo',
  'auth.devices.unknownBrowser': 'Navegador desconocido',
  'auth.devices.unknownOs': 'sistema desconocido',
  'auth.devices.label': '{browser} en {os}',
  'auth.devices.lastSeen': 'Última actividad: {date}',
  'auth.devices.signOut': 'Cerrar sesión en este dispositivo',
  'auth.devices.signOutEverywhere': 'Cerrar sesión en todos',
  'auth.devices.everywhereHint':
    'Cierra la sesión en todos tus dispositivos, este incluido. Te pedimos un código nuevo primero.',

  'auth.delete.title': 'Borrar cuenta',
  'auth.delete.lead': 'Borra tu cuenta y todos tus datos de Michelito. No se puede deshacer.',
  'auth.delete.open': 'Borrar mi cuenta…',
  'auth.delete.dialogTitle': '¿Borrar tu cuenta?',
  'auth.delete.loses': 'Si la borras:',
  'auth.delete.lossData':
    'Se borran todos tus datos: estados de cuenta, movimientos, presupuestos y ajustes.',
  'auth.delete.lossNow': 'Quedan ilegibles al instante: la clave que los cifra se destruye ahora mismo.',
  'auth.delete.lossBackups': 'Desaparecen de las copias de seguridad en 30 días como máximo.',
  'auth.delete.lossGmail': 'Se revoca el acceso de Michelito a tu Gmail.',
  'auth.delete.lossSessions': 'Se cierra la sesión en todos tus dispositivos.',
  'auth.delete.typeEmail': 'Para confirmar, escribe tu correo: {email}',
  'auth.delete.confirm': 'Borrar mi cuenta para siempre',
  'auth.delete.deleting': 'Borrando…',
  'auth.delete.cancel': 'Cancelar',
  'auth.delete.done': 'Tu cuenta y tus datos se borraron. Gracias por usar Michelito.',

  'auth.stepUp.title': 'Confirma que eres tú',
  'auth.stepUp.lead': 'Te enviamos un código nuevo a {email}. Escríbelo para seguir.',
  'auth.stepUp.send': 'Enviar el código',
  'auth.stepUp.confirm': 'Confirmar',
  'auth.stepUp.cancel': 'Cancelar',

  'auth.shell.settings': 'Ajustes',
  'auth.shell.signedIn': 'Sesión iniciada',
} as const satisfies Catalog
