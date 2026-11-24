// Spanish UI text: the AI connector (consent screen, Settings) and its proposals in Review.
// Keys start with "connector.".
import type { Catalog } from '../index'

export const connector = {
  'connector.title': 'Claude y otras IA',
  'connector.lead':
    'Conecta Michelito a Claude para preguntarle por tus finanzas y pedirle que revise tus categorías. Claude solo puede leer y proponer: los cambios llegan a Revisión y tú decides.',
  'connector.what': 'las conexiones',
  'connector.urlLabel': 'Dirección del conector',
  'connector.copy': 'Copiar',
  'connector.copied': 'Copiado',
  'connector.step1': 'En Claude, abre Ajustes → Conectores y elige «Añadir conector personalizado».',
  'connector.step2': 'Pega la dirección de arriba, ponle un nombre (por ejemplo, Michelito) y pulsa Conectar.',
  'connector.step3': 'Claude te trae aquí: revisa lo que pide y pulsa Permitir.',
  'connector.none': 'Ninguna IA conectada.',
  'connector.connectedOn': 'Conectada el {created} · último uso: {used}',
  'connector.revoke': 'Desconectar',
  'connector.revokeLead': 'Esta IA dejará de poder leer tu cuenta de inmediato. Lo que ya propuso sigue en Revisión.',
  'connector.revokeYes': 'Sí, desconectar',
  'connector.cancel': 'Cancelar',
  'connector.revoked': 'Listo: esa IA ya no puede leer tu cuenta.',
  'connector.sees':
    'Lo que lee llega a la IA que conectes (Anthropic, si es Claude): montos, comercios, categorías, saldos y tus grupos compartidos con los movimientos de sus miembros. Nunca ve números completos de cuenta o tarjeta ni correos.',

  'connector.consent.title': '{client} quiere conectarse a tu Michelito',
  'connector.consent.what': 'la solicitud de conexión',
  'connector.consent.back': 'Al terminar vuelves a {host}.',
  'connector.consent.can': 'Podrá:',
  'connector.consent.read':
    'Leer tus cuentas, movimientos, presupuesto, préstamos, cuotas, inversiones, efectivo y grupos compartidos (también los movimientos de los demás miembros).',
  'connector.consent.propose': 'Proponerte cambios de categoría, que tú apruebas o descartas en Revisión.',
  'connector.consent.cannot': 'No podrá cambiar nada por su cuenta ni ver números completos de cuenta, de tarjeta ni correos.',
  'connector.consent.lasts': 'La conexión dura hasta que la quites en Ajustes, o 90 días sin uso.',
  'connector.consent.account': 'Se conectará la cuenta {email}.',
  'connector.consent.onlyIf':
    'Permite solo si tú acabas de pedir esta conexión desde Claude. Si te llegó este enlace de otra persona, cancela.',
  'connector.consent.allow': 'Permitir',
  'connector.consent.deny': 'Cancelar',
  'connector.consent.leaving': 'Volviendo a {host}…',
  'connector.consent.gone': 'Esta solicitud ya venció o se usó. Vuelve a conectar desde Claude.',

  'connector.proposals.title': 'Propuestas de la IA',
  'connector.proposals.what': 'las propuestas',
  'connector.proposals.from': 'De {source} · {count}',
  'connector.proposals.changes': { one: '{count} cambio', other: '{count} cambios' },
  'connector.proposals.dataNote': 'Explicación escrita por {source}.',
  'connector.proposals.onlyThis': 'Solo esta',
  'connector.proposals.rule': 'Regla del comercio',
  'connector.proposals.move': '{from} → {to}',
  'connector.proposals.missingCategory': 'categoría borrada',
  'connector.proposals.apply': { one: 'Aplicar {count} cambio', other: 'Aplicar {count} cambios' },
  'connector.proposals.applyNone': 'Elige algún cambio',
  'connector.proposals.dismiss': 'Descartar',
  'connector.proposals.dismissed': 'Descartada',
  'connector.proposals.outcome.applied': { one: '{count} aplicado', other: '{count} aplicados' },
  'connector.proposals.outcome.skipped': { one: '{count} omitido', other: '{count} omitidos' },
  'connector.proposals.outcome.failed': { one: '{count} falló', other: '{count} fallaron' },
  'connector.proposals.undoHint': 'Puedes deshacer cada cambio en la Bitácora.',
  'connector.proposals.selectAll': 'Todos',
  'connector.proposals.selectNone': 'Ninguno',
} as const satisfies Catalog
