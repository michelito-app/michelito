"""Spanish text of the import pipeline (`michelito.extract`, `michelito.ingest`,
`michelito.parsers.common`): the status details stored in `documents.detail` and
`document_parts.note`, which the import screens (and the demo's sample statement) show."""

MESSAGES: dict[str, str] = {
    # Gmail attachments (`extract`).
    "core.extract.too_large": "adjunto de {megabytes} MB supera el límite; no se descargó",
    "core.extract.same_file": "mismo archivo que otro documento ya guardado",
    "core.extract.no_parser_format": "formato sin parser en la fase 1",
    # Parsing and storing (`ingest`).
    "core.ingest.archived_source": "fuente sin parser en la fase 1",
    "core.ingest.unreadable_pdf": "no se pudo leer el PDF: {error}",
    "core.ingest.detect_failed": "al reconocer el formato: {error}",
    "core.ingest.unsupported": "ningún parser reconoce el formato",
    # A retry of a document that already has statements: the earlier detail, then this.
    "core.ingest.retry_separator": "; reintento: ",
    "core.ingest.retry": "{previous}; reintento: {status}: {reason}",
    "core.ingest.part_label": "estado {number}",
    "core.ingest.already_stored": "ya guardado",
    "core.ingest.duplicate_period": "ya existe un estado para ese corte",
    "core.ingest.duplicate_printout": "ya existe una impresión igual",
    "core.ingest.stored": "{count} transacciones",
    "core.ingest.no_statement": "no se encontró ningún estado en el documento",
    "core.ingest.parts_stored": "{parsed} de {total} estados guardados ({count} transacciones)",
    "core.ingest.parts_repeated": "repetidos: {labels}",
    "core.ingest.part_note": "{label} nota: {note}",
    # The name given to a category whose stored name was empty (`db` migration of schema 8).
    "core.db.no_name": "Sin nombre",
    # Validation against the printed totals (`parsers.common`).
    "core.validation.no_sections": "el estado no tiene secciones",
    "core.validation.debits": "débitos",
    "core.validation.credits": "créditos",
    "core.validation.count_note": "{currency}: {label}: {rows} filas ≠ {count} impresas",
    "core.validation.total_mismatch": "{currency}: {label} leídos {read} ≠ impresos {printed}",
    "core.validation.balance_mismatch": (
        "{currency}: balance anterior {previous} con movimientos da {expected} ≠ balance al "
        "corte {closing}"
    ),
    "core.validation.no_totals": "{currency}: no hay totales impresos para validar",
    "core.validation.chain_mismatch": (
        "{currency}: la fila {index} ({day}) imprime balance {balance}, pero el anterior con su "
        "monto da {running}"
    ),
}
