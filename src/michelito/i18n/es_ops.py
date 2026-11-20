"""Spanish text of the hosted operations email (`michelito.hosted.ops`): only what failed, with
counts; never an address, a file name or an amount."""

MESSAGES: dict[str, str] = {
    "hosted.ops.subject": "Michelito: algo falló en el servidor",
    "hosted.ops.body": (
        "La revisión diaria del servidor encontró esto:\n\n"
        "{problems}\n\n"
        "Este correo solo llega cuando algo falla.\n"
    ),
    "hosted.ops.backup_failed": "El último respaldo falló ({reason}).",
    "hosted.ops.backup_never": "Todavía no hay ningún respaldo que haya funcionado.",
    "hosted.ops.backup_old": "El último respaldo que funcionó fue hace {hours} horas.",
    "hosted.ops.mail_failed": "{count} correos con código no se pudieron enviar en el último día.",
    "hosted.ops.parser_failed": (
        "{count} estados no se pudieron leer en el último día (tipos: {kinds})."
    ),
    "hosted.ops.unreadable": "{count} cuentas no se pudieron abrir para revisarlas.",
}
