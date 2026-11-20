// Spanish UI text: hosted onboarding (the gate, uploading statements, the processing screen, the
// first review, the setup checklist, the sample-data band and the designed empty states). Keys
// start with "onboarding.".
import type { Catalog } from '../index'

export const onboarding = {
  'onboarding.gate.label': 'Bienvenida',
  'onboarding.gate.title': 'Empieza con tus estados de cuenta',
  'onboarding.gate.lead':
    'Sube los PDFs que te manda tu banco: varios a la vez, de distintos bancos y meses. Con uno que cuadre ya ves tu resumen.',
  'onboarding.gate.trust':
    'Tus estados se leen y se descartan; solo guardamos las transacciones que cuadran, cifradas a tu nombre.',
  'onboarding.gate.demo': 'Ver datos de ejemplo',
  'onboarding.gate.signOut': 'Cerrar sesión',

  'onboarding.upload.label': 'Subir estados',
  'onboarding.upload.title': 'Importar estados',
  'onboarding.upload.lead':
    'Sube más meses o estados de otra cuenta. Solo se guarda lo que cuadra con los totales del banco.',
  'onboarding.upload.drop': 'Arrastra aquí tus estados en PDF',
  'onboarding.upload.pick': 'Elegir PDFs',
  'onboarding.upload.hint': 'Hasta {count} archivos a la vez, de {megabytes} MB cada uno como máximo.',
  'onboarding.upload.uploading': 'Subiendo…',
  'onboarding.upload.notPdf': '{name} no es un PDF.',
  'onboarding.upload.tooMany': 'Elige hasta {count} archivos a la vez.',
  'onboarding.upload.tooLarge': '{name} pasa de {megabytes} MB.',
  'onboarding.upload.more': 'Subir otros estados',
  'onboarding.share.title': {
    one: '¿Importar 1 archivo compartido?',
    other: '¿Importar {count} archivos compartidos?',
  },
  'onboarding.share.lead': 'Llegaron desde el menú Compartir de tu teléfono. Revisa que sean tus estados.',
  'onboarding.share.size': '{size} KB',
  'onboarding.share.import': 'Importar',
  'onboarding.share.discard': 'Descartar',
  'onboarding.upload.files': 'Tus archivos',

  'onboarding.file.queued': 'En cola',
  'onboarding.file.reading': 'Leyendo…',
  'onboarding.file.squared': '✓ cuadró al centavo',
  'onboarding.file.duplicate': 'Ya lo tenías: no se guardó otra vez',
  'onboarding.file.invalid':
    'Los totales no coinciden; no lo guardamos para no mostrarte números falsos.',
  'onboarding.file.locked': 'Tiene contraseña',
  'onboarding.file.unsupported': 'Todavía no leemos estados de este banco o de este formato.',
  'onboarding.file.unreadable': 'No pudimos leerlo: ¿es el PDF que manda el banco?',
  'onboarding.file.tooComplex':
    'Es demasiado largo o pesado para leerlo con seguridad (más de 50 páginas o demasiado contenido).',
  'onboarding.file.statements': { one: '1 estado', other: '{count} estados' },
  'onboarding.account.card': 'Tarjeta ···{last4}',
  'onboarding.account.other': 'Cuenta ···{last4}',

  'onboarding.password.title': 'Algunos archivos tienen contraseña',
  'onboarding.password.lead':
    'Elige el banco y escribe la contraseña de sus PDFs: la probamos en todos los archivos que faltan. Solo la usamos para abrirlos ahora; no la guardamos.',
  'onboarding.password.bank': 'Banco',
  'onboarding.password.field': 'Contraseña de los PDFs',
  'onboarding.password.submit': 'Abrir',
  'onboarding.password.trying': 'Probando…',
  'onboarding.password.wrong':
    'La contraseña de {bank} no abrió ningún archivo. Revísala y vuelve a escribirla.',
  'onboarding.password.tried': {
    one: 'La contraseña de {bank} abrió 1 archivo.',
    other: 'La contraseña de {bank} abrió {count} archivos.',
  },
  'onboarding.password.left': {
    one: 'Falta 1 archivo con contraseña.',
    other: 'Faltan {count} archivos con contraseña.',
  },

  'onboarding.request.open': 'Avísame cuando lo soportemos',
  'onboarding.request.which': '¿De qué banco es?',
  'onboarding.request.send': 'Avisarme',
  'onboarding.request.done': 'Anotado. Solo guardamos el nombre del banco, no tu correo.',

  'onboarding.bank.popular': 'Popular',
  'onboarding.bank.bhd': 'BHD',
  'onboarding.bank.banreservas': 'Banreservas',
  'onboarding.bank.scotiabank': 'Scotiabank',
  'onboarding.bank.santa_cruz': 'Banco Santa Cruz',
  'onboarding.bank.apap': 'APAP',
  'onboarding.bank.cibao': 'Asociación Cibao',
  'onboarding.bank.banesco': 'Banesco',
  'onboarding.bank.promerica': 'Promerica',
  'onboarding.bank.bdi': 'Banco BDI',
  'onboarding.bank.caribe': 'Banco Caribe',
  'onboarding.bank.vimenca': 'Banco Vimenca',
  'onboarding.bank.lafise': 'Banco Lafise',
  'onboarding.bank.ademi': 'Banco Ademi',
  'onboarding.bank.lopez_de_haro': 'Banco López de Haro',
  'onboarding.bank.other': 'Otro',

  'onboarding.result.open': 'Ver mi resumen',
  'onboarding.result.nudge': 'Con 3 meses verás tus gastos habituales y tus recurrentes.',
  'onboarding.result.none': 'Ningún estado cuadró',
  'onboarding.result.noneLead':
    'No abrimos tu resumen con números que no cuadran. Prueba con otro estado, o mira cómo se ve Michelito con datos de ejemplo.',
  'onboarding.result.retry': 'Prueba con otro estado',

  'onboarding.review.title': 'Ajusta tus comercios principales',
  'onboarding.review.lead':
    'Donde más gastaste. Confirma su categoría o cámbiala: el cambio vale para todo ese comercio.',
  'onboarding.review.correct': '✓ Correcto',
  'onboarding.review.change': 'Cambiar',
  'onboarding.review.later': 'Luego',
  'onboarding.review.reviewed': 'Revisado',
  'onboarding.review.rule': 'Cambiado',
  'onboarding.review.save': 'Guardar',
  'onboarding.review.category': 'Categoría',
  'onboarding.review.sheet': 'Categoría de {merchant}',
  'onboarding.review.purchases': { one: '1 compra', other: '{count} compras' },

  'onboarding.checklist.title': 'Para sacarle más provecho',
  'onboarding.checklist.months': 'Agrega más meses',
  'onboarding.checklist.monthsProgress': '{count} de 3 meses',
  'onboarding.checklist.account': 'Agrega otra cuenta',
  'onboarding.checklist.automate': 'Automatiza los próximos',
  'onboarding.checklist.soon': 'Próximamente',
  'onboarding.checklist.missing': 'Te falta {month} de {bank} {account}',
  'onboarding.checklist.done': 'Hecho',
  'onboarding.checklist.upload': 'Subir',
  'onboarding.checklist.dismiss': 'Ocultar',

  'onboarding.band.label': 'Aviso de datos de ejemplo',
  'onboarding.band.text': 'Datos de ejemplo',
  'onboarding.band.back': 'Volver a subir mis estados',

  'onboarding.empty.preview': 'Ver cómo se ve',
  'onboarding.empty.upload': 'Subir estados',
  'onboarding.empty.uploadMonth': 'Subir otro mes',
  'onboarding.empty.toTransactions': 'Ir a transacciones',
  'onboarding.empty.summary.title': 'Aquí verás tu mes',
  'onboarding.empty.summary.text':
    'Lo que entró, lo que salió y lo que te quedó, en cuanto subas un estado que cuadre.',
  'onboarding.empty.budget.title': 'Tu presupuesto sale de tus gastos',
  'onboarding.empty.budget.text':
    'Con un mes de compras te proponemos un tope por categoría, basado en lo que gastas de verdad.',
  'onboarding.empty.transactions.title': 'Aquí verás cada compra',
  'onboarding.empty.transactions.text':
    'Cada movimiento de tus estados, con su categoría, para buscar y corregir en un toque.',
  'onboarding.empty.pending.title': 'Lo que te deben y lo que debes',
  'onboarding.empty.pending.text':
    'Cuando compartas un gasto o prestes dinero, aquí verás quién te debe y cuánto.',
  'onboarding.empty.investments.title': 'Tus inversiones, en un solo lugar',
  'onboarding.empty.investments.text':
    'Marca como inversión una transferencia a un puesto de bolsa o a un certificado y verás cuánto rinde.',
  'onboarding.empty.investments.suggest': '¿Esto es una inversión?',
  'onboarding.empty.investments.suggestText':
    'Estas transferencias parecen ir a un puesto de bolsa o a un certificado.',
  'onboarding.empty.investments.open': 'Revisar',
  'onboarding.empty.recurring.title': 'Necesito 2 meses para encontrar tus pagos fijos',
  'onboarding.empty.recurring.text':
    'Suscripciones, seguros y préstamos aparecen aquí cuando se repiten de un mes a otro.',
  'onboarding.empty.reports.title': 'Compara tus meses',
  'onboarding.empty.reports.text':
    'Con dos meses o más verás en qué gastaste más o menos que de costumbre.',
  'onboarding.empty.log.title': 'Tu historial de cambios',
  'onboarding.empty.log.text':
    'Cada categoría o nota que cambies queda anotada aquí, y la puedes deshacer.',
} as const satisfies Catalog
