"""Spanish text produced by `michelito.analysis`: change-log descriptions, review reasons, API
error details, seed category names and labels the UI shows."""

MESSAGES: dict[str, str] = {
    # --- group A: links, transfers, exchanges, reversals, corrections, accounts, coverage,
    # interest, rates, bcrd ---
    "analysis.accounts.cash_box_name": "Efectivo",
    "analysis.corrections.note_too_long": "la nota tiene más de {max} letras",
    "analysis.exchanges.needs_both_currencies": "un cambio necesita patas en RD$ y en US$",
    "analysis.exchanges.opposite_directions": (
        "las patas de una moneda van en una dirección y las de la otra al revés"
    ),
    "analysis.exchanges.zero_leg": "una pata sin monto no sirve",
    "analysis.links.already_linked": "la transacción ya está en otro vínculo",
    "analysis.links.only_expense_shared": "solo un gasto (monto positivo) se puede compartir",
    "analysis.links.choose_split": (
        "elige una forma de repartir: «Éramos N», «Mi parte» u «otra persona»"
    ),
    "analysis.links.people_range": "«Éramos N» va de 2 a 100 personas",
    "analysis.links.share_range": "tu parte tiene que ser mayor que 0 y no más que el gasto",
    "analysis.links.credit_already_linked": "ese crédito ya está enlazado",
    "analysis.links.not_group_reimbursement": "ese crédito no es un reembolso del grupo",
    "analysis.links.amount_positive": "el monto tiene que ser mayor que 0",
    "analysis.links.currency_choice": "la moneda es RD$ o US$",
    "analysis.links.manual_not_in_group": "ese reembolso a mano no es del grupo",
    "analysis.links.exchange_needs_legs": "un cambio necesita al menos una pata en cada moneda",
    "analysis.links.leg_already_linked": "una de las transacciones ya está en otro vínculo",
    "analysis.links.rate_positive": "la tasa tiene que ser mayor que 0",
    "analysis.links.credit_not_contribution": "un crédito no puede ser un aporte",
    "analysis.links.credit_not_in_investment": "ese crédito no es de la inversión",
    "analysis.links.move_not_in_investment": "ese movimiento no es de la inversión",
    "analysis.links.capital_only_mixed": "solo un crédito mixto lleva una parte de capital",
    "analysis.links.capital_range": (
        "la parte de capital tiene que ser mayor que 0 y menor que el crédito"
    ),
    "analysis.links.not_shared": "la transacción no está marcada como compartida",
    "analysis.links.too_many_decimals": "el monto tiene más de dos decimales",
    "analysis.links.invalid_amount": "monto inválido",
    "analysis.links.unknown_role": "tipo desconocido: {role}",
    "analysis.links.unknown_investment": "inversión desconocida: {id}",
    "analysis.links.unknown_group": "grupo desconocido: {id}",
    "analysis.links.unknown_exchange": "cambio desconocido: {id}",
    "analysis.links.text_too_long": "«{field}» tiene más de {max} letras",
    "analysis.links.field_with_whom": "con quién",
    "analysis.links.field_name": "nombre",
    "analysis.links.field_from_whom": "de quién",
    "analysis.links.field_place": "dónde",
    # --- end group A ---
    # --- group B: spending, shared, anomalies, one_offs, one_off_dismissals, report, review,
    # review_marks ---
    # Reasons of a one-off expense suggestion (`one_offs`), joined with " · ".
    "analysis.one_offs.category_times": "{times} veces tu compra típica en {category}",
    "analysis.one_offs.rare_category": "categoría poco usada",
    "analysis.one_offs.new_merchant": "comercio nuevo",
    "analysis.one_offs.infrequent_merchant": "comercio poco frecuente",
    "analysis.one_offs.merchant_times": "{times} veces lo usual en {merchant}",
    # Reasons in "To review" (`review`).
    "analysis.review.since_last_year": "en el último año",
    "analysis.review.since_last_days": "en los últimos {days} días",
    "analysis.review.unusual_income": (
        "Ingreso de {amount} de una contraparte nueva: no te pagó {since}"
    ),
    "analysis.review.large_third_party": (
        "Transferencia a terceros de {amount} (desde {threshold} se revisa)"
    ),
    "analysis.review.same_day": "el mismo día",
    "analysis.review.previous_day": "el día anterior",
    "analysis.review.duplicate": "Mismo comercio, monto y cuenta que otro cargo {when}",
    # --- end group B ---
    # --- group C: categories, catalog, changelog, changelog_rules, claude_prompt, insights ---
    "analysis.categories.kind_income": "ingreso",
    "analysis.categories.kind_expense": "gasto",
    "analysis.categories.kind_transfer": "transferencia",
    "analysis.catalog.keyword_too_long": "palabra clave demasiado larga: {keyword}…",
    "analysis.catalog.keyword_empty": "palabra clave sin letras ni números: {keyword}",
    "analysis.catalog.too_many_keywords": "a lo sumo {max} palabras clave por categoría",
    "analysis.catalog.system_suffix": "{name} (sistema)",
    "analysis.catalog.link_only": (
        "«{name}» la pone su vínculo: márcalo desde el detalle de la transacción"
    ),
    "analysis.catalog.unknown": "categoría desconocida: {category}",
    "analysis.catalog.builtin_kind": "el tipo de una categoría del sistema no se puede cambiar",
    "analysis.catalog.builtin_delete": (
        "una categoría del sistema no se puede borrar (se puede ocultar)"
    ),
    "analysis.catalog.in_use": "la categoría tiene transacciones: elige a cuál pasan",
    "analysis.catalog.same_target": "el destino tiene que ser otra categoría",
    "analysis.catalog.name_empty": "el nombre no puede quedar vacío",
    "analysis.catalog.name_too_long": "el nombre tiene más de {max} letras",
    "analysis.catalog.duplicate_name": "ya hay una categoría «{name}»",
    "analysis.catalog.unknown_kind": "tipo desconocido: {kind}",
    "analysis.catalog.invalid_color": "color inválido (se espera #RRGGBB): {color}",
    "analysis.insights.empty": "el análisis está vacío",
    "analysis.insights.too_long": "el análisis pasa de {max} caracteres ({length})",
    "analysis.insights.invalid_month": "mes inválido '{month}'; use AAAA-MM",
    "analysis.insights.missing": "no hay análisis de {month}",
    "analysis.changelog_rules.role_expense": "gasto compartido",
    "analysis.changelog_rules.role_reimbursement": "reembolso",
    "analysis.changelog_rules.role_leg": "pata de un cambio",
    "analysis.changelog_rules.role_contribution": "aporte",
    "analysis.changelog_rules.role_return": "rendimiento",
    "analysis.changelog_rules.role_capital": "devolución de capital",
    "analysis.changelog_rules.role_mixed": "cobro mixto",
    "analysis.changelog_rules.role_stored": "pasado a tu efectivo",
    "analysis.changelog_rules.role_deposit": "depositado de tu efectivo",
    "analysis.changelog_rules.role_reserved": "cubierto por la reserva",
    "analysis.changelog_rules.link": "vínculo",
    "analysis.changelog_rules.link_shared": "grupo compartido",
    "analysis.changelog_rules.link_exchange": "cambio",
    "analysis.changelog_rules.link_investment": "inversión",
    "analysis.changelog_rules.link_cash_box": "efectivo",
    "analysis.changelog_rules.link_reserve": "reserva",
    "analysis.changelog_rules.entry": "movimiento",
    "analysis.changelog_rules.entry_initial": "saldo inicial",
    "analysis.changelog_rules.entry_income": "entrada",
    "analysis.changelog_rules.entry_expense": "salida",
    "analysis.changelog_rules.mark_none": "sin marca",
    "analysis.changelog_rules.mark_confirmed": "es recurrente",
    "analysis.changelog_rules.mark_dismissed": "no es recurrente",
    "analysis.changelog_rules.mark_cancelled": "cancelada",
    "analysis.changelog_rules.manual_reimbursement": "reembolso a mano {amount}",
    "analysis.changelog_rules.cash_entry": "{kind} {amount} el {day}",
    "analysis.changelog_rules.in_group": "en {group}",
    "analysis.changelog_rules.installments": "{count} cuotas",
    "analysis.changelog_rules.union_separate": "por separado",
    "analysis.changelog_rules.union_with": "con {name}",
    "analysis.changelog_rules.reviewed": "revisado",
    "analysis.changelog_rules.suggestion_dismissed": "sugerencia descartada",
    "analysis.changelog_rules.no_budget": "sin presupuesto",
    "analysis.changelog_rules.cap": "tope RD$ {amount}",
    "analysis.changelog_rules.no_note": "sin nota",
    "analysis.changelog_rules.one_off": "gasto único",
    "analysis.changelog_rules.not_one_off": "no es gasto único",
    "analysis.changelog_rules.automatic_category": "categoría automática",
    "analysis.changelog_rules.category_number": "categoría n.º {id}",
    "analysis.changelog_rules.and_more": "{shown} y {count} más",
    "analysis.changelog.unknown_entry": "entrada desconocida: {id}",
    "analysis.changelog.reason_too_long": "el motivo tiene más de {max} letras",
    "analysis.changelog.blocked": "{reason}; ya no se puede deshacer.",
    "analysis.changelog.blocked_by": "{reason}: primero deshaz la entrada posterior n.º {id}.",
    "analysis.changelog.blocked_by_redo": "{reason}: primero rehaz la entrada posterior n.º {id}.",
    "analysis.changelog.redo_later_first": "Primero rehaz la entrada posterior n.º {id}.",
    "analysis.changelog.member_in_use": (
        "{name} tiene gastos o pagos en el grupo después de este cambio; quitarlo los dejaría "
        "sin persona"
    ),
    "analysis.changelog.someone": "Esa persona",
    "analysis.changelog.parent_link": "El vínculo",
    "analysis.changelog.parent_category": "La categoría",
    "analysis.changelog.parent_row": "La fila madre",
    "analysis.changelog.parent_number": "{label} n.º {id}",
    "analysis.changelog.parent_gone": "{label} al que volvería ya no existe o es otro",
    "analysis.changelog.category_gone": "La categoría de antes ya no existe",
    "analysis.changelog.category_link_only": "«{name}» solo la pone su vínculo: no se pone a mano",
    "analysis.changelog.investment_order": (
        "La inversión quedaría con un cobro del {day} anterior a su primer aporte ({first})"
    ),
    "analysis.changelog.conflict": (
        "Lo de antes choca con algo de ahora (la transacción está en otro vínculo o hay "
        "otra categoría con ese nombre)"
    ),
    "analysis.changelog.would_change_later": (
        "Deshacerla cambiaría también lo de una entrada posterior"
    ),
    "analysis.changelog.busy": "La base está ocupada; reintenta.",
    "analysis.changelog.already_undone": "Ya está deshecha.",
    "analysis.changelog.not_undone": "No está deshecha: no hay nada que rehacer.",
    "analysis.changelog.record_not_undoable": (
        "Es el registro de un «Deshacer»: se deshace o se rehace desde el cambio original."
    ),
    "analysis.changelog.changed_outside": (
        "Cambió después por algo que no queda en la bitácora; ya no se puede deshacer."
    ),
    "analysis.changelog.undo_later_first": "Primero deshaz la entrada posterior n.º {id}.",
    "analysis.changelog.later_uses_before": (
        "Otra entrada posterior usa lo que había antes (por ejemplo, la transacción está "
        "ahora en otro vínculo): deshazla primero."
    ),
    "analysis.changelog.would_change_later_undo": (
        "Deshacerla cambiaría también lo de una entrada posterior: deshaz esa primero."
    ),
    "analysis.changelog.nothing_to_undo": "No había nada que deshacer.",
    # --- end group C ---
    # --- group D: recurring, recurring_marks, recurring_loans, providers, investments, budget,
    # budget_store ---
    # recurring: cadence and screen-group labels, join/separate errors, why a mark is refused.
    "analysis.recurring.cadence.monthly": "mensual",
    "analysis.recurring.cadence.yearly": "anual",
    "analysis.recurring.group.housing": "Vivienda",
    "analysis.recurring.group.loans": "Préstamos",
    "analysis.recurring.group.utilities": "Servicios",
    "analysis.recurring.group.insurance": "Seguros",
    "analysis.recurring.group.subscriptions": "Suscripciones",
    "analysis.recurring.group.fees": "Cargos del banco",
    "analysis.recurring.group.other": "Otros recurrentes",
    "analysis.recurring.unknown": "recurrente desconocido: {series}",
    "analysis.recurring.already_joined": "ya están juntos",
    "analysis.recurring.unknown_merchant": "comercio desconocido: {merchant}",
    "analysis.recurring.already_separate": "ya va por separado",
    "analysis.recurring.mark.not_expense": "Solo un gasto puede ser recurrente.",
    "analysis.recurring.mark.refund": "Una devolución no es un cobro recurrente.",
    "analysis.recurring.mark.top_up": "Las recargas prepago no son recurrentes.",
    "analysis.recurring.mark.store_purchase": (
        "Parece una compra en una tienda del proveedor, no el pago de la factura."
    ),
    # recurring_marks: API errors for a bad mark.
    "analysis.recurring_marks.unknown_status": "estado desconocido: {status}",
    "analysis.recurring_marks.negative_installments": "cuotas restantes negativas: {left}",
    "analysis.recurring_marks.unknown_cadence": "cadencia desconocida: {cadence}",
    "analysis.recurring_marks.unknown_group": "grupo desconocido: {group}",
    "analysis.recurring_marks.unknown_currency": "moneda desconocida: {currency}",
    "analysis.recurring_marks.invalid_merchant": "comercio inválido",
    # budget_store: API errors on the budget caps.
    "analysis.budget_store.already_active": "el presupuesto ya está activo",
    "analysis.budget_store.cap_range": "el tope va de RD$ 0 a RD$ 100,000,000",
    "analysis.budget_store.cap_whole": "el tope va en pesos enteros",
    "analysis.budget_store.no_untouched_cap": "esa categoría no tiene un tope sin tocar",
    # investments: review reasons for a suggested contribution or return.
    "analysis.investments.reason.contribution": "¿Es otro aporte a {title}?",
    "analysis.investments.reason.return": "¿Es un cobro de {title}?",
    # --- end group D ---
    # --- group E: cash_box, cash_box_store, reserves, reserve_store, reserve_suggestions ---
    "analysis.cash_box.description_initial": "Saldo inicial del efectivo",
    "analysis.cash_box.description_income": "Entrada en efectivo",
    "analysis.cash_box.description_expense": "Salida en efectivo",
    "analysis.cash_box.inflow_needs_income": (
        "en tu efectivo, una entrada va a una categoría de ingreso"
    ),
    "analysis.cash_box.outflow_needs_expense": (
        "en tu efectivo, una salida va a una categoría de gasto"
    ),
    "analysis.cash_box.concept_required": "escribe el concepto (en qué fue)",
    "analysis.cash_box.concept_too_long": "el concepto tiene más de {max} letras",
    "analysis.cash_box.concept_invalid": "el concepto tiene caracteres no válidos",
    "analysis.cash_box.count_invalid": (
        "cuánto efectivo tienes: un monto de 0 o más, con hasta dos decimales"
    ),
    "analysis.cash_box.unrecorded_out": "Gastos en efectivo sin anotar",
    "analysis.cash_box.unrecorded_in": "Efectivo sin anotar",
    "analysis.cash_schedule.unknown_kind": "tipo desconocido: {kind} (es pago o cobro)",
    "analysis.cash_schedule.unknown_frequency": "frecuencia desconocida: {frequency}",
    "analysis.cash_schedule.start_range": "el inicio va del {first} al {last}",
    "analysis.cash_schedule.end_or_count": "termina en una fecha o tras unas veces, no las dos",
    "analysis.cash_schedule.end_range": (
        "el final va después del inicio y hasta dentro de diez años"
    ),
    "analysis.cash_schedule.count_range": "las veces van de 1 a {max}",
    "analysis.cash_schedule.unknown": "programación desconocida: {id}",
    "analysis.cash_schedule.kind_fixed": "un pago no se convierte en cobro (ni al revés)",
    "analysis.cash_schedule.not_occurrence": "ese movimiento no viene de una programación",
    "analysis.changelog_rules.cash_schedule": "{kind} programado «{concept}» {amount}",
    "analysis.changelog_rules.cash_schedule_paused": "en pausa",
    "analysis.changelog_rules.cash_schedule_payment": "pago",
    "analysis.changelog_rules.cash_schedule_collection": "cobro",
    "analysis.changelog_rules.cash_skip": "no pasó el {day}",
    "analysis.changelog_rules.cash_spent_direct": "lo gastaste directo",
    "analysis.changelog_rules.cash_reconciliation": "cuadre de {month}",
    "analysis.changelog_rules.cash_pending": "por confirmar",
    "analysis.cash_box.date_range": "la fecha va del {first} al {last}",
    "analysis.cash_box.unknown_kind": "tipo desconocido: {kind}",
    "analysis.cash_box.amount_positive": "el monto tiene que ser mayor que 0",
    "analysis.cash_box.amount_decimals": "el monto tiene más de dos decimales",
    "analysis.cash_box.currency": "la moneda es RD$ o US$",
    "analysis.cash_box_store.unknown_entry": "movimiento de efectivo desconocido: {id}",
    "analysis.cash_box_store.initial_no_category": "el saldo inicial no lleva categoría",
    "analysis.cash_box_store.category_must_be_income": "la categoría tiene que ser de ingreso",
    "analysis.cash_box_store.category_must_be_expense": "la categoría tiene que ser de gasto",
    "analysis.cash_box_store.amount_needs_currency": (
        "el monto que salió de tu efectivo va con su moneda"
    ),
    "analysis.cash_box_store.not_stored": "esa transacción no es un retiro pasado a tu efectivo",
    "analysis.cash_box_store.not_deposit": "esa transacción no es un depósito de tu efectivo",
    "analysis.reserves.month_01": "enero",
    "analysis.reserves.month_02": "febrero",
    "analysis.reserves.month_03": "marzo",
    "analysis.reserves.month_04": "abril",
    "analysis.reserves.month_05": "mayo",
    "analysis.reserves.month_06": "junio",
    "analysis.reserves.month_07": "julio",
    "analysis.reserves.month_08": "agosto",
    "analysis.reserves.month_09": "septiembre",
    "analysis.reserves.month_10": "octubre",
    "analysis.reserves.month_11": "noviembre",
    "analysis.reserves.month_12": "diciembre",
    "analysis.reserves.due_format": "el vencimiento va como AAAA-MM",
    "analysis.reserves.due_month_range": "el mes del vencimiento va de 01 a 12",
    "analysis.reserve_store.default_name": "Reserva n.º {id}",
    "analysis.reserve_store.unknown": "reserva desconocida: {id}",
    "analysis.reserve_store.name_required": "la reserva necesita un nombre",
    "analysis.reserve_store.name_too_long": "el nombre tiene más de {max} letras",
    "analysis.reserve_store.amount_range": "el monto va de RD$ 1 a RD$ 100,000,000",
    "analysis.reserve_store.every_choices": "se repite cada año, cada 6 meses o una sola vez",
    "analysis.reserve_store.unknown_category": "categoría desconocida",
    "analysis.reserve_store.expense_category": "una reserva es de una categoría de gasto",
    "analysis.reserve_store.not_member": "ese gasto no es de la reserva",
    "analysis.reserve_store.invalid_key": "clave de sugerencia inválida",
    "analysis.reserve_suggestions.yearly_recurring": "Recurrente anual: se cobra en {month}",
    "analysis.reserve_suggestions.irregular_one_year": (
        "Gasto irregular: ≈ RD$ {amount}/año (promedio de {years} año); más en {month}"
    ),
    "analysis.reserve_suggestions.irregular_years": (
        "Gasto irregular: ≈ RD$ {amount}/año (promedio de {years} años); más en {month}"
    ),
    "analysis.reserve_suggestions.peak_name": "{month}: {category}",
    "analysis.reserve_suggestions.peak": "Pico en {month} en {count} años ({years})",
    # --- end group E ---
}
