"""Spanish text of hosted mode (`michelito.hosted`): the sign-in emails and the messages its
routes return. The emails carry only the code, its expiry and a warning: nothing financial."""

MESSAGES: dict[str, str] = {
    "hosted.email.code_subject": "Tu código para entrar a Michelito",
    "hosted.email.code_body": (
        "Tu código para entrar a Michelito es:\n\n"
        "    {code}\n\n"
        "Vence en {minutes} minutos y sirve una sola vez.\n"
        "{link}\n"
        "Si no fuiste tú, ignora este correo: sin el código nadie puede entrar.\n"
    ),
    "hosted.email.link": "\nEn la computadora también puedes abrir este enlace:\n{url}\n",
    "hosted.email.invite_subject": "Te invitaron a Michelito",
    "hosted.email.invite_body": (
        "Te invitaron a Michelito.\n\n"
        "Entra en {url}, escribe este correo y luego el código:\n\n"
        "    {code}\n\n"
        "La invitación vence en {days} días y sirve una sola vez.\n"
        "{link}\n"
        "Si no esperabas esta invitación, ignora este correo.\n"
    ),
    "hosted.signed_out": "no has iniciado sesión",
    "hosted.wrong_code": "el código no es correcto o ya venció",
    "hosted.rate_limited": "pediste demasiados códigos: espera unos minutos",
    "hosted.mail_unavailable": (
        "ahora mismo no podemos enviar códigos: vuelve a intentarlo más tarde"
    ),
    "hosted.step_up_required": "confirma con un código nuevo para seguir",
    "hosted.bad_email": "el correo no parece válido",
    "hosted.invitations_off": "las invitaciones entre personas están desactivadas",
    "hosted.already_member": "ese correo ya tiene cuenta",
}
