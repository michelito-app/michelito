"""Spanish text of the browser extension's routes (`hosted.extension_routes`)."""

MESSAGES: dict[str, str] = {
    "extension.bad_code": (
        "ese código no sirve: genera uno nuevo en Ajustes y pégalo antes de 10 minutos"
    ),
    "extension.no_token": (
        "la extensión no está vinculada; vincúlala de nuevo con un código de Ajustes"
    ),
    "extension.rate_limited": "demasiados intentos; espera unos minutos",
    "extension.other_origin": "esta ruta es solo para la extensión de Michelito",
    "extension.too_many_orders": "ya hay demasiados pedidos con nombres en esta cuenta",
    "extension.failed": "no se pudieron guardar los nombres; prueba de nuevo",
}
