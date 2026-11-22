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
    "analysis.ledger.not_member": "esa persona no está en el grupo",
    "analysis.ledger.used_entry": "«{what}» ({day})",
    "analysis.ledger.used_shares": "tiene parte en {list}",
    "analysis.ledger.used_paid": "pagó {list}",
    "analysis.ledger.used_payment": "tiene un pago en el grupo: {list}",
    "analysis.ledger.used_payments": "tiene pagos en el grupo: {list}",
    "analysis.ledger.used_payment_item": "{amount} el {day}",
    "analysis.ledger.used_in": "No se puede quitar a {name}: {what}.",
    "analysis.ledger.used_resplit_hint": (
        " Puedes quitarlo de {count} gasto(s) y del grupo: esos gastos se dividen de nuevo "
        "entre los demás."
    ),
    "analysis.ledger.used_blocked_hint": (
        " Primero borra o cambia esos gastos y pagos (o deja a la persona en el grupo)."
    ),
    "analysis.ledger.parts_positive": "cada persona tiene al menos 1 parte",
    "analysis.ledger.allocations_need_payer": (
        "«También paga por…» es solo para un pago que otra persona te hizo"
    ),
    "analysis.ledger.allocation_not_me": "un pago no puede ser por ti",
    "analysis.ledger.allocations_add_up": "lo que cubre por cada persona tiene que sumar el pago",
    "analysis.ledger.allocation_twice": "una persona aparece dos veces en lo que cubre el pago",
    "analysis.ledger.unknown_split": "la división es «iguales», «montos exactos» o «por partes»",
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
    "analysis.changelog.parent_payment": "El pago",
    "analysis.changelog.parent_contact": "La persona",
    "analysis.changelog_rules.ledger_group": "grupo «{name}»",
    "analysis.changelog_rules.ledger_archived": " (archivado)",
    "analysis.changelog_rules.ledger_member": "en el grupo",
    "analysis.changelog_rules.ledger_member_written_off": "no me lo va a pagar",
    "analysis.changelog_rules.ledger_entry": "gasto «{what}» de {amount}",
    "analysis.changelog_rules.ledger_split": "parte de {amount}",
    "analysis.changelog_rules.ledger_payment": "pago de {amount}",
    "analysis.changelog_rules.ledger_allocation": "cubre {amount}",
    "analysis.changelog_rules.ledger_link": "transacción enlazada",
    "analysis.changelog_rules.ledger_setting": "«Revisa tus personas» pendiente",
    "analysis.changelog_ledger.and": "{head} y {last}",
    "analysis.changelog_ledger.someone": "alguien",
    "analysis.changelog_ledger.you": "ti",
    "analysis.changelog_ledger.person_number": "la persona {id}",
    "analysis.changelog_ledger.group_new": "Creaste el grupo {group}",
    "analysis.changelog_ledger.group_new_with": "Creaste el grupo {group} con {names}",
    "analysis.changelog_ledger.group_renamed": "Renombraste el grupo {old} a {new}",
    "analysis.changelog_ledger.group_archived": "Archivaste el grupo {group}",
    "analysis.changelog_ledger.group_unarchived": "Sacaste del archivo el grupo {group}",
    "analysis.changelog_ledger.group_category": "Cambiaste la categoría del grupo {group}",
    "analysis.changelog_ledger.member_added": "Agregaste a {names} al grupo {group}",
    "analysis.changelog_ledger.member_removed": "Quitaste a {names} del grupo {group}",
    "analysis.changelog_ledger.member_removed_resplit": (
        "Quitaste a {names} del grupo {group} y de {count} gasto(s), divididos entre los demás"
    ),
    "analysis.changelog_ledger.written_off_one": (
        "Marcaste que {names} no te lo va a pagar en {group}"
    ),
    "analysis.changelog_ledger.written_off_many": (
        "Marcaste que {names} no te lo van a pagar en {group}"
    ),
    "analysis.changelog_ledger.written_back_one": "{names} vuelve a deberte en {group}",
    "analysis.changelog_ledger.written_back_many": "{names} vuelven a deberte en {group}",
    "analysis.changelog_ledger.entry_added": (
        "Agregaste el gasto «{what}» de {amount} al grupo {group}"
    ),
    "analysis.changelog_ledger.entry_deleted": (
        "Borraste el gasto «{what}» de {amount} del grupo {group}"
    ),
    "analysis.changelog_ledger.entry_changed": "Cambiaste el gasto «{what}» del grupo {group}",
    "analysis.changelog_ledger.split_changed": "Cambiaste una división en el grupo {group}",
    "analysis.changelog_ledger.payment_between": "un pago de {source} a {target} de {amount}",
    "analysis.changelog_ledger.payment_unassigned": "un pago sin asignar de {amount}",
    "analysis.changelog_ledger.covering": " (cubre a {names})",
    "analysis.changelog_ledger.payment_added": "Registraste {payment} en el grupo {group}",
    "analysis.changelog_ledger.payment_deleted": "Borraste {payment} del grupo {group}",
    "analysis.changelog_ledger.payment_assigned": (
        "Asignaste a {name} el pago de {amount} del grupo {group}"
    ),
    "analysis.changelog_ledger.payment_accepted": (
        "Aceptaste la diferencia del pago de {amount} del grupo {group}"
    ),
    "analysis.changelog_ledger.payment_linked": "Enlazaste un pago del grupo {group} a tu banco",
    "analysis.changelog_ledger.payment_unlinked": (
        "Desenlazaste un pago del grupo {group} de tu banco"
    ),
    "analysis.changelog_ledger.covering_changed": (
        "Cambiaste a quién cubre un pago del grupo {group}: también a {names}"
    ),
    "analysis.changelog_ledger.covering_removed": (
        "Quitaste a {names} de un pago del grupo {group}"
    ),
    "analysis.changelog_ledger.covering_amounts": (
        "Cambiaste cuánto cubre de cada persona un pago del grupo {group}"
    ),
    "analysis.changelog_ledger.cover_dismissed": (
        "Respondiste que un pago del grupo {group} no era por nadie más"
    ),
    "analysis.changelog_ledger.cover_asked": (
        "Volviste a preguntar si un pago del grupo {group} era por alguien más"
    ),
    "analysis.changelog_ledger.leftover_on": (
        "Las diferencias de cambio de {names} cuentan como saldadas en {group}"
    ),
    "analysis.changelog_ledger.leftover_off": (
        "Las diferencias de cambio de {names} vuelven a contar en {group}"
    ),
    "analysis.ledger.cover_reason_one": (
        "{payer} pagó {excess} de más y {names} debe {owed}. ¿Ese pago también era por {names}?"
    ),
    "analysis.ledger.cover_reason_many": (
        "{payer} pagó {excess} de más y {names} deben {owed}. ¿Ese pago también era por {names}?"
    ),
    "analysis.ledger.cover_reason_one_payments": (
        "{payer} pagó {excess} de más en {count} pagos y {names} debe {owed}. "
        "¿Esos pagos también eran por {names}?"
    ),
    "analysis.ledger.cover_reason_many_payments": (
        "{payer} pagó {excess} de más en {count} pagos y {names} deben {owed}. "
        "¿Esos pagos también eran por {names}?"
    ),
    "analysis.changelog_ledger.covering_changed_many": (
        "Cambiaste a quién cubren {count} pagos del grupo {group}: también a {names}"
    ),
    "analysis.changelog_ledger.cover_dismissed_many": (
        "Respondiste que {count} pagos del grupo {group} no eran por nadie más"
    ),
    "analysis.changelog_ledger.cover_asked_many": (
        "Volviste a preguntar si {count} pagos del grupo {group} eran por alguien más"
    ),
    "analysis.ledger.cover_other_group": "ese pago no es de este grupo",
    "analysis.ledger.no_cover": "no hay nada que proponer en este grupo",
    "analysis.changelog_ledger.contact_added": "Agregaste a {name} a tus personas",
    "analysis.changelog_ledger.contact_renamed": "Renombraste a {old} como {new}",
    "analysis.changelog_ledger.alias_added": "Agregaste «{alias}» como otro nombre de {name}",
    "analysis.changelog_ledger.alias_removed": "Quitaste «{alias}» de los nombres de {name}",
    "analysis.changelog_ledger.contact_merged": "Uniste a {source} con {target}",
    "analysis.changelog_ledger.review_people": "Revisaste tus personas",
    "web.ledger.group_number": "grupo {id}",
    "web.ledger.contact_number": "persona {id}",
    "web.ledger.review_people": "Revisa tus personas",
    "web.ledger.invalid_day": "fecha inválida",
    "web.ledger.description_required": "escribe una descripción",
    "web.ledger.payment_currency": "la transacción está en otra moneda",
    "analysis.ledger_credit.paid_over": (
        "lo que te pagaron es más que los gastos: elige «partes iguales» o agrega otro gasto"
    ),
    "web.ledger_credit.one_currency": (
        "para que su parte sea lo que pagó, los gastos y los pagos van en la misma moneda"
    ),
    "web.ledger_credit.needs_person": "elige quién te pagó cada transacción",
    "web.ledger_credit.repeated": "esa transacción está dos veces",
    "web.ledger.payment_needs_debit": "un pago que hiciste es un débito sin otro vínculo",
    "web.review.payment_reason": "¿{name} te pagó? Te debe en «{group}»",
    "web.review.payment_link_reason": "¿Es el pago de {name} en «{group}»? Está sin enlazar",
    "web.review.payment_someone": "alguien",
}
