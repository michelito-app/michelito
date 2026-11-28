"""Estados sintéticos: misma estructura que los reales, contenido inventado.

Ningún dato aquí corresponde a una cuenta real.
"""

from decimal import Decimal

from michelito.parsers.common import Page
from tests.layout import block, page, placed, row

POPULAR_DOP = page(
    *block("""
                                                         ESTADO DE CUENTA
                             LÍNEA DE CRÉDITO                  FECHA LÍMITE BALANCE
    VISA PRESTIGE DOP                              FECHA DE CORTE
                             CRÉDITO  DISPONIBLE               DE PAGO     ANTERIOR
    ****-****-****-1234    100,000.00 90,000.00    13/01/2026 07/02/2026 5,000.00
      FECHAS DE NO. DE REFERENCIA  CARGOS,PAGOS, CRÉDITOSY AJUSTES ANTERIORES CANTIDAD
    ENTRADA TRANSAC.
    15/12  14/12 11111111111111111111111 COLMADO INVENTADO SANTO DOMINGO   1,200.50
                                       5411 000001
    02/01  01/01 22222222222222222222222 CAFE FICTICIO SANTO DOMINGO         300.00
                                       5814 000002
    05/01  05/01 33333333333333333333333 SU PAGO GRACIAS                  -5,000.00
                          UNA CANTIDAD CON EL SIGNO (-) DE MENOS ES UN CRÉDITO.
      CUOTAS
                     MONTO VENCIDO     PAGO MÍNIMO    BALANCE A PAGAR  BALANCE TOTAL
      VENCIDAS
      0                0.00            150.00        1,500.50         1,500.50
                                                                     Página: 1 / 2
""")
)

POPULAR_DOP_WRONG_TOTAL = page(
    *block("""
    VISA PRESTIGE DOP                              FECHA DE CORTE
    ****-****-****-1234    100,000.00 90,000.00    13/01/2026 07/02/2026 5,000.00
    15/12  14/12 11111111111111111111111 COLMADO INVENTADO SANTO DOMINGO   1,200.50
      0                0.00            150.00        1,600.50         1,600.50
""")
)

POPULAR_USD = page(
    *block("""
                                                         ESTADO DE CUENTA
    VISA PRESTIGE USD                              FECHA DE CORTE
    ****-****-****-1234      2,000.00  1,975.00    13/01/2026 07/02/2026 0.00
    20/12  18/12 44444444444444444444444 TIENDA ONLINE SEATTLE              25.00
                                       5942 000003
      0                0.00             25.00           25.00            25.00
                                                                     Página: 2 / 2
""")
)

# Formato 2020-2025: el pie no tiene etiquetas y va repartido en varias líneas.
POPULAR_DOP_SPLIT_FOOTER = page(
    *block("""
    VISA PRESTIGE DOP
    ****-****-****-1234    100,000.00 90,000.00    13/01/2025 07/02/2025 5,000.00
    15/12  14/12 11111111111111111111111 COLMADO INVENTADO SANTO DOMINGO   1,200.50
                                       5411 000001
    05/01  05/01 33333333333333333333333 SU PAGO GRACIAS                  -5,000.00
                                                                150.00   1,200.50
       0     0.00        1,200.50
                                                                  0.00       0.00
                                                                150.00   1,200.50
                                                                     Página: 1 / 1
""")
)

# Formato de inicios de 2024: una línea con cuatro valores (sin "balance a pagar").
POPULAR_DOP_FOUR_VALUE_FOOTER = page(
    *block("""
    VISA PRESTIGE DOP
    ****-****-****-1234    100,000.00 90,000.00    13/01/2024 07/02/2024 5,000.00
    15/12  14/12 11111111111111111111111 COLMADO INVENTADO SANTO DOMINGO   1,200.50
    05/01  05/01 33333333333333333333333 SU PAGO GRACIAS                  -5,000.00
       0     0.00        150.00       1,200.50
""")
)

POPULAR_TERMS = page(
    *block("""
    TÉRMINOS Y CONDICIONES
    Texto legal inventado sin datos de ninguna cuenta.
""")
)

BHD_TC_SUMMARY = page(
    *block("""
    ESTADO DE CUENTA DE: TARJETA DE CRÉDITO
                                              Tipo de tarjeta MC BLACK
    FULANO DE TAL
                                              Número de tarjeta 510041******9999
    correo@ejemplo.com
                                              Límite de crédito RD$ 100,000.00 y US$ 2,000.00
    CALLE INVENTADA 1
                                              Fecha de corte Fecha límite de pago
    CIUDAD INVENTADA                          26/01/2026    20/02/2026
    Este es el resumen de tu corte a la fecha:
                         PESOS          DÓLARES
    Balance anterior   1,000.00          10.00
    Pagos y créditos   1,000.00          10.00
    Compras y débitos  2,500.00          30.00
    Balance al corte   2,500.00          30.00
    Este es el resumen de tu línea de crédito cuotas BHD:
    Balance anterior       0.00
    Este es tu pago mínimo:
    Pago mínimo total    125.00           5.00
""")
)

BHD_TC_MOVEMENTS = page(
    row("Fecha Fecha No. de Tarjeta Concepto", "Débitos", "Créditos"),
    "TRANSACCIONES EN PESOS RD$",
    row("28/12 29/12 9999 SUPERMERCADO FICTICIO SANTO DOMINGO-DO", "2,000.00"),
    row("10/01 11/01 9999 FARMACIA INVENTADA SANTO DOMINGO-DO", "500.00"),
    row("19/01 19/01 PAGO DEBITO A CUENTA MBP", "", "1,000.00"),
    row("** TOTAL TRANSACCIONES EN RD$ PESOS **", "2,500.00", "1,000.00"),
    "TRANSACCIONES EN DOLARES US$",
    row("05/01 06/01 9999 TIENDA ONLINE SEATTLE-US", "30.00"),
    "<CONTINUA>",
)

# En algunos estados el título "TRANSACCIONES EN DÓLARES" se imprime encima de
# "<CONTINUA>" y el texto extraído sale mezclado.
BHD_TC_MOVEMENTS_GARBLED = page(
    row("Fecha Fecha No. de Tarjeta Concepto", "Débitos", "Créditos"),
    "TRANSACCIONES EN PESOS RD$",
    row("28/12 29/12 9999 SUPERMERCADO FICTICIO SANTO DOMINGO-DO", "2,000.00"),
    row("10/01 11/01 9999 FARMACIA INVENTADA SANTO DOMINGO-DO", "500.00"),
    row("19/01 19/01 66666666666666666666666 DEVOLUCION", "", "1,000.00"),
    row("** TOTAL TRANSACCIONES EN RD$ PESOS **", "2,500.00", "1,000.00"),
    "                 DO<LCAORNETSI NUUS$A>",
    "TRANSACCIONES EN",
)

BHD_TC_CONTINUED_USD_ONLY = page(
    row("Fecha Fecha No. de Tarjeta Concepto", "Débitos", "Créditos"),
    row("05/01 06/01 9999 TIENDA ONLINE SEATTLE-US", "30.00"),
    row("15/01 15/01 PAGO DEBITO A CUENTA MBP", "", "10.00"),
    row("** TOTAL TRANSACCIONES EN US$ DOLAR **", "30.00", "10.00"),
    row("Estrellas Gan. Del Mes", "-2.00"),
)

BHD_TC_CONTINUED = page(
    row("Fecha Fecha No. de Tarjeta Concepto", "Débitos", "Créditos"),
    row("15/01 15/01 PAGO DEBITO A CUENTA MBP", "", "10.00"),
    row("** TOTAL TRANSACCIONES EN US$ DOLARES **", "30.00", "10.00"),
    "PESOS 0.00 0.00 125.00 0.00 125.00 2,500.00 0.00 2,500.00",
)

BHD_AHORRO = page(
    *block("""
                                               Número de cuenta
                                               XXXXXXX-999-1
                                               Número de cuenta regional
                                               DO00BCBH000000000XXXXXXX9991
        FULANO DE TAL
                                               Moneda
        CALLE INVENTADA 1
                                                RD$
        BARRIO INVENTADO
        SANTO DOMINGO                          Fecha de corte
                                               2026-01-31
        correo@ejemplo.com
                                               Balance inicial
                                                10,000.00
                                       Escanéame para validar
                                               Cheques en tránsito
    """),
    row("Fecha Ref. Detalles", "Débitos", "Créditos", "Balance"),
    row("05/01 1234567890 TRANSFERENCIA RECIBIDA", "", "5,000.00", "15,000.00"),
    row("10/01 PAGO DE TC 5100 XXXX XXXX 9999", "3,000.00", "", "12,000.00"),
    row("31/01 PAGO INTERESES CA", "", "0.50", "12,000.50"),
    "0.00CKS    1DEBITOS    3,000.00",
    "           2CREDITOS              5,000.50",
)

# Formato 2025: etiquetas en mayúscula inicial, sin "Moneda", con "Balance Final"
# impreso y un fragmento suelto "Fecha de" entre la etiqueta y su valor.
BHD_AHORRO_2025_ROWS = (
    *block("""
                                               Número de Cuenta
                                                XXXXXXX-999-1
                                             Número de Cuenta Regional
        FULANO DE TAL                      DO00BCBH000000000XXXXXXX9991
        CALLE INVENTADA 1 BARRIO           Fecha de Corte
                                                Fecha de
        SANTO DOMINGO ESTE                     2025-05-31
                                               Balance Inicial
        REPUBLICA DOMINICANA
                                                10,000.00
                                             Cheques en Tránsito
        correo@ejemplo.com
                                                  0.00
                                               Balance Final
                                                12,000.50
    """),
    row("Fecha Ref. Detalle", "Débitos", "Créditos", "Balance"),
    row("05/05 1234567890 TRANSFERENCIA RECIBIDA", "", "5,000.00", "15,000.00"),
    row("10/05 PAGO DE TC 5100 XXXX XXXX 9999", "3,000.00", "", "12,000.00"),
    row("30/05 PAGO INTERESES CA", "", "0.50", "12,000.50"),
    "0.00CKS    1DEBITOS    3,000.00",
    "           2CREDITOS              5,000.50",
)
BHD_AHORRO_2025 = page(*BHD_AHORRO_2025_ROWS)

# El mismo estado de enero 2026 bajado del portal de BHD: fechas completas (dd/mm/aaaa),
# referencia de siete dígitos, "0.00" en la columna que no aplica, una línea de
# "Balance anterior" antes de las filas y espacios en los totales ("1 DEBITOS").
BHD_AHORRO_PORTAL_ROWS = (
    *block("""
                                BANCO INVENTADO S.A. RNC 9-99-99999-9
                                     TEL. (999) 999-9999 . WEB: ejemplo.com
                                               Número de cuenta
                                                XXXXXXX-999-1
                                             Número de cuenta regional
                                             DO00BCBH000000000XXXXXXX9991
        FULANO DE TAL
                                                  Moneda
        CALLE INVENTADA 1
                                                   RD$
        BARRIO INVENTADO                        Fecha de corte
                                                 31/01/2026
        SANTO DOMINGO                           Balance inicial
                                                 10,000.00
                                               Cheques en tránsito
                                                   0.00
                                                Balance final
                                                 12,000.50
                                  Estado de cuenta
    """),
    row("Fecha Ref. Detalles", "Débitos", "Créditos", "Balance"),
    "                              Balance anterior: 31/12/2025 10,000.00",
    row("05/01/2026 1234567 TRANSFERENCIA RECIBIDA", "0.00", "5,000.00", "15,000.00"),
    row("10/01/2026 7654321 PAGO DE TC 5100 XXXX XXXX 9999", "3,000.00", "0.00", "12,000.00"),
    row("31/01/2026 PAGO INTERESES CA", "0.00", "0.50", "12,000.50"),
    "                        0 CKS          1 DEBITOS            3,000.00",
    "                                       2 CREDITOS                       5,000.50",
)
BHD_AHORRO_PORTAL = page(*BHD_AHORRO_PORTAL_ROWS)


_PORTAL_TABLE = row("Fecha Ref. Detalles", "Débitos", "Créditos", "Balance")


def bhd_ahorro_portal_partial(
    *,
    opening: str = "10,000.00",
    opening_line: str = "Balance inicial: 01/01/2026",
    final: str = "0.00",
    balances: tuple[str, str] = ("15,000.00", "12,000.00"),
) -> tuple:
    """Enero 2026 bajado del portal el día 12, antes del corte del 31: "Balance final" en
    0.00, filas hasta el 10 y el balance del inicio del mes como primera línea de la tabla."""
    header = BHD_AHORRO_PORTAL_ROWS[: BHD_AHORRO_PORTAL_ROWS.index(_PORTAL_TABLE)]
    values = {"12,000.50": final, "10,000.00": opening}
    rows = (
        *(
            values.get(line.strip(), line.strip()).rjust(len(line))
            if line.strip() in values
            else line
            for line in header
        ),
        _PORTAL_TABLE,
        f"{' ' * 30}{opening_line} {opening}",
        row("05/01/2026 1234567 TRANSFERENCIA RECIBIDA", "0.00", "5,000.00", balances[0]),
        row("10/01/2026 7654321 PAGO DE TC 5100 XXXX XXXX 9999", "3,000.00", "0.00", balances[1]),
        "                        0 CKS          1 DEBITOS            3,000.00",
        "                                       1 CREDITOS                       5,000.00",
    )
    return (page(*rows),)


BHD_AHORRO_PORTAL_PARTIAL_PAGES = bhd_ahorro_portal_partial()

# Estado de cuenta corriente del Popular (formato actual): resumen con totales impresos y
# movimientos con dos fechas "DDMMM" (a veces con el mes en inglés), monto con signo
# (débito negativo) y balance. El detalle puede seguir en las líneas de abajo.
POPULAR_CUENTA_ROWS_1 = block("""
                                                                         Pag 1
                                                           15 de enero de 2026
    FULANO DE TAL
    correo@ejemplo.com
                     INFORMACIÓN SOBRE SU ESTADO DE CUENTA
    CTA CTE PERSONAL INVENTADA  123456789
     NÚMERO DE CUENTA REGIONAL  DO00BPDO00000000000123456789
                                          CANTIDAD      MONTO RD$
    BALANCE ANTERIOR                                    10,000.00
    + DEPÓSITOS Y OTROS CRÉDITOS              2         60,000.00
    - CHEQUES Y OTRO DÉBITOS                  3          5,001.50
    + INTERÉS PAGADO                                         0.00
    - INTERÉS CARGADO                                        0.00
    BALANCE AL CORTE                                    64,998.50
       FECHAS DE
                 No. DE CHEQUE DETALLE                DÉBITO RD$ CRÉDITO RD$ BALANCE RD$
    ENTRADA TRANSAC.
    15DEC       BALANCE ANTERIOR                                              10,000.00
    20DIC 20DIC PAGO DE NOMINA EMPRESA FICTICIA RD$ .00          50,000.00    60,000.00
    22DIC 21DIC MB a 0000000001 PERSONA INVENTADA     -1,000.00               59,000.00
    02ENE 02ENE PAGO IMPUESTO 0.15% DGII, 1 TRANS POR $ 1,000.00 Del -1.50    58,998.50
                26/12/2025 Al 01/01/2026

    Pie de página inventado
    texto promocional inventado.                                 60,000.00
    LINEA DE AYUDA INVENTADA: 000-000-0000
""")
POPULAR_CUENTA_ROWS_2 = block("""
                                                                         Pag 2
                                                           15 de enero de 2026
    FULANO DE TAL
                              SU ESTADO DE CUENTA
       FECHAS DE
                 No. DE CHEQUE DETALLE                DÉBITO RD$ CRÉDITO RD$ BALANCE RD$
    ENTRADA TRANSAC.
    08ENE 08ENE LBTR/IB/ VIA LBTR 0000000002, FULANO DE TAL  -4,000.00        54,998.50
                BANCO INVENTADO S.A. CAS0000000001
    12ENE 11ENE MB desde 000000003 FULANO DE                     10,000.00    64,998.50
    15ENE BALANCE AL CORTE                                                    64,998.50
    LINEA DE AYUDA INVENTADA: 000-000-0000
""")
POPULAR_CUENTA_DOP = (page(*POPULAR_CUENTA_ROWS_1), page(*POPULAR_CUENTA_ROWS_2))

# Cuenta de ahorro en dólares con interés pagado: el interés va aparte de los depósitos
# en el resumen, pero aparece como un movimiento de crédito.
POPULAR_CUENTA_USD = (
    page(
        *block("""
                                                                         Pag 1
                                                          31 de octubre de 2026
    FULANO DE TAL
                     INFORMACIÓN SOBRE SU ESTADO DE CUENTA
    CTA AHO DOLARES INVENTADA  987654321
     NÚMERO DE CUENTA REGIONAL  DO00BPDO00000000000987654321
                                          CANTIDAD      MONTO US$
    BALANCE ANTERIOR                                     1,000.00
    + DEPÓSITOS Y OTROS CRÉDITOS              1            500.00
    - CHEQUES Y OTRO DÉBITOS                  1            200.00
    + INTERÉS PAGADO                                         0.25
    - INTERÉS CARGADO                                        0.00
    BALANCE AL CORTE                                     1,300.25
       FECHAS DE
                 No. DE CHEQUE DETALLE                DÉBITO US$ CRÉDITO US$ BALANCE US$
    ENTRADA TRANSAC.
    30SEP       BALANCE ANTERIOR                                               1,000.00
    05OCT 05OCT TRANSFERENCIA RECIBIDA DEL EXTERIOR                 500.00     1,500.00
    20OCT 20OCT TRANSFERENCIA A CUENTA PROPIA        -200.00                   1,300.00
    31OCT 31OCT INTERESES GANADOS                                     0.25     1,300.25
    31OCT BALANCE AL CORTE                                                     1,300.25
""")
    ),
)

# El mismo estado con un balance al corte que no cuadra con los movimientos.
POPULAR_CUENTA_WRONG_CLOSING = (
    page(
        *(
            r.replace("64,998.50", "65,998.50") if r.startswith("BALANCE AL CORTE") else r
            for r in POPULAR_CUENTA_ROWS_1
        )
    ),
    page(*POPULAR_CUENTA_ROWS_2),
)

# Impresión de "Transacciones" en Popularenlinea (Chrome → Guardar como PDF). Sin resumen:
# cada fila trae fecha de posteo y efectiva, número de cheque y de referencia (a veces
# vacíos), descripción, monto ("-" al final si es débito) y balance. Una descripción larga
# se reparte en renglones encima y debajo de la fila, centrada en ella.
# Cada fila: (posteo, efectiva, cheque, referencia, renglones de descripción, monto, balance).
WebRow = tuple[str, str, str | None, str | None, tuple[str, ...], str, str]

_WEB_COLUMNS = {"posteo": 6, "efectiva": 18, "cheque": 30, "referencia": 45, "detalle": 58}
_WEB_MONTO_END = 101
_WEB_BALANCE_END = 116
_WEB_WRAP = 11.3  # distancia entre renglones de una misma descripción
_WEB_GAP = 18.5  # distancia entre filas


def _at(*parts: tuple[int, str]) -> str:
    """Texto con cada parte empezando en su columna (en caracteres)."""
    line = ""
    for column, text in parts:
        line = line.ljust(column) + text
    return line


def _web_header(top: float) -> list[tuple[float, str]]:
    c = _WEB_COLUMNS
    return [
        (top, _at((c["posteo"], "Fecha"), (c["efectiva"], "Fecha"), (c["cheque"], "Nro. de"),
                  (c["referencia"], "Nro. de"))),
        (top + 5.4, _at((c["detalle"], "Descripción"), (_WEB_MONTO_END - 6, "Monto"),
                        (_WEB_BALANCE_END - 8, "Balance"))),
        (top + 11.2, _at((c["posteo"], "posteo"), (c["efectiva"], "efectiva"),
                         (c["cheque"], "cheque"), (c["referencia"], "referencia"))),
    ]  # fmt: skip


def _web_row(top: float, movement: WebRow) -> tuple[list[tuple[float, str]], float]:
    """Renglones de una fila desde `top`; devuelve también dónde empieza la siguiente."""
    posted, effective, cheque, reference, details, amount, balance = movement
    c = _WEB_COLUMNS
    middle = top + (len(details) - 1) / 2 * _WEB_WRAP
    inline = details[len(details) // 2] if len(details) % 2 else ""
    main = _at(
        (c["posteo"], posted),
        (c["efectiva"], effective),
        *([(c["cheque"], cheque)] if cheque else []),
        *([(c["referencia"], reference)] if reference else []),
        *([(c["detalle"], inline)] if inline else []),
    )
    main = _at((0, main), (_WEB_MONTO_END - len(amount), amount))
    main = _at((0, main), (_WEB_BALANCE_END - len(balance), balance))
    lines = [(middle, main)]
    for index, text in enumerate(details):
        if inline and index == len(details) // 2:
            continue
        lines.append(
            (middle + (index - (len(details) - 1) / 2) * _WEB_WRAP, _at((c["detalle"], text)))
        )
    return lines, top + (len(details) - 1) * _WEB_WRAP + _WEB_GAP


def popular_web(
    *pages_rows: tuple[WebRow, ...],
    account: str = "Cuenta Corriente / 123456789",
    printed: str = "21 de enero de 2026 a las 9:41 a. m.",
) -> tuple:
    """Páginas de una impresión; la primera lleva la cabecera de la cuenta."""
    built = []
    for number, rows in enumerate(pages_rows):
        lines: list[tuple[float, str]] = []
        top = 3.6
        if number == 0:
            lines += [(16.0, _at((87, printed))), (73.6, "     FULANO DE TAL"),
                      (84.9, "    INVENTADO"), (96.1, f"     {account}"),
                      (107.8, "     Transacciones")]  # fmt: skip
            top = 129.9
        lines += _web_header(top)
        top += 29.7
        for movement in rows:
            row_lines, top = _web_row(top, movement)
            lines += row_lines
        if number == len(pages_rows) - 1:
            lines.append((top + 40, _at((45, "Copyright inventado 2026 Banco Ficticio, S.A."))))
        built.append(placed(*lines))
    return tuple(built)


WEB_ROWS: tuple[WebRow, ...] = (
    ("12/01/2026", "11/01/2026", "0000000000001", None, ("MB DESDE 000000003 FULANO DE",),
     "$10,000.00", "$64,998.50"),
    ("16/01/2026", "15/01/2026", "0000000000002", None,
     ("PAGO TARJETA", "TIENDA FICTICIA S.R.L.", "SANTO DOMINGO"), "$1,500.00-", "$63,498.50"),
    ("17/01/2026", "17/01/2026", None, None, ("DEPOSITO CHEQUE Y EFECTIVO",),
     "$2,000.00", "$65,498.50"),
    ("19/01/2026", "19/01/2026", "0000000000003", None,
     ("IMPUESTO 0.15% DGII 1 TRANS POR", "$ 1,500.00 DEL 16/01/2026 AL", "16/01/2026"),
     "$2.25-", "$65,496.25"),
    ("20/01/2026", "20/01/2026", "0000000000004", "0001",
     ("TRANSFERENCIA RECIBIDA DE", "PERSONA INVENTADA"),
     "$500.00", "$65,996.25"),
)  # fmt: skip
POPULAR_WEB = popular_web(WEB_ROWS[:3], WEB_ROWS[3:])

# Una impresión posterior que repite días de la anterior y trae movimientos nuevos.
WEB_ROWS_LATER: tuple[WebRow, ...] = (
    *WEB_ROWS[1:],
    ("20/01/2026", "20/01/2026", "0000000000005", None, ("COMISION INVENTADA",),
     "$50.00-", "$65,946.25"),
    ("22/01/2026", "22/01/2026", "0000000000006", None, ("MB A 0000000009 PERSONA",),
     "$1,000.00-", "$64,946.25"),
)  # fmt: skip
POPULAR_WEB_LATER = popular_web(WEB_ROWS_LATER, printed="23 de enero de 2026 a las 8:05 p. m.")

# La misma página impresa más tarde el mismo día: igual rango, un posteo tardío más.
POPULAR_WEB_REPRINT = popular_web(
    (*WEB_ROWS, WEB_ROWS_LATER[4]), printed="20 de enero de 2026 a las 6:30 p. m."
)

# Un sobregiro: la cadena baja de cero y vuelve. El balance negativo lleva el signo
# delante del símbolo ("-$5.40"); el monto, detrás ("$15.40-").
WEB_ROWS_OVERDRAFT: tuple[WebRow, ...] = (
    ("05/02/2026", "05/02/2026", "0000000000011", None, ("DEPOSITO INVENTADO",),
     "$10.00", "$10.00"),
    ("06/02/2026", "06/02/2026", "0000000000012", None, ("CARGO INVENTADO",),
     "$15.40-", "-$5.40"),
    ("07/02/2026", "07/02/2026", "0000000000013", None, ("COMISION SOBREGIRO",),
     "$1.00-", "-$6.40"),
    ("09/02/2026", "09/02/2026", "0000000000014", None, ("TRANSFERENCIA RECIBIDA",),
     "$20.00", "$13.60"),
)  # fmt: skip
POPULAR_WEB_OVERDRAFT = popular_web(WEB_ROWS_OVERDRAFT)

# Un balance intermedio que no sigue de los montos: los totales cuadran, la cadena no.
POPULAR_WEB_BROKEN_CHAIN = popular_web(
    (*WEB_ROWS[:2], (*WEB_ROWS[2][:6], "$65,598.50"), *WEB_ROWS[3:]),
)

# Estado de cuenta de Banreservas (portal, "Microsoft Reporting Services"): una página por
# mes. Arriba "Titular:", una fila "Número de cuenta | Alias | Fecha del reporte | Balance"
# con sus valores (el balance es el del día del reporte, no el del corte) y "Movimientos"
# con el periodo, que termina el primer día del mes siguiente. La tabla tiene Fecha,
# Descripción, Débito (con "-" delante), Crédito y Balance; las filas van de la más nueva
# a la más vieja y la descripción sigue en renglones debajo de la fila (la contraparte de
# una transferencia).
# Cada fila: (fecha, renglones de descripción, débito o None, crédito o None, balance).
BanreservasRow = tuple[str, tuple[str, ...], str | None, str | None, str]

_BR_DATE = 12  # columnas en caracteres (5 puntos cada uno)
_BR_DETAIL = 29
_BR_DEBIT_END = 69
_BR_CREDIT_END = 90
_BR_BALANCE_END = 112
_BR_WRAP = 13.4  # distancia entre renglones de una misma fila
_BR_GAP = 17.4  # distancia entre el último renglón de una fila y la siguiente


def _br_row(top: float, movement: BanreservasRow) -> tuple[list[tuple[float, str]], float]:
    day, details, debit, credit, balance = movement
    main = _at((_BR_DATE, day), (_BR_DETAIL, details[0] if details else ""))
    if debit is not None:
        main = _at((0, main), (_BR_DEBIT_END - len(debit), debit))
    if credit is not None:
        main = _at((0, main), (_BR_CREDIT_END - len(credit), credit))
    main = _at((0, main), (_BR_BALANCE_END - len(balance), balance))
    lines = [(top, main)]
    for index, text in enumerate(details[1:], start=1):
        lines.append((top + index * _BR_WRAP, _at((_BR_DETAIL, text))))
    return lines, top + max(len(details) - 1, 0) * _BR_WRAP + _BR_GAP


def banreservas(
    *pages_rows: tuple[BanreservasRow, ...],
    account: str = "0000000000",
    period: str = "01/01/2026 - 01/02/2026",
    report: str = "05/02/2026",
    balance: str = "1,500.00",
    holder: str = "FULANO DE TAL",
    carried: tuple[str, ...] = (),
    repeat_header: bool = True,
) -> tuple:
    """Páginas de un estado; la primera lleva la cabecera de la cuenta.

    `carried`: renglones de descripción arriba de la segunda página, que siguen a la última
    fila de la primera. `repeat_header`: si las páginas siguientes repiten los títulos.
    """
    built = []
    for number, rows in enumerate(pages_rows):
        lines: list[tuple[float, str]] = []
        top = 40.0
        if number == 0:
            lines += [
                (73.1, _at((7, f"Titular: {holder}"))),
                (110.8, _at((8, "Número de cuenta"), (30, "Alias"), (68, "Fecha del reporte"),
                            (_BR_BALANCE_END - 7, "Balance"))),
                (128.3, _at((8, account), (30, "-"), (71, report),
                            (_BR_BALANCE_END - len(balance), balance))),
                (160.8, _at((7, "Movimientos"))),
                (186.5, _at((7, period))),
            ]  # fmt: skip
            top = 221.7
        if number == 0 or repeat_header:
            lines.append(
                (top, _at((14, "Fecha"), (_BR_DETAIL, "Descripción"),
                          (_BR_DEBIT_END - 6, "Débito"), (_BR_CREDIT_END - 7, "Crédito"),
                          (_BR_BALANCE_END - 7, "Balance")))
            )  # fmt: skip
            top += 17.4
        if number == 1:
            for text in carried:
                lines.append((top, _at((_BR_DETAIL, text))))
                top += _BR_WRAP
            top += _BR_GAP - _BR_WRAP if carried else 0
        for movement in rows:
            row_lines, top = _br_row(top, movement)
            lines += row_lines
        built.append(placed(*lines))
    return tuple(built)


# De la más nueva a la más vieja, como el banco. Balance antes de la primera: 10,000.00.
BANRESERVAS_ROWS: tuple[BanreservasRow, ...] = (
    ("28/01/2026", ("TRANSFERENCIA",), "-26,000.00", None, "1,408.59"),
    ("20/01/2026", ("PAGO INTERES INVENTADO",), None, "12.34", "27,408.59"),
    ("15/01/2026", ("PAGOS AL INSTANTE", "BCRD A ZUTANO FICTICIO", "RODRIGUEZ"),
     "-2,500.00", None, "27,396.25"),
    ("15/01/2026", ("COMISION PAGO AL", "INSTANTE BCRD"), "-100.00", None, "29,896.25"),
    ("10/01/2026", ("TRANSFERENCIA A", "MENGANO INVENTADO", "PEREZ"),
     "-5,000.00", None, "29,996.25"),
    ("05/01/2026", ("COBRO IMP DGII", "0.15%_IMPUESTO INV"), "-3.75", None, "34,996.25"),
    ("03/01/2026", ("TRANSFERENCIA DE", "PERSONA INVENTADA", "OTRO APELLIDO"),
     None, "25,000.00", "35,000.00"),
)  # fmt: skip
BANRESERVAS = banreservas(BANRESERVAS_ROWS)

# Un balance intermedio que no sigue de los montos.
BANRESERVAS_BROKEN_CHAIN = banreservas(
    (*BANRESERVAS_ROWS[:3], (*BANRESERVAS_ROWS[3][:4], "29,996.25"), *BANRESERVAS_ROWS[4:])
)

# El mes en curso: el reporte es de antes de que cierre el periodo, y el balance de la
# cabecera (el del día del reporte) es el de la fila más nueva.
BANRESERVAS_PARTIAL = banreservas(BANRESERVAS_ROWS[1:], report="27/01/2026", balance="27,408.59")

UNKNOWN = page("DOCUMENTO SIN FORMATO CONOCIDO", "Nada que leer aquí.")

POPULAR_PAGES = (POPULAR_DOP, POPULAR_USD, POPULAR_TERMS)
BHD_TC_PAGES = (BHD_TC_SUMMARY, BHD_TC_MOVEMENTS, BHD_TC_CONTINUED)
BHD_AHORRO_PAGES = (BHD_AHORRO,)
BHD_AHORRO_PORTAL_PAGES = (BHD_AHORRO_PORTAL,)

# Estados «históricos» del Popular: la ejecutiva manda un PDF con varios estados mensuales
# seguidos de una cuenta, con páginas en blanco (o con solo un número) entre uno y otro.
# Cada estado empieza en la página con "PAG 1" en la línea del titular; las siguientes dicen
# "PAG 2"… y repiten la cabecera. Fechas "DD MMM" sin año, débito con "-" al final, montos
# menores que uno sin cero inicial (".00"); la descripción va en la misma línea del monto o
# en las de abajo. Cada fila: (entrada, transacción, descripción en la línea, monto con
# signo, renglones de detalle). El generador calcula los balances y el resumen.
HistoricoRow = tuple[str, str, str, str, tuple[str, ...]]

_HI_ENTRY, _HI_TRANS, _HI_INLINE, _HI_DETAIL = 20, 29, 37, 40
_HI_AMOUNT_END, _HI_BALANCE_END = 88, 104
_HI_INTEREST = ("INTERES GANADO",)


def _hi_value(text: str) -> Decimal:
    digits = text.rstrip("-").replace(",", "")
    return Decimal(f"0{digits}" if digits.startswith(".") else digits)


def _hi_money(value: Decimal) -> str:
    text = f"{value:,.2f}"
    return text[1:] if text.startswith("0.") else text


def _hi_header(
    sheet: int, number: int, account: str, cut: str, page_format: str = "PAG {}"
) -> list[str]:
    return [
        str(sheet),
        _at((0, "SR FULANO DE TAL"), (57, page_format.format(number))),
        "CALLE INVENTADA NO 1",
        _at((0, "SANTO DOMINGO"), (51, cut)),
        "SECTOR INVENTADO 1",
        "SANTO DOMINGO DISTRITO NACIONAL",
        _at((8, account)),
        _at((8, "NUMERO DE CUENTA REGIONAL DO00BPDO00000000000123456789")),
    ]


def _hi_line(*parts: tuple[int, str], amount: str = "", balance: str) -> str:
    line = _at(*parts)
    if amount:
        line = _at((0, line), (_HI_AMOUNT_END - len(amount), amount))
    return _at((0, line), (_HI_BALANCE_END - len(balance), balance))


def _hi_summary(
    opening: Decimal,
    rows: list[HistoricoRow],
    interest: str | None,
    closing: str,
    debit_count_off: int = 0,
) -> list[str]:
    credits = [r for r in rows if not r[3].endswith("-") and r[4] != _HI_INTEREST]
    debits = [r for r in rows if r[3].endswith("-")]
    total = {
        "credits": sum((_hi_value(r[3]) for r in credits), Decimal(0)),
        "debits": sum((_hi_value(r[3]) for r in debits), Decimal(0)),
    }
    return [
        _at((35, "CANTIDAD"), (53, "MONTO")),
        _hi_line((3, "BALANCE ANTERIOR"), balance=_hi_money(opening)),
        _hi_line((3, "+ DEPOSITOS Y OTROS CREDITOS"), (38, str(len(credits))),
                 balance=_hi_money(total["credits"])),
        _hi_line((3, "- CHEQUES Y OTROS DEBITOS"), (38, str(len(debits) + debit_count_off)),
                 balance=_hi_money(total["debits"])),
        *([_hi_line((3, "+ INTERES PAGADO"), balance=interest)] if interest else []),
        _hi_line((3, "BALANCE AL CORTE"), balance=closing),
    ]  # fmt: skip


def popular_history(
    *pages_rows: tuple[HistoricoRow, ...],
    account: str = "CTA CTE NOMINA 123456789 RD$ FULANO DE TAL",
    cut: str = "12 NOV 2025",
    opening: str = "52,618.37",
    opening_day: str = "09 OCT",
    interest: str | None = None,
    closing: str | None = None,
    sheet: int = 1,
    debit_count_off: int = 0,
    page_format: str = "PAG {}",
    footer: tuple[int, str] | None = None,
) -> tuple[Page, ...]:
    """Páginas de un estado. `interest` agrega la fila del interés pagado el día del corte;
    `closing` cambia el balance al corte del resumen (para un estado que no cuadra);
    `debit_count_off` se suma a la cantidad de débitos impresa (el banco a veces cuenta una
    fila menos en los meses con interés); `page_format` es cómo se imprime el número de
    página; `footer` (columna, texto) va justo debajo de las filas de cada página."""
    rows = [list(r) for r in pages_rows] or [[]]
    cut_day = " ".join(cut.split()[:2])
    if interest is not None:
        rows[-1].append((cut_day, cut_day, "", interest, _HI_INTEREST))
    start = balance = _hi_value(opening)
    built: list[list[str]] = []
    for number, page_rows in enumerate(rows, start=1):
        lines = _hi_header(sheet + number - 1, number, account, cut, page_format)
        summary_at = len(lines)
        lines += [
            _at((3, "FECHA  FECHA   NUM DE   DESCRIPCION"), (80, "MONTO"), (97, "BALANCE")),
            _at((3, "ENTRADA TRANS  CHEQUE")),
        ]
        if number == 1:
            lines.append(
                _hi_line((_HI_ENTRY, opening_day), (_HI_INLINE, "BALANCE ANTERIOR"),
                         balance=_hi_money(start))
            )  # fmt: skip
        for entry, trans, inline, amount, details in page_rows:
            value = _hi_value(amount)
            balance += -value if amount.endswith("-") else value
            parts = [(_HI_ENTRY, entry), (_HI_TRANS, trans)]
            if inline:
                parts.append((_HI_INLINE, inline))
            lines.append(_hi_line(*parts, amount=amount, balance=_hi_money(balance)))
            lines += [_at((_HI_DETAIL, text)) for text in details]
        if footer is not None:
            lines.append(_at(footer))
        if number == len(rows):
            lines.append(
                _hi_line((_HI_ENTRY, cut_day), (_HI_INLINE, "BALANCE AL CORTE"),
                         balance=_hi_money(balance))
            )  # fmt: skip
        lines += ["", "", _at((3, "PIE DE PAGINA INVENTADO 000-000-0000"))]
        built.append(lines)
    # El resumen de la primera página necesita el balance final: va al terminar.
    all_rows = [r for page_rows in rows for r in page_rows]
    summary = _hi_summary(start, all_rows, interest, closing or _hi_money(balance), debit_count_off)
    built[0][summary_at:summary_at] = summary
    return tuple(page(*lines) for lines in built)


HISTORICO_NOV_ROWS: tuple[tuple[HistoricoRow, ...], ...] = (
    (
        ("14 OCT", "14 OCT", "", "43,275.81", ("PAGO DE NOMINAS EMPRESA INVENTADA", "RD$ .00")),
        ("14 OCT", "14 OCT", "", "60,000.00-", ("MB a 000000001 PERSONA INVENTADA",)),
        ("17 OCT", "17 OCT", "", "180.00-",
         ("PAGO IMPUESTO 0.15% DGII", "3 TRANS POR $ 120,000.00", "Del 06/10/2025 Al 12/10/2025")),
    ),
    (
        ("03 NOV", "03 NOV", "AUT PAGO 850000000", "5,412.66-", ("008-00000",)),
        ("10 NOV", "08 NOV", "", "100,000.00", ("DEPOSITO INVENTADO",)),
    ),
)  # fmt: skip
HISTORICO_NOV = popular_history(*HISTORICO_NOV_ROWS)
# Balance al corte de noviembre: 52,618.37 + 143,275.81 − 65,592.66.
HISTORICO_NOV_CLOSING = "130,301.52"
# Diciembre sin movimientos: el balance anterior es el del corte.
HISTORICO_DIC = popular_history(
    cut="12 DIC 2025", opening=HISTORICO_NOV_CLOSING, opening_day="12 NOV", sheet=3
)
# Enero cruza el año: las filas de diciembre son de 2025.
HISTORICO_ENE = popular_history(
    (
        ("20 DIC", "19 DIC", "COMPRA INVENTADA", "1,311.12-", ()),
        ("05 ENE", "05 ENE", "", "10,000.00", ("MB desde 000000003 FULANO DE",)),
        ("12 ENE", "11 ENE", "", "10,000.00", ("MB desde 000000003 FULANO DE",)),
    ),
    cut="12 ENE 2026",
    opening=HISTORICO_NOV_CLOSING,
    opening_day="12 DIC",
    sheet=4,
)
# Un PDF con los tres estados y páginas en blanco (o con solo un número) intercaladas.
POPULAR_HISTORICO = (
    page(),
    *HISTORICO_NOV,
    page("3"),
    *HISTORICO_DIC,
    page(),
    *HISTORICO_ENE,
    page("6"),
)
# El mismo PDF con el balance al corte de diciembre mal impreso: ese tramo no cuadra.
POPULAR_HISTORICO_BAD_DIC = (
    *HISTORICO_NOV,
    page(),
    *popular_history(
        cut="12 DIC 2025",
        opening=HISTORICO_NOV_CLOSING,
        opening_day="12 NOV",
        closing="140,000.00",
        sheet=3,
    ),
    page(),
    *HISTORICO_ENE,
)

# Ahorro en dólares con interés pagado (va aparte de los depósitos en el resumen).
POPULAR_HISTORICO_USD = popular_history(
    (
        ("05 SEP", "05 SEP", "TRANSFERENCIA RECIBIDA", "500.00", ("DEL EXTERIOR",)),
        ("20 SEP", "20 SEP", "", "200.00-", ("TRANSFERENCIA A CUENTA PROPIA",)),
    ),
    account="AHORRO US$ PERS 987654321 USD FULANO DE TAL",
    cut="30 SEP 2025",
    opening="1,000.00",
    opening_day="31 AGO",
    interest=".12",
)

# Otro mes con interés en que el resumen cuenta una fila de débito menos de las que trae
# (montos y cadena de balances cuadran): entra con una nota, no como inválido.
POPULAR_HISTORICO_USD_SHORT_COUNT = popular_history(
    (
        ("03 OCT", "03 OCT", "", "100.00-", ("COMISION INVENTADA",)),
        ("10 OCT", "10 OCT", "", "50.00-", ("TRANSFERENCIA A CUENTA PROPIA",)),
        ("20 OCT", "20 OCT", "", "300.00", ("TRANSFERENCIA RECIBIDA",)),
    ),
    account="AHORRO US$ PERS 987654321 USD FULANO DE TAL",
    cut="31 OCT 2025",
    opening="1,300.12",
    opening_day="30 SEP",
    interest=".15",
    debit_count_off=-1,
)

# Cuenta Digital (corriente) que se vacía: cierra en ".00".
POPULAR_HISTORICO_DIGITAL = popular_history(
    (("15 OCT", "15 OCT", "", "1,500.00-", ("MB a 000000009 PERSONA INVENTADA",)),),
    account="CUENTA DIGITAL 555666777 RD$ FULANO DE TAL",
    cut="12 NOV 2025",
    opening="1,500.00",
)

# Separadores rotos entre palabras: "ï¿½" (los bytes UTF-8 de U+FFFD leídos como latin-1),
# U+FFFD solo y el espacio duro, donde el PDF tenía un espacio.
_BAD = "ï¿½"
HISTORICO_BROKEN_SPACES_DESCRIPTION = "LBTR/IB/ VIA LBTR 2000000000 FULANO DE TAL BANCO INVENTADO"
POPULAR_HISTORICO_BROKEN_SPACES = popular_history(
    (
        ("05 NOV", "05 NOV", "", "5,000.00-",
         (f"LBTR/IB/ VIA LBTR 2000000000 FULANO{_BAD}DE{_BAD}TAL",
          "BANCO�INVENTADO  ")),
    ),
    account="CUENTA DIGITAL 555666777 RD$ FULANO DE TAL",
    cut="12 NOV 2025",
    opening="6,000.00",
)  # fmt: skip


# Historial de préstamo del Popular (lo manda el oficial de cuentas): encabezado con el número,
# el saldo de capital y la cancelación a la fecha, y una fila por movimiento con el monto y el
# saldo después. Las filas viejas traen dos fechas numéricas y un código; las nuevas, una sola
# fecha con el mes en letras.
def popular_loan_history(
    movements: tuple[str, ...],
    *,
    number: str = "1234567",
    capital: str = "89,950.00",
) -> tuple[Page, ...]:
    return (
        page(
            "                    Historial Préstamo        15-Jul-2025",
            f"          Préstamo: {number}            Moneda: RD$",
            "            Nombre: FULANO DE TAL",
            f"  Saldo de capital:        {capital}",
            "           Interés:         (120.50)",
            "              Mora:                -",
            "Balance de Bolcillo:               -",
            "            Seguro:                -",
            "Cancelación en fecha:      89,829.50",
            "Fch pst  Fch efc CT Descripción          Monto tran    Saldo de cuenta",
            *movements,
        ),
    )


POPULAR_LOAN_MOVEMENTS = (
    " 5-03-25  5-03-25 34 DESEMBOLSO ADIC      120,000.00      120,000.00",
    " 5-03-25  5-03-25 83 PAGO                   1,440.00      120,000.00",
    " 5-03-25  5-03-25 83 PAGO                     560.00      120,000.00",
    " 7-04-25  7-04-25 83 PAGO                  11,200.00      110,000.00",
    "         5-May-25    PAGO                  11,100.00      100,000.00",
    "         9-Jun-25    PAGO                   4,000.00       96,950.00",
    "         9-Jun-25    PAGO                   7,000.00       89,950.00",
    "        10-Jun-25    PAGO                     300.00       89,950.00",
)
POPULAR_LOAN_HISTORY = popular_loan_history(POPULAR_LOAN_MOVEMENTS)
# El saldo impreso no es el de la última fila.
POPULAR_LOAN_HISTORY_WRONG_BALANCE = popular_loan_history(
    POPULAR_LOAN_MOVEMENTS, capital="80,000.00"
)
# Un pago que baja el capital más de lo que se pagó.
POPULAR_LOAN_HISTORY_BROKEN_CHAIN = popular_loan_history(
    (
        "         5-May-25    DESEMBOLSO SIEBEL     50,000.00       50,000.00",
        "         5-Jun-25    PAGO                   1,000.00       45,000.00",
    ),
    capital="45,000.00",
)
# Un movimiento que el parser no conoce.
POPULAR_LOAN_HISTORY_UNKNOWN_ROW = popular_loan_history(
    (
        "         5-May-25    DESEMBOLSO SIEBEL     50,000.00       50,000.00",
        "         5-Jun-25    AJUSTE                 1,000.00       49,000.00",
    ),
    capital="49,000.00",
)
