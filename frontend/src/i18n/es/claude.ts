// Spanish UI text: claude. Keys start with "claude.".
import type { Catalog } from '../index'

export const claude = {
  'claude.help': 'Pégalo en Claude (claude.ai, la app o Claude Code) y pega aquí la respuesta',
  'claude.manualNote':
    'No se pudo copiar solo: el texto quedó seleccionado abajo; cópialo con Ctrl+C (o mantén pulsado y «Copiar»).',
  'claude.allAccounts': 'todas',
  'claude.size': '{size} · {words} palabras',

  'claude.button': 'Copiar para Claude',
  'claude.buttonNamed': 'Copiar para Claude {label}',
  'claude.dialog.title': 'Copiar para Claude · {label}',
  'claude.dialog.instruction': 'Instrucción para Claude',
  'claude.dialog.reset': 'Restablecer',
  'claude.dialog.dossierFailed': 'No se pudo cargar el dossier: {message}',
  'claude.dialog.dossierSize': 'Dossier de {label}: {size}. Las cuentas son las de esta pantalla.',
  'claude.dialog.dossierLoading': 'Cargando el dossier…',
  'claude.dialog.instructionFailed': 'No se pudo cargar la instrucción: {message}',
  'claude.dialog.copied': 'Copiado',
  'claude.dialog.copy': 'Copiar',
  'claude.dialog.copiedNote': 'Instrucción y dossier copiados.',
  'claude.dialog.manualText': 'Texto para copiar a mano',
  'claude.dialog.helpLine': '{help}.',
  'claude.dialog.answer': 'Respuesta de Claude (Markdown)',
  'claude.dialog.over': 'Sobran {count} caracteres',
  'claude.dialog.left': 'Quedan {count} caracteres',
  'claude.dialog.saveFailed': 'No se pudo guardar: {message}',
  'claude.dialog.replaces': 'Reemplaza el análisis guardado (cuentas: {accounts})',
  'claude.dialog.confirm': '¿Reemplazar el análisis de {label}?',
  'claude.dialog.yesReplace': 'Sí, reemplazar',
  'claude.dialog.no': 'No',
  'claude.dialog.save': 'Guardar análisis',
} as const satisfies Catalog
