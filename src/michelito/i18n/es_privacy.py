"""Spanish text of the public privacy page (`michelito.hosted.privacy`, `GET /privacy`). Its
English version, with the same keys, lives in that module. `{policy}` becomes the link to
Google's policy and `{email}` the contact address; both are escaped there."""

MESSAGES: dict[str, str] = {
    "privacy.title": "Privacidad en Michelito",
    "privacy.updated": "Última actualización: {date}.",
    "privacy.other_language": "English version below.",
    "privacy.back": "Volver a Michelito",
    "privacy.who.title": "Quiénes somos",
    "privacy.who.1": (
        "Michelito (michelito.app) es una app de finanzas personales que administra su propio "
        "autor. Esta política es la de la app en michelito.app, donde cada persona entra con su "
        "cuenta. La demo (demo.michelito.app) usa solo datos inventados."
    ),
    "privacy.stored.title": "Qué guardamos",
    "privacy.stored.1": "El correo electrónico de tu cuenta.",
    "privacy.stored.2": (
        "Tus sesiones y dispositivos: el navegador, el sistema y la fecha de la última "
        "actividad. Nunca guardamos tu dirección IP."
    ),
    "privacy.stored.3": (
        "Lo que sale de los estados de cuenta que subes o reenvías (movimientos, balances y "
        "cuentas), y tus correcciones y notas."
    ),
    "privacy.stored.4": (
        "De los correos de bancos y comercios, reenviados o leídos de Gmail, solo los datos que "
        "sacamos de ellos: montos, fechas, comercio, número de pedido, un resumen corto y el "
        "enlace al pedido. Nunca guardamos el cuerpo del correo."
    ),
    "privacy.stored.5": (
        "Los PDF que reenvías se leen y se borran. Un correo en cuarentena se guarda cifrado "
        "30 días; un estado que espera tu clave o tu aprobación, hasta 90 días."
    ),
    "privacy.stored.6": "La clave de los PDF de tu banco, solo si eliges guardarla.",
    "privacy.gmail.title": "Gmail (datos de usuario de Google)",
    "privacy.gmail.1": (
        "Conectar Gmail es opcional. Si lo conectas, Michelito pide solo el permiso de lectura "
        "(gmail.readonly): no puede enviar, borrar ni cambiar nada en tu correo."
    ),
    "privacy.gmail.2": (
        "Solo pedimos a Gmail los mensajes de los remitentes de comercios que la app conoce "
        "(hoy, las confirmaciones de pedido y de envío de Amazon) de los últimos 12 meses. De "
        "cada uno guardamos solo el monto, la fecha, el comercio, el número de pedido, un resumen "
        "corto y el enlace al pedido; nunca el cuerpo ni los adjuntos."
    ),
    "privacy.gmail.3": (
        "El acceso que Google nos da (un token de actualización) se guarda cifrado dentro de tu "
        "base de datos. Desconectar Gmail en Ajustes lo revoca ante Google y lo borra; también "
        "puedes quitar el acceso desde tu cuenta de Google. Los recibos ya leídos se quedan en tu "
        "cuenta, como el resto de tus datos."
    ),
    "privacy.gmail.4": (
        "Usamos los datos de usuario de Google solo para mostrarte tus propios recibos junto a "
        "tus movimientos. No los vendemos, no los usamos para publicidad ni para entrenar modelos "
        "de inteligencia artificial o de aprendizaje automático, y no se los pasamos a nadie, "
        "salvo lo necesario para dar esta función, por seguridad o porque la ley lo exija. "
        "Ninguna persona los lee, salvo con tu permiso, por seguridad o porque la ley lo exija."
    ),
    "privacy.gmail.5": (
        "El uso y la transferencia que Michelito hace de la información recibida de las API de "
        "Google se ajustan a la {policy}, incluidos los requisitos de uso limitado."
    ),
    "privacy.gmail.policy": "Política de datos de usuario de los servicios de API de Google",
    "privacy.protect.title": "Cómo lo protegemos",
    "privacy.protect.1": (
        "Cada cuenta tiene su propia base de datos, cifrada con AES-256 (SQLCipher) con una "
        "clave propia. Esa clave se guarda cifrada con una clave maestra del servidor. Todo viaja "
        "por HTTPS."
    ),
    "privacy.protect.2": (
        "Por eso el servidor sí puede leer tus datos: los necesita para recibir tus correos "
        "reenviados mientras no estás y para que no los pierdas si pierdes un dispositivo. No "
        "hay un modo en el que ni nosotros podamos leerlos."
    ),
    "privacy.protect.3": (
        "Las copias de seguridad, cifradas, se guardan en Cloudflare R2 y se borran a los 30 días."
    ),
    "privacy.others.title": "Quién más interviene",
    "privacy.others.1": "El proveedor del servidor virtual donde corre la app.",
    "privacy.others.2": (
        "Cloudflare: recibe los correos que reenvías (Email Routing) y guarda las copias de "
        "seguridad cifradas (R2)."
    ),
    "privacy.others.3": "Resend: envía los códigos para entrar (recibe tu correo y el código).",
    "privacy.others.4": "Google: solo si conectas Gmail.",
    "privacy.others.5": (
        "No hay analítica, ni publicidad, ni cookies de rastreo. Las únicas cookies son las que "
        "la app necesita para funcionar: la de tu sesión, una que reconoce un navegador donde ya "
        "entraste y una que se usa al compartir PDF desde el teléfono."
    ),
    "privacy.others.6": "Ningún servicio de inteligencia artificial recibe tus datos.",
    "privacy.keep.title": "Cuánto tiempo y cómo se borran",
    "privacy.keep.1": "Guardamos tus datos mientras exista tu cuenta.",
    "privacy.keep.2": (
        "Cuando se borra tu cuenta, su clave se destruye en el acto y sus datos quedan "
        "ilegibles. En las copias de seguridad se vuelven ilegibles y desaparecen a más tardar en "
        "30 días. Para borrar tu cuenta, escríbenos."
    ),
    "privacy.keep.3": (
        "Desconectar Gmail revoca el acceso de Michelito a tu correo. Borrar tu cuenta también "
        "lo revoca."
    ),
    "privacy.contact.title": "Contacto",
    "privacy.contact.email": "Para cualquier pregunta sobre tus datos, escribe a {email}.",
    "privacy.contact.none": (
        "Para cualquier pregunta sobre tus datos, escríbenos a la dirección de soporte de la app."
    ),
    "privacy.changes.title": "Cambios",
    "privacy.changes.1": "Si esta política cambia, actualizamos esta página y la fecha de arriba.",
}
