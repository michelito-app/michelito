"""Spanish text of the AI connector's routes (`hosted.connector_routes`)."""

MESSAGES: dict[str, str] = {
    "connector.bad_request": (
        "esta solicitud de conexión no es válida: vuelve a conectar desde Claude"
    ),
    "connector.request_gone": (
        "esta solicitud de conexión ya venció o se usó: vuelve a conectar desde Claude"
    ),
    "connector.rate_limited": "demasiados intentos; espera unos minutos",
    "connector.connection_gone": "esa conexión ya no existe",
}
