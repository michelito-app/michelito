"""Spanish text of email forwarding (`michelito.hosted.forwarding_routes` and `notices`): API
messages and the problem emails, which never carry an amount, a name, a sender or a file name."""

MESSAGES: dict[str, str] = {
    "forwarding.off": "el reenvío de correos no está activado en este servidor",
    "forwarding.bad_signature": "solicitud no autorizada",
    "forwarding.replayed": "esta solicitud ya se recibió",
    "forwarding.bad_request": "la solicitud no tiene el formato esperado",
    "forwarding.too_large": "el correo es demasiado grande",
    "forwarding.unknown_address": "esa dirección no existe",
    "forwarding.rate_limited": "llegaron demasiados correos; prueba más tarde",
    "forwarding.failed": "no se pudo procesar el correo; se reintentará",
    "forwarding.busy": "el servidor está ocupado; se reintentará",
    "forwarding.bad_length": "el cuerpo no tiene el largo declarado",
    "forwarding.too_slow": "el cuerpo tardó demasiado en llegar",
    "forwarding.address_exists": "ya tienes una dirección: cámbiala en lugar de crear otra",
    "forwarding.unknown_bank": "banco desconocido",
    "forwarding.unknown_item": "ese correo ya no está",
    "forwarding.confirm_first": "confirma primero que quieres aprobarlo",
    "forwarding.approval_in_use": (
        "no se puede deshacer: alguno de sus movimientos tiene una nota, está en un grupo, "
        "en un vínculo o ya confirmó un aviso; quítalo de ahí primero"
    ),
    "forwarding.notice.subject": "Michelito: algo pasó con tus estados",
    "forwarding.notice.body": (
        "{problem}\n\n"
        "Ábrelo en Michelito: {link}\n\n"
        "Este correo solo llega cuando hay un problema con lo que reenvías. "
        "No incluye montos ni movimientos.\n"
    ),
    "forwarding.notice.quarantine": (
        "Llegó un correo que no pudimos verificar como de tu banco. Está en espera, sin abrir, "
        "hasta que lo apruebes o lo descartes."
    ),
    "forwarding.notice.password_missing": (
        "Llegó un estado protegido con clave. Escribe la clave de ese banco para leerlo."
    ),
    "forwarding.notice.password_wrong": (
        "La clave guardada no abrió un estado que llegó. Escribe la clave nueva de ese banco."
    ),
    "forwarding.notice.unsupported": "Llegó un estado de un banco que todavía no leemos.",
    "forwarding.notice.invalid": (
        "Llegó un estado cuyos totales no cuadran: no lo guardamos para no mostrarte "
        "números falsos."
    ),
    "forwarding.notice.unreadable": "Llegó un estado que no pudimos leer.",
    "forwarding.notice.full": (
        "Llegó un correo que no se pudo guardar porque la espera está llena. Revisa los estados "
        "y correos en espera."
    ),
    "forwarding.notice.new_account": (
        "Llegó un estado de una cuenta o tarjeta que todavía no tienes en Michelito. Apruébalo "
        "si es tuyo; si no, descártalo."
    ),
    "forwarding.notice.overdue": (
        "Un estado que suele llegar por estas fechas todavía no llegó. Revisa tu reenvío."
    ),
}
