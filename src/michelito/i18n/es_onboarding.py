"""Spanish text of the hosted upload and onboarding routes (`michelito.hosted.onboarding_routes`).
None of these messages carries a password, a file's content or anything read from it."""

MESSAGES: dict[str, str] = {
    "onboarding.no_files": "elige al menos un estado en PDF",
    "onboarding.too_many_files": "son demasiados archivos: sube hasta {count} a la vez",
    "onboarding.file_too_large": "un archivo pasa de {megabytes} MB",
    "onboarding.upload_too_large": "entre todos pasan de {megabytes} MB: súbelos en partes",
    "onboarding.bad_file": "no pudimos leer uno de los archivos",
    "onboarding.bad_request": "la solicitud no es válida",
    "onboarding.unknown_job": "esa carga ya no existe: vuelve a subir los estados",
    "onboarding.unknown_bank": "ese banco no está en la lista",
    "onboarding.no_locked": "no queda ningún archivo con contraseña",
    "onboarding.rate_limited": (
        "subiste muchos estados seguidos: espera un rato y vuelve a intentarlo"
    ),
    "onboarding.password_rate_limited": (
        "probaste muchas contraseñas seguidas: espera unos minutos"
    ),
    "onboarding.unknown_merchant": "ese comercio no está entre los principales",
    "onboarding.unknown_share": "lo que compartiste ya no está: vuelve a compartirlo",
    "onboarding.gate_closed": "primero sube un estado que cuadre",
    "onboarding.log.first_review_closed": "Ajusta tus comercios principales",
    "onboarding.log.checklist_dismissed": "Para sacarle más provecho",
    "onboarding.log.shown": "visible",
    "onboarding.log.hidden": "oculto",
}
