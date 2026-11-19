"""Spanish text of the public demo (`michelito.demo`): its notice and the messages its routes
show to the visitor."""

MESSAGES: dict[str, str] = {
    "demo.notice": "Demo con datos inventados · tus cambios se borran en 24 h",
    "demo.full": "La demo está llena por ahora: vuelve a intentarlo en un rato.",
    "demo.restarts": (
        "Ya empezaste de nuevo hace poco (se puede una vez cada 5 minutos y unas pocas veces al "
        "día)."
    ),
    "demo.copy_full": (
        "Tu copia de la demo llegó a su límite de tamaño; se reinicia en 24 h o desde «Empezar de "
        "nuevo»."
    ),
    "demo.too_many_copies": (
        "Ya se crearon varias copias de la demo desde tu conexión hoy: vuelve mañana o usa la que "
        "ya tienes."
    ),
    "demo.no_session": "no hay sesión de la demo: recarga la página",
    "demo.internal_error": "error interno",
    "demo.samples_used": "ya probaste varios estados de ejemplo en esta copia",
    "demo.feedback_used": "ya enviaste varias opiniones desde esta copia: ¡gracias!",
    "demo.retry_later": "{reason}: vuelve a intentarlo más tarde",
    "demo.unknown_event": "evento desconocido",
    "demo.copy_busy": "tu copia de la demo está ocupada: vuelve a intentarlo",
    "demo.busy": "la demo está ocupada: vuelve a intentarlo en unos segundos",
    "demo.too_many_requests": "demasiadas peticiones: espera un minuto",
    "demo.sample_duplicate": "ese estado ya se importó",
    # Feedback (`demo.feedback_store`).
    "demo.feedback.text_length": "la opinión tiene que tener entre 1 y {max} letras",
    "demo.feedback.bad_email": "el correo no parece válido",
    "demo.feedback.bad_ref": "ref inválido",
    "demo.feedback.per_minute": "demasiadas opiniones en este minuto",
    "demo.feedback.per_day": "ya llegaron muchas opiniones hoy",
    "demo.feedback.store_full": "el buzón de opiniones está lleno",
}
