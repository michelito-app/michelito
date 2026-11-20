"""Spanish text of the shared ledger (schema 19): API errors, review reasons and migrated
names."""

MESSAGES: dict[str, str] = {
    "analysis.accounts.group_account_name": "Compartidos",
    "core.migration_mismatch": (
        "La base no se actualizó: al pasar los grupos compartidos a la versión 19 un saldo "
        "cambiaría ({detail}). Quedó como estaba. Revisa una copia con "
        "«uv run python scripts/check_shared_migration.py <copia.db>» y avísanos."
    ),
    "analysis.ledger.name_required": "escribe un nombre",
    "analysis.ledger.text_too_long": "el texto tiene más de {max} letras",
    "analysis.ledger.unknown_contact": "persona desconocida: {id}",
    "analysis.ledger.me_fixed": "«Tú» siempre está en el grupo y no se cambia",
    "analysis.ledger.alias_taken": "ese nombre ya es de otra persona",
    "analysis.ledger.unknown_alias": "esa persona no tiene ese nombre",
    "analysis.ledger.merge_invalid": "elige otra persona para unir",
    "analysis.ledger.member_in_use": "esa persona tiene gastos o pagos en el grupo",
    "analysis.ledger.not_member": "esa persona no está en el grupo",
    "analysis.ledger.unknown_split": "la división es «igual» o «montos exactos»",
    "analysis.ledger.split_needs_people": "marca al menos una persona",
    "analysis.ledger.exact_must_add_up": "los montos exactos tienen que sumar el total",
    "analysis.ledger.link_needs_me": "solo un gasto que pagaste tú se enlaza a tu banco",
    "analysis.ledger.unknown_entry": "gasto desconocido: {id}",
    "analysis.ledger.payment_needs_me": "un pago es tuyo: de ti o para ti",
    "analysis.ledger.unknown_payment": "pago desconocido: {id}",
    "analysis.ledger.payment_linked": "ese pago ya está enlazado",
    "analysis.ledger.not_linked": "no está enlazado",
    "analysis.ledger.migrated_group": "Grupo {id}",
    "analysis.ledger.placeholder": "Persona {number}",
    "analysis.changelog.old_shared": (
        "Es de un grupo compartido de antes de la versión 19: ese grupo pasó a Compartidos con "
        "personas, y ahí se cambia (cada cambio nuevo sí se puede deshacer)."
    ),
    "analysis.changelog.parent_group": "El grupo",
    "analysis.changelog.parent_entry": "El gasto",
    "analysis.changelog.parent_contact": "La persona",
    "analysis.changelog_rules.ledger_group": "grupo «{name}»",
    "analysis.changelog_rules.ledger_archived": " (archivado)",
    "analysis.changelog_rules.ledger_member": "en el grupo",
    "analysis.changelog_rules.ledger_member_written_off": "no me lo va a pagar",
    "analysis.changelog_rules.ledger_entry": "gasto «{what}» de {amount}",
    "analysis.changelog_rules.ledger_split": "parte de {amount}",
    "analysis.changelog_rules.ledger_payment": "pago de {amount}",
    "analysis.changelog_rules.ledger_link": "transacción enlazada",
    "analysis.changelog_rules.ledger_setting": "«Revisa tus personas» pendiente",
    "web.ledger.group_number": "grupo {id}",
    "web.ledger.contact_number": "persona {id}",
    "web.ledger.review_people": "Revisa tus personas",
    "web.ledger.invalid_day": "fecha inválida",
    "web.ledger.description_required": "escribe una descripción",
    "web.ledger.payment_currency": "la transacción está en otra moneda",
    "web.ledger.payment_needs_debit": "un pago que hiciste es un débito sin otro vínculo",
    "web.review.payment_reason": "¿{name} te pagó? Te debe en «{group}»",
    "web.review.payment_link_reason": "¿Es el pago de {name} en «{group}»? Está sin enlazar",
    "web.review.payment_someone": "alguien",
}
