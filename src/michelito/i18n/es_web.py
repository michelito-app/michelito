"""Spanish text of the board API (`michelito.web`): `detail` messages, skip reasons, labels and
change-log text the routes return to the UI."""

MESSAGES: dict[str, str] = {
    # Card billing (`web.billing_routes`).
    "web.billing.unknown_account": "esa cuenta no existe",
    "web.billing.not_a_card": "la facturación solo se mide en tarjetas de crédito",
    "web.billing.no_statements": "esa tarjeta no tiene estados",
    "web.billing.range": "el mes inicial va después del final",
    "web.transactions.month_or_range": "usa un mes o un rango, no los dos",
    "web.transactions.range": "el mes inicial va después del final",
    "web.range_too_long": "el rango no puede pasar de {months} meses",
    # Installment plans (`web.installment_routes`).
    "web.tags.unknown": "esa etiqueta no existe",
    "web.tags.unknown_target": "ese préstamo o plan de cuotas no existe",
    "web.tags.derived": "esa transacción viene de su grupo, préstamo o plan: quítala desde ahí",
    "web.loans.unknown": "ese préstamo no existe",
    "web.loans.none": "sin préstamo",
    "web.loans.log_payment": "pago del préstamo {name}",
    "web.installments.unknown": "ese plan de cuotas no existe",
    "web.installments.not_a_charge": "solo un cargo de tarjeta puede ser una cuota",
    "web.installments.number_over_count": "la cuota no puede pasar del total de cuotas",
    "web.installments.none": "sin plan de cuotas",
    "web.installments.log_plan": "plan de cuotas {name}",
    "web.installments.log_number": "cuota {number} de {name}",
    "web.review.loan_payments": (
        "{name}: el estado del préstamo dice que se pagó {expected} este mes "
        "y los pagos enlazados suman {found}"
    ),
    "web.review.loan_contract": (
        "{name}: el estado del préstamo deja un balance de {found} "
        "y el contrato esperaba {expected}"
    ),
    "web.review.installment_amount": "{name}: la cuota {number} llegó por otro monto",
    "web.review.installment_repeated": "{name}: hay más de un cargo para la cuota {number}",
    "web.review.installment_after_end": "{name}: llegó un cargo después de la última cuota",
    "web.review.installment_refund": "{name}: el comercio devolvió dinero en esta tarjeta",
    # Shared by several routes.
    "web.unknown_transaction": "transacción desconocida",
    "web.proposals.unknown": "esa propuesta no existe",
    "web.proposals.answered": "esa propuesta ya se respondió",
    "web.proposals.unknown_item": "un cambio no es de esta propuesta",
    "web.proposals.failed": "no se pudo aplicar",
    "web.proposals.duplicate_statement": "ese estado ya estaba guardado",
    "web.already_linked": "la transacción ya está en otro vínculo",
    "web.no_data": "mes sin datos",
    "web.unknown_transaction_fingerprint": "transacción desconocida: {fingerprint}",
    "web.month_without_movements": "mes sin movimientos: {month}",
    "web.unknown_category": "categoría desconocida",
    "web.to_review": "por revisar",
    "web.deleted": "borrada",
    "web.not_found": "no existe",
    # Request guards (`web.app`).
    "web.no_session": "no hay sesión de la demo: recarga la página",
    "web.missing_header": "falta la cabecera {header}",
    "web.unknown_author": "autor desconocido",
    "web.author_not_accepted": "autor no aceptado en modo {mode}",
    "web.unavailable_in_mode": "no disponible en modo {mode}",
    "web.missing_content_length": "falta Content-Length",
    "web.body_too_large": "el cuerpo es demasiado grande",
    "web.unknown_accounts": "cuentas desconocidas: {keys}",
    # Transactions, shared groups and exchanges (`web.app`).
    "web.cash_box_self_only": "un movimiento de tu efectivo se corrige solo a sí mismo",
    "web.expense_in_other_group": "el gasto ya está en otro grupo: quítalo de ese primero",
    "web.unknown_group": "grupo desconocido",
    "web.credit_or_manual": "manda un crédito (`credit`) o uno a mano (`manual`)",
    "web.group_without_expenses": "el grupo no tiene gastos presentes",
    "web.refund_before_expense": "el reembolso no puede ser antes del gasto",
    "web.not_a_reimbursement": "ese crédito no es un reembolso",
    "web.expense_not_in_group": "ese gasto no está en el grupo",
    "web.unknown_exchange": "cambio desconocido",
    "web.not_a_leg": "esa transacción no es una pata del cambio",
    "web.not_one_off": "no es único",
    # Categories and rates (`web.app`).
    "web.deleted_moved_to": "borrada (pasa a {name})",
    "web.rate_not_positive": "la tasa debe ser mayor que cero",
    # Month names, January first: `web.summary.month_label` capitalizes them ("Enero 2025") and
    # the trend chart uses their first three letters ("ene").
    "web.summary.month_01": "enero",
    "web.summary.month_02": "febrero",
    "web.summary.month_03": "marzo",
    "web.summary.month_04": "abril",
    "web.summary.month_05": "mayo",
    "web.summary.month_06": "junio",
    "web.summary.month_07": "julio",
    "web.summary.month_08": "agosto",
    "web.summary.month_09": "septiembre",
    "web.summary.month_10": "octubre",
    "web.summary.month_11": "noviembre",
    "web.summary.month_12": "diciembre",
    # Link checks (`web.links`).
    "web.link.only_expense_shared": "solo un gasto (monto positivo) se puede compartir",
    "web.link.credit_already_linked": "ese crédito ya está enlazado",
    "web.link.not_shared": "el gasto no está marcado como compartido",
    "web.link.only_credit_reimburses": "solo un crédito puede ser un reembolso",
    "web.link.missing_rate": (
        "falta la tasa de cambio de ese mes para pasar el crédito a la moneda del gasto"
    ),
    "web.link.credit_not_eligible": "ese crédito no puede ser un reembolso",
    "web.link.unknown_group": "grupo desconocido: {link_id}",
    "web.link.leg_already_linked": "una de las transacciones ya está en otro vínculo",
    "web.link.leg_not_bank": "las patas de un cambio son de cuentas bancarias",
    "web.link.leg_not_eligible": (
        "salario, pagos de tarjeta, envíos entre tus cuentas o algo ya enlazado no pueden ser "
        "una pata"
    ),
    # Batch category edit (`web.batch_edit`, `web.batch_routes`).
    "web.batch.skip.linked": "está en un vínculo que fija su categoría",
    "web.batch.skip.cash_box": (
        "es de tu efectivo: una entrada va a un ingreso y una salida a un gasto"
    ),
    "web.batch.skip.direction": "es un débito: no puede ser ingreso",
    "web.batch.skip.unchanged": "ya estaba en esa categoría",
    "web.batch.skip.unknown": "no existe",
    "web.batch.one_transaction": "1 transacción",
    "web.batch.transactions": "{count} transacciones",
    "web.batch.several_categories": "varias categorías",
    # Review (`web.review`, `web.review_routes`).
    "web.review.rule_reason": "{merchant}: lo pusiste {count} veces en {category}. ¿Siempre?",
    "web.review.reserve_reason": "¿Es de la reserva «{name}»? Vence en {month} {year}",
    "web.review.no_rule": "no hay una regla propuesta para ese comercio",
    "web.review.reviewed": "revisado",
    "web.review.rule_proposed": "regla propuesta",
    "web.review.rule_discarded": "descartada",
    "web.review.rule_allowed": "se puede proponer",
    "web.review.unconfirmed_reason": "No apareció en tu estado de {month}. ¿Se reversó?",
    "web.review.receipt_reason": "¿Es este el cargo de tu pedido {order} de {merchant}?",
    "web.receipt.unknown": "ese recibo no existe",
    "web.receipt.not_proposed": "ese recibo no se propuso para esta transacción",
    "web.receipt.none": "sin recibo",
    "web.provisional.discarded": "descartado",
    "web.provisional.kept": "mantenido sin estado",
    "web.provisional.pending": "pendiente de estado",
    "web.provisional.voided": "anulado por una alerta de reverso",
    "web.provisional.unknown": "no es una transacción pendiente de estado",
    "web.provisional.linked": "Quítala del grupo primero",
    "web.provisional.in_cash": "Está en tu efectivo: toca «Lo gasté directo» primero",
    "web.review.reversal_linked": (
        "El banco avisó un reverso de esta compra. Quítala del grupo y descártala, o mantenla."
    ),
    "web.review.reversal_charged": (
        "El banco avisó un reverso, pero tu estado trae el cargo. Revísalo con el banco."
    ),
    # Saved insights (`web.insight_routes`).
    "web.insight.accounts_mismatch": (
        "las cuentas no son las del dossier que se copió; vuelve a copiarlo"
    ),
    "web.insight.not_found": "no hay análisis de ese mes",
    # Dossier (`web.dossier_routes`).
    "web.dossier.account_key_too_long": "clave de cuenta de más de {max} caracteres",
    # Budget (`web.budget_routes`).
    "web.budget.subject": "Presupuesto",
    "web.budget.inactive": "sin activar",
    "web.budget.activated": "{count} categorías, {with_cap} con tope",
    "web.budget.expense_only": "solo una categoría de gasto lleva tope",
    "web.budget.not_active": "el presupuesto no está activo: actívalo primero",
    "web.budget.no_warning": "no hay aviso de lo habitual para esa categoría",
    "web.budget.kept": "se queda {cap}",
    "web.budget.usual_changed": "lo habitual pasó de RD$ {basis:,} a RD$ {usual:,}",
    # Recurring (`web.recurring`, `web.recurring_routes`).
    "web.recurring.installments_group": "Cuotas",
    "web.recurring.alert_new": "Nuevo: {cost} al mes",
    "web.recurring.alert_price_up": "Subió de {before} a {after}",
    "web.recurring.alert_charged_after_cancel": "Cobró {amount} después de cancelarlo",
    "web.recurring.separated": "{merchant} · fuera de {series}",
    # Reserves (`web.reserve_routes`).
    "web.reserve.skip.linked": "ya está en un vínculo (otra reserva, un grupo, una inversión…)",
    "web.reserve.skip.not_expense": "no es un gasto",
    "web.reserve.skip.unknown": "no existe",
    "web.reserve.plan.amount": "RD$ {amount:,}",
    "web.reserve.plan.once": "una vez, en {month}",
    "web.reserve.plan.yearly": "cada año en {month}",
    "web.reserve.plan.every": "cada {months} meses desde {month}",
    "web.reserve.plan.text": "{amount} · {when}",
    "web.reserve.plan.multiple": " · varios gastos",
    "web.reserve.unknown": "reserva desconocida",
    "web.reserve.covered_by": "cubierto por «{name}»",
    "web.reserve.batch_before": "{count} gastos sin reserva",
    "web.reserve.batch_after": "{count} gastos cubiertos por «{name}»",
    "web.reserve.back_to_cap": "vuelve al tope",
    "web.reserve.suggested": "sugerida",
    "web.reserve.dismissed": "descartada",
    # Shared by the cash box and investment routes.
    # Cash box (`/api/cash-box`).
    "web.cash.unknown_entry": "movimiento desconocido",
    "web.cash.initial_no_repeat": "el saldo inicial no se repite",
    "web.cash.box_name": "Efectivo",
    "web.cash.from_box": "Vino de tu efectivo",
    "web.cash.only_withdrawal": (
        "solo un retiro de cajero (un débito de la categoría «Efectivo») pasa a tu efectivo"
    ),
    "web.cash.only_bank_credit": (
        "solo un crédito de una cuenta bancaria (que no sea salario, pago de "
        "tarjeta ni envío entre tus cuentas) puede venir de tu efectivo"
    ),
    "web.cash.same_currency_amount": (
        "en la misma moneda sale de tu efectivo lo mismo que el depósito"
    ),
    # Investments (`/api/investments`).
    "web.investment.unknown": "inversión desconocida",
    "web.investment.unknown_id": "inversión desconocida: {investment_id}",
    "web.investment.only_bank_debit": "solo un débito de una cuenta bancaria puede ser un aporte",
    "web.investment.only_bank_credit": "solo un crédito de una cuenta bancaria puede ser un cobro",
    "web.investment.return_before_first": (
        "un cobro no puede ser anterior al primer aporte ({first})"
    ),
    "web.investment.kind_values": "kind es «contribution» o «credit»",
    "web.investment.capital_only_if_mixed": (
        "un crédito mixto lleva la parte de capital; los demás, no"
    ),
    "web.category.unknown": "categoría desconocida: {ref}",
    # Reports (`web.reports`).
    "web.report.reversed_range": "el mes «desde» va después del mes «hasta»",
    "web.report.too_many_months": "a lo sumo {max} meses",
    "web.report.income": "Ingresos",
    "web.report.expenses": "Gastos",
    "web.report.third_party": "Transferencias a terceros",
    "web.report.net": "Te quedó",
    # Change-log text of transaction edits (`web.edit_log`).
    "web.log.yes": "sí",
    "web.log.no": "no",
    "web.log.link": "Vínculo",
    "web.log.link_number": "{label} n.º {id}",
    "web.log.group": "Grupo",
    "web.log.exchange": "Cambio",
    "web.log.investment": "Inversión",
    "web.log.reserve": "Reserva",
    "web.log.no_rule": "sin regla",
    "web.log.unknown_entry": "entrada desconocida",
    # Transactions (`web.transactions`, `web.log_routes`).
    "web.tx.unknown_scope": "alcance desconocido: {scope}",
    # Accounts: the payment warning (`web.accounts.due_text`).
    "web.account.due": "{label}: paga {amounts} antes del {day} {month} para no pagar intereses",
    "web.account.and": " y ",
    "web.account.month_01": "ene",
    "web.account.month_02": "feb",
    "web.account.month_03": "mar",
    "web.account.month_04": "abr",
    "web.account.month_05": "may",
    "web.account.month_06": "jun",
    "web.account.month_07": "jul",
    "web.account.month_08": "ago",
    "web.account.month_09": "sep",
    "web.account.month_10": "oct",
    "web.account.month_11": "nov",
    "web.account.month_12": "dic",
}
