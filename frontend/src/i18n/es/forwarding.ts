// Spanish UI text: email forwarding in hosted mode (Settings → «Automatiza los próximos», the
// Gmail guide and the «Tus estados» card). Keys start with "forwarding.".
import type { Catalog } from '../index'

export const forwarding = {
  'forwarding.title': 'Automatiza los próximos',
  'forwarding.lead':
    'Reenvía a esta dirección los correos de tus bancos: los estados y los avisos de consumo llegan solos a Michelito.',
  'forwarding.address.label': 'Tu dirección de reenvío',
  'forwarding.address.none': 'Todavía no tienes una dirección de reenvío.',
  'forwarding.address.create': 'Crear mi dirección',
  'forwarding.address.copy': 'Copiar',
  'forwarding.address.copied': 'Copiada',
  'forwarding.address.rotate': 'Cambiar la dirección',
  'forwarding.address.rotateHint':
    'Si alguien más la conoce, cámbiala: la vieja deja de funcionar en el acto y tendrás que actualizar el reenvío en tu correo.',
  'forwarding.address.private':
    'Es privada: quien la conozca puede enviarte correos. Lo que no venga de tu banco queda en espera, sin abrir.',
  'forwarding.guide.link': 'Cómo crear el reenvío en Gmail',
  'forwarding.guide.title': 'Reenvío desde Gmail',
  'forwarding.guide.back': 'Volver a Ajustes',
  'forwarding.guide.step1': 'En Gmail en una computadora, abre Configuración → Ver todos los ajustes → Reenvío y correo POP/IMAP.',
  'forwarding.guide.step2': 'Toca «Añadir una dirección de reenvío» y pega tu dirección de Michelito.',
  'forwarding.guide.step3':
    'Gmail envía un código de confirmación a esa dirección: aparece aquí, en Ajustes. Cópialo en Gmail o abre su enlace. Michelito nunca lo confirma por ti.',
  'forwarding.guide.step4':
    'No actives el reenvío de todo tu correo. En su lugar, crea un filtro: Configuración → Filtros → Crear un filtro.',
  'forwarding.guide.step5': 'En «De», pega los remitentes de tus bancos:',
  'forwarding.guide.step6': 'Toca «Crear filtro», marca «Reenviarlo a» con tu dirección de Michelito y guarda.',
  'forwarding.guide.done':
    'Listo: los próximos estados y avisos llegarán solos. Los que pidan clave te esperan aquí hasta que la escribas.',
  'forwarding.guide.copySenders': 'Copiar remitentes',
  'forwarding.guide.receiptsTitle': 'Opcional: el detalle de tus compras',
  'forwarding.guide.receipts':
    'Para ver en cada cargo de Amazon el pedido al que corresponde, crea otro filtro igual con estos remitentes. Michelito lee de esos correos solo el número de pedido, el monto y el resumen; nunca crea transacciones con ellos.',

  'forwarding.confirmation.title': 'Confirma el reenvío en Gmail',
  'forwarding.confirmation.lead':
    'Gmail pidió confirmar que quieres reenviar a Michelito. Escribe este código en Gmail o abre el enlace. Si no lo pediste tú, ignóralo.',
  'forwarding.confirmation.code': 'Código: {code}',
  'forwarding.confirmation.requester': 'Lo pidió {email}. Si no es tu Gmail, no lo confirmes.',
  'forwarding.confirmation.link': 'Abrir el enlace de Gmail',
  'forwarding.confirmation.dismiss': 'Ya lo confirmé',

  'forwarding.waiting.title': 'Estados en espera',
  'forwarding.waiting.lead':
    'Llegaron protegidos con clave. Se guardan cifrados hasta que escribas la clave; luego se leen y se borran.',
  'forwarding.waiting.item': '{bank} · llegó el {date}',
  'forwarding.waiting.reading': 'Leyendo…',
  'forwarding.waiting.missing': 'Falta la clave',
  'forwarding.waiting.wrong': 'La clave guardada no lo abrió',
  'forwarding.waiting.bank': 'Banco',
  'forwarding.waiting.password': 'Clave de los PDFs',
  'forwarding.waiting.submit': 'Abrir',
  'forwarding.waiting.trying': 'Probando…',
  'forwarding.waiting.opened': {
    one: 'Se abrió {count} estado.',
    other: 'Se abrieron {count} estados.',
  },
  'forwarding.waiting.notOpened': 'Esa clave no abrió ningún estado de {bank}.',

  'forwarding.quarantine.title': 'Correos sin verificar',
  'forwarding.quarantine.lead':
    'No pudimos comprobar que vengan de tu banco. No abrimos nada hasta que lo apruebes.',
  'forwarding.quarantine.item': 'De {domain} · {date}',
  'forwarding.quarantine.attachments': {
    zero: 'sin adjuntos',
    one: '{count} adjunto',
    other: '{count} adjuntos',
  },
  'forwarding.quarantine.unknown_sender': 'Remitente desconocido',
  'forwarding.quarantine.unauthenticated': 'La firma del banco no se pudo verificar',
  'forwarding.quarantine.unknown_card': 'Una tarjeta que todavía no tienes en Michelito',
  'forwarding.quarantine.approve': 'Aprobar',
  'forwarding.quarantine.discard': 'Descartar',
  'forwarding.quarantine.confirm': 'Sí, aprobar',
  'forwarding.quarantine.cancel': 'Cancelar',
  'forwarding.quarantine.confirmLead':
    'Al aprobarlo, Michelito lo abre y guarda lo que traiga como si viniera de tu banco. Solo hazlo si lo reconoces.',
  'forwarding.quarantine.impersonation':
    'Alguien podría estar haciéndose pasar por tu banco: este correo dice venir de él, pero su firma no se pudo verificar.',
  'forwarding.quarantine.otherCard':
    'Si esa tarjeta no es tuya, alguien podría estar reenviándote correos de otra persona.',

  'forwarding.held.title': 'Estados de cuentas nuevas',
  'forwarding.held.lead':
    'Estos estados cuadran, pero son de una cuenta o tarjeta que todavía no tienes en Michelito. Apruébalos solo si son tuyos.',
  'forwarding.held.item': '{bank} · llegó el {date}',

  'forwarding.approvals.title': 'Aprobados a mano',
  'forwarding.approvals.lead':
    'Lo que entró porque lo aprobaste. Sus movimientos llevan la marca «Aprobado a mano».',
  'forwarding.approvals.statement': 'Estado de {domain} · {date}',
  'forwarding.approvals.alert': 'Aviso de consumo de {domain} · {date}',
  'forwarding.approvals.undo': 'Deshacer',
  'forwarding.badge.approved': 'Aprobado a mano',
  'forwarding.badge.approvedDetail':
    'Entró porque aprobaste un correo que no se pudo verificar como de tu banco. Puedes deshacerlo en Ajustes.',

  'forwarding.passwords.title': 'Claves de tus PDFs',
  'forwarding.passwords.lead':
    'Si guardas la clave de un banco, sus estados se leen apenas llegan. Se guarda cifrada en tu base y nunca se muestra.',
  'forwarding.passwords.stored': 'Guardada',
  'forwarding.passwords.none': 'Sin guardar',
  'forwarding.passwords.store': 'Guardar mi clave',
  'forwarding.passwords.forget': 'Olvidar mi clave',
  'forwarding.passwords.field': 'Clave de {bank}',
  'forwarding.passwords.save': 'Guardar',
  'forwarding.passwords.cancel': 'Cancelar',

  'forwarding.card.title': 'Tus estados',
  'forwarding.card.attention': 'Para atender',
  'forwarding.card.none': 'Todavía no llegó ningún estado por reenvío.',
  'forwarding.card.arrival': '{bank} · {account} · {month}',
  'forwarding.card.arrivedOn': 'llegó el {date}',
  'forwarding.card.waiting': {
    one: '{count} estado espera su clave',
    other: '{count} estados esperan su clave',
  },
  'forwarding.card.quarantine': {
    one: '{count} correo sin verificar',
    other: '{count} correos sin verificar',
  },
  'forwarding.card.overdue': 'Aún no llega el estado de {bank} · {account} (solía llegar el {date})',
  'forwarding.card.manage': 'Ver en Ajustes',
  'forwarding.problem.invalid': '{bank}: un estado no cuadró y no se guardó',
  'forwarding.problem.unsupported': '{bank}: llegó un estado que todavía no sabemos leer',
  'forwarding.problem.unreadable': '{bank}: llegó un estado que no pudimos leer',
  'forwarding.problem.too_complex': '{bank}: llegó un estado demasiado grande para leerlo',
  'forwarding.problem.full': '{bank}: la espera está llena y un estado no se guardó',
  'forwarding.problem.failed': '{bank}: un aviso de consumo no se pudo leer',
  'forwarding.problem.password_wrong': '{bank}: la clave guardada no abrió un estado',
  'forwarding.what': 'el reenvío',
} as const satisfies Catalog
