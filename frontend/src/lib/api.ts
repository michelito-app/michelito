// Tipos de la API local (src/finanzas/web/schemas.py): dinero en centavos enteros,
// fechas ISO y la tasa como texto con 4 decimales.

export interface MonthOption {
  month: string
  label: string
  partial: boolean
}

export interface Rate {
  value: string
  month_used: string
  source: string
}

export interface SavedRate extends Rate {
  month: string
}

export interface Coverage {
  key: string
  label: string
  through: string | null
  complete: boolean
}

export interface CategoryLine {
  category: string
  amount_cents: number
  habitual_cents: number | null
  diff_cents: number | null
  same: boolean
  share: number
  one_offs_cents: number
  purchases: number
  habitual_purchases: number | null
}

export interface Change {
  category: string
  diff_cents: number
  one_offs_cents: number
  purchases: number
  habitual_purchases: number | null
}

/** Tipo de una categoría: solo los gastos cuentan como gasto; las transferencias, en nada. */
export type Kind = 'ingreso' | 'gasto' | 'transferencia'

/** GET /api/categories: también las ocultas (los selectores las dejan fuera). */
export interface Category {
  id: number
  name: string
  kind: Kind
  color: string | null // null: color automático (por puesto en el Resumen)
  hidden: boolean
  builtin: boolean // del sistema: no se borra ni cambia de tipo
  builtin_key: string | null // identidad estable de una del sistema ("THIRD_PARTY")
  keywords: string[]
  count_year: number
}

export interface CategoryBody {
  name: string
  kind: Kind
  color?: string | null
  keywords?: string[]
}

/** Lo ausente no cambia; `color: null` vuelve al color automático. */
export interface CategoryPatch {
  name?: string
  kind?: Kind
  color?: string | null
  hidden?: boolean
  keywords?: string[]
}

/** POST /api/categories/{id}/preview: qué movería guardar esas palabras clave. */
export interface KeywordPreview {
  count: number
  total_cents: number // en RD$, sin los US$ sin tasa
  unconverted_usd_cents: number
  conflicts: number
}

export interface MonthTotal {
  month: string
  label: string
  total_cents: number // gastos
  income_cents: number
  partial: boolean // mes en curso para las cuentas elegidas: va en color claro
  // Mes atípico frente a lo habitual (> max(30 %, RD$ 10,000) contra la mediana de los 6
  // meses completos anteriores); null si no lo es o no se compara.
  spent_flag: Direction | null
  spent_habitual_cents: number | null // null con menos de tres meses de referencia
  income_flag: Direction | null
  income_habitual_cents: number | null
}

export type Direction = 'up' | 'down'

/** Un comercio que explica un mes atípico ("Qué pasó"). */
export interface Contribution {
  side: 'gasto' | 'ingreso'
  merchant: string
  category: string
  amount_cents: number // lo del comercio en el mes, RD$
  habitual_cents: number // su mediana en los meses de referencia
  diff_cents: number
  count: number
  fingerprint: string // su movimiento mayor del mes; "" si no apareció
  day: string | null
  description: string
}

export interface AccountTotal {
  key: string
  label: string
  total_cents: number
  usd_cents: number
}

export interface Summary {
  option: MonthOption
  coverage: Coverage[]
  total_cents: number // gastos
  income_cents: number
  third_party_cents: number // transferencias a terceros del mes: no son gasto, pero salen
  net_cents: number | null // ingresos − gastos − terceros; null: solo tarjetas elegidas
  savings_rate: number | null // null si el ingreso es despreciable o está incompleto
  income_through: string | null // ISO: una cuenta bancaria corta antes del fin del mes
  regular_total_cents: number
  one_offs_cents: number
  habitual_cents: number | null
  usd_cents: number
  usd_in_dop_cents: number | null
  rate: Rate | null
  categories: CategoryLine[]
  changes: Change[]
  trend: MonthTotal[]
  by_account: AccountTotal[]
  needs_income: boolean // ninguna cuenta bancaria elegida (solo tarjetas): sin flujo que mostrar
  to_cards_cents: number // pagos de tarjeta desde las elegidas si falta alguna tarjeta (aprox.)
  to_own_cents: number // "Entre mis cuentas" que sale de las elegidas si falta alguna (aprox.)
  owed_cents: number // te deben: pendiente de los gastos compartidos del mes (RD$)
  exchanges_pending_cents: number // cambios de divisas abiertos del mes: pendiente en RD$
  what_happened: Contribution[] // "Qué pasó": vacío si el mes no es atípico
  invested_cents: number // aportes a inversiones del mes (RD$): no restan de lo que te quedó
  cash_box_cents: number // retiros del mes guardados en la caja fuerte (RD$): tampoco restan
  incomes: IncomeLine[] // ingresos del mes por categoría («Cripto» aparte), de mayor a menor
}

/** Los ingresos del mes de una categoría, en RD$ (positivo). */
export interface IncomeLine {
  category: string
  amount_cents: number
  count: number
}

/** Otra transacción mencionada en el detalle (un reembolso, una pata, una sugerencia). */
export interface LinkedTx {
  fingerprint: string
  day: string
  merchant: string
  account_label: string
  amount_cents: number // el del estado; un crédito, negativo
  currency: string
  // Un crédito en la otra moneda del gasto: lo que vale en la del gasto (null si falta la tasa).
  converted_cents?: number | null
  converted_currency?: string | null
  description?: string // como aparece en el estado
}

/** Una opción de un selector de vínculos, en el orden del servidor; `primary`: va a la vista
 * (la interfaz muestra las primeras y deja el resto tras «Ver más»). */
export interface Candidate extends LinkedTx {
  primary: boolean
}

/** Reembolso anotado a mano: en efectivo (`place` vacío) o en otra cuenta. */
export interface ManualEntry {
  id: number
  amount_cents: number
  day: string
  person: string
  place: string
  currency: string // la del dinero
}

/** Reparto de un gasto: exactamente una forma. */
export interface Split {
  people: number | null
  my_share_cents: number | null
  for_other: boolean
}

/** Un gasto de un grupo compartido: su reparto y su estado (en su moneda). */
export interface GroupExpense extends LinkedTx, Split {
  share_cents: number
  counted_cents: number
  reimbursed_cents: number // lo imputado, del gasto más viejo al más nuevo
  pending_cents: number
  written_off_cents: number
}

/** Las cifras de los gastos del grupo en una moneda. */
export interface SharedTotal {
  currency: 'DOP' | 'USD'
  share_cents: number
  reimbursed_cents: number
  pending_cents: number
  written_off_cents: number
}

/** Un grupo en una lista: título (nombre, «Con quién» o comercio) y lo pendiente por moneda. */
export interface GroupRef {
  id: number
  title: string
  name: string
  with_whom: string
  first_fingerprint: string // el primer gasto: abre la pantalla del grupo
  expense_count: number
  pending: CurrencyCents[]
  last_split: Split // el del último gasto agregado: se propone al sumar otro
}

export interface GroupCandidate extends GroupRef {
  primary: boolean
}

/** Un grupo compartido: uno o más gastos, cada uno con su reparto, y sus reembolsos. */
export interface SharedInfo extends GroupRef {
  written_off: boolean
  expenses: GroupExpense[] // del más viejo al más nuevo
  totals: SharedTotal[]
  excess: CurrencyCents[] // devuelto de más tras saldar todo
  unconverted: string[] // reembolsos que no contaron por falta de tasa
  reimbursements: LinkedTx[]
  manual: ManualEntry[]
}

export interface ExchangeInfo {
  id: number
  rate: string // RD$ por US$ en uso, 4 decimales
  implied_rate: string
  agreed_rate: string | null
  closed: boolean
  base: 'DOP' | 'USD'
  totals: CurrencyCents[]
  pending_cents: number
  pending_currency: 'DOP' | 'USD'
  pending_dop_cents: number
  needs_agreed_rate: boolean // sin tasa acordada y solo el primer par: el pendiente no dice nada
  legs: LinkedTx[]
}

export type LinkKind =
  | ''
  | 'shared'
  | 'reimbursement'
  | 'exchange'
  | 'investment'
  | 'cash_box'
  | 'reserve'

export type InvestmentStatus = 'active' | 'closed' | 'written_off'
export type InvestmentRole = 'contribution' | 'return' | 'capital' | 'mixed'
export type CreditRole = Exclude<InvestmentRole, 'contribution'>

/** Una inversión en una lista: título (nombre, «Con quién» o comercio) y capital por volver. */
export interface InvestmentRef {
  id: number
  title: string
  name: string
  with_whom: string
  status: InvestmentStatus
  currency: string // la del primer aporte
  first_fingerprint: string // el primer aporte: abre la pantalla de la inversión
  pending_cents: number // capital por volver, en `currency`
}

/** «¿Es otro aporte a…?» o «¿Es un cobro de…?» de una fila. */
export interface InvestmentHint extends InvestmentRef {
  kind: 'aporte_posible' | 'cobro_posible'
}

/** Un movimiento de una inversión, en su moneda. */
export interface InvestmentEntry {
  fingerprint: string
  day: string
  merchant: string
  description: string
  account_label: string
  role: InvestmentRole
  amount_cents: number // positivo
  currency: string
  capital_cents: number // parte de capital de un crédito (aporte: 0)
  return_cents: number // parte de rendimiento de un crédito (aporte: 0)
  excess_cents: number // capital devuelto de más que lo aportado: está en return_cents
  counted: boolean // false: en otra moneda sin ninguna tasa, no suma
}

/** Una inversión con sus cifras (en su moneda) y sus movimientos. */
export interface Investment extends InvestmentRef {
  written_off: boolean
  first_day: string
  last_activity: string
  last_credit: string | null
  contributed_cents: number
  capital_returned_cents: number
  returns_cents: number // incluye lo devuelto de más (excess_cents)
  excess_cents: number // capital devuelto de más que lo aportado: cuenta como rendimiento
  annual_rate: number | null // fracción (0.12 = 12 %); null sin tiempo invertido
  pending_dop_cents: number | null // capital por volver ≈ RD$; null: US$ sin tasa
  unconverted_count: number
  entries: InvestmentEntry[] // por fecha
}

/** Todas las inversiones (`GET /api/investments`) y sus totales en ≈ RD$. */
export interface InvestmentList {
  pending_dop_cents: number
  returns_year_dop_cents: number
  year: number
  active_count: number
  unconverted: { pending_usd_cents: number; returns_usd_cents: number } // US$ sin tasa
  rate: Rate | null
  investments: Investment[] // la última actividad primero
}

export interface InvestmentPatch {
  name?: string | null
  with_whom?: string | null
  written_off?: boolean
}

/** El tipo de un crédito; `capital_cents` solo en un mixto (0 < capital < crédito). */
export interface RoleBody {
  role: CreditRole
  capital_cents?: number
}

/** Forma de repartir un gasto: exactamente una. */
export interface SplitBody {
  people?: number
  my_share_cents?: number
  for_other?: boolean
}

/** El reparto del gasto; si no está en un grupo, `link_id` lo suma a ese grupo y, sin él, se
 * crea uno nuevo con «Con quién» (`with_whom`, opcional). */
export interface SharedBody extends SplitBody {
  link_id?: number
  with_whom?: string | null
}

export interface GroupPatch {
  name?: string | null
  with_whom?: string | null
  written_off?: boolean
}

export interface ManualBody {
  amount_cents: number
  day: string
  person?: string | null
  place?: string | null
  currency?: 'DOP' | 'USD' | null // null: la del gasto más antiguo del grupo
}

export interface ReimbursementCandidates {
  credits: Candidate[] // créditos que pueden reembolsar el grupo
  groups: GroupCandidate[] // grupos que este crédito puede reembolsar
  places: string[]
}

export interface Tx {
  fingerprint: string
  day: string
  merchant: string
  description: string
  category: string
  category_id: number | null
  kind: Kind
  original_category: string
  account: string
  account_label: string
  amount_cents: number
  currency: string
  amount_dop_cents: number | null
  one_off: boolean
  corrected: boolean
  merchant_year_count: number
  suggested_one_off: boolean // parece gasto único (reglas locales); ver one_off_reasons
  one_off_reasons: string[]
  one_off_dismissed: boolean // el usuario dijo "No es único"; se puede volver a sugerir
  note: string
  // Vínculos: "shared" (amount_cents es tu parte; gross_cents, el monto del estado),
  // "reimbursement", "exchange" o "".
  link: LinkKind // también si el vínculo está dormido (su gasto o una pata ya no aparece)
  link_id: number | null
  can_share: boolean // reglas del servidor: se puede marcar compartido
  can_reimburse: boolean // puede ser reembolso de un gasto compartido
  can_exchange: boolean // puede ser pata de un cambio de divisas
  gross_cents: number | null
  pending_cents: number // te deben de este gasto
  shared: SharedInfo | null // el grupo de la fila, como gasto o como reembolso
  reimbursement_of: LinkedTx | null // el primer gasto del grupo que reembolsa
  suggested_group: GroupRef | null // «¿Reembolso de <grupo>?»
  exchange: ExchangeInfo | null
  suggested_exchange_with: LinkedTx | null
  can_invest: boolean // un débito bancario que puede ser un aporte («Es una inversión…»)
  can_invest_credit: boolean // un crédito bancario que puede ser de una inversión
  investment: InvestmentRef | null // la inversión de la fila
  investment_role: InvestmentRole | '' // su tipo en ella
  investment_capital_cents: number | null // en un crédito mixto, la parte de capital
  suggested_investment: InvestmentHint | null
  can_store: boolean // un retiro (débito de «Efectivo») que se puede guardar en la caja fuerte
  can_deposit: boolean // un crédito bancario que puede venir de la caja fuerte
  cash_box_role: CashBoxRole | ''
  // En un depósito de la caja: la moneda en que salió de ella y cuánto (null: sin tasa).
  cash_box_currency: string | null
  cash_box_amount_cents: number | null
  cash_entry_id: number | null // anotado a mano en la caja (se edita y se borra)
}

export type CashBoxRole = 'stored' | 'deposit'
export type CashEntryKind = 'initial' | 'income' | 'expense'
export type CashLineKind = CashEntryKind | CashBoxRole
export type CashCurrency = 'DOP' | 'USD'

export interface CurrencyAmount {
  currency: string
  amount_cents: number
}

/** Una entrada o salida de la caja fuerte; `amount_cents` con signo en la moneda de la caja
 * (+ entra, − sale; null: depósito en otra moneda sin tasa, no baja el saldo). */
export interface CashLine {
  kind: CashLineKind
  day: string
  fingerprint: string
  entry_id: number | null // anotado a mano: se edita y se borra
  currency: string
  amount_cents: number | null
  dop_cents: number | null // ≈ RD$ a la tasa de su mes
  source_amount_cents: number // el movimiento como aparece, positivo
  source_currency: string
  merchant: string
  account_label: string
  category: string
  category_id: number | null
  note: string
  in_flow: boolean // sale en Transacciones (todo menos el saldo inicial)
  group: string | null // el grupo compartido en que está: borrarlo lo saca de él
}

/** GET /api/cash-box: saldo por moneda, ≈ RD$ y sus movimientos. */
export interface CashBox {
  account_key: string
  label: string
  exists: boolean
  balances: CurrencyAmount[] // RD$ primero
  total_dop_cents: number
  unconverted: CurrencyAmount[] // sin tasa
  negative: CurrencyAmount[] // monedas en negativo: se avisa
  uncounted: string[] // depósitos sin tasa
  lines: CashLine[] // la más reciente primero
}

export interface CashEntryBody {
  kind: CashEntryKind
  day: string
  amount_cents: number
  currency: CashCurrency
  category_id?: number | null
  note?: string | null
}

export interface DepositBody {
  currency?: CashCurrency | null
  amount_cents?: number | null
}

/** Compra del mes que parece un gasto único (GET /api/one-off-suggestions). */
export interface OneOffSuggestion {
  fingerprint: string
  day: string
  merchant: string
  description: string
  account_label: string
  amount_cents: number // en la moneda original
  currency: string
  amount_dop_cents: number
  reasons: string[]
}

/** Análisis guardado de un mes (GET /api/insights). */
export interface Insight {
  month: string
  label: string
  text: string // Markdown, hasta 4000 caracteres
  accounts: string[] | null // cuentas analizadas; null: todas
  created_at: string
  updated_at: string
  stale: boolean // los datos cambiaron desde este análisis
}

/** Una celda de "Comparar meses" (GET /api/reports/compare). */
export interface CompareCell {
  amount_cents: number
  habitual_cents: number | null // null: el mes no se compara
  flag: Direction | null // se aparta de lo habitual de su fila
  level: number // 1 a 3 en una subida; 0 si no
}

export interface CompareRow {
  key: string // "ingresos", "gastos", "terceros", "neto" o el nombre de la categoría
  label: string
  cells: CompareCell[]
}

export interface Comparison {
  months: MonthOption[] // del más viejo al más nuevo
  totals: CompareRow[]
  categories: CompareRow[]
  incomes: CompareRow[] // ingresos por categoría (clave `ingreso:<nombre>`)
}

/** Tipos de «Para revisar» (src/finanzas/analysis/review.py). */
export type ReviewKind =
  | 'unico'
  | 'ingreso_inusual'
  | 'tercero_grande'
  | 'duplicado'
  | 'subio'
  | 'aporte_posible'
  | 'cobro_posible'
  | 'regla_posible'
  | 'reserva_posible'

/** Un movimiento para revisar (GET /api/review y /api/review/history). */
export interface ReviewItem {
  kind: ReviewKind
  fingerprint: string
  day: string
  month: string
  merchant: string
  description: string
  account_label: string
  amount_cents: number // en la moneda original, positivo
  currency: string
  amount_dop_cents: number | null // null: US$ sin tasa
  reason: string
  reviewed: boolean
  investment_id?: number | null // aporte o cobro posible: la inversión que se propone
  category_id?: number | null // regla posible: la categoría que se propone
  reserve_id?: number | null // reserva posible: la reserva que se propone
}

export interface ReviewMark {
  kind: ReviewKind
  fingerprint: string
  reviewed: boolean
}

export interface DismissBody {
  dismissed: boolean
}

export interface DismissResult {
  fingerprint: string
  dismissed: boolean
}

export interface Transactions {
  items: Tx[]
  count: number
  total_cents: number // gastos de la lista, solo filas convertidas a RD$
  income_cents: number // ingresos de la lista en RD$, positivo
  unconverted_usd_cents: number // US$ sin tasa del mes
}

export interface StatementLine {
  period_start: string | null
  period_end: string
  currency: string
  charges_cents: number | null
  payments_cents: number | null
  balance_cents: number | null
  due_date: string | null
  minimum_payment_cents: number | null
  paid_full: boolean | null // null: sin veredicto (último corte o sin saldo)
  left_over_cents: number | null // lo que quedó sin pagar cuando paid_full es false
  paid_late: boolean // el saldo se cubrió, pero después de la fecha límite
  next_interest_cents: number // intereses cobrados en el estado siguiente
  printout: boolean // impresión de Transacciones del portal, no un estado del banco
}

export interface CurrencyCents {
  currency: string
  cents: number
}

/** Qué pagar antes de la fecha límite para no generar intereses. `text` es la frase del
 * servidor; la interfaz arma la suya y la usa solo de respaldo. */
export interface DuePayment {
  due_date: string
  amounts: CurrencyCents[]
  minimums: CurrencyCents[]
  text: string
}

export interface Account {
  key: string
  kind: string
  label: string
  cut_day: number | null
  currencies: string[]
  latest: StatementLine[]
  missing_statement: boolean
  statements: StatementLine[]
  to_pay: DuePayment | null
}

export interface InterestLine {
  key: string
  label: string
  currency: string
  total_cents: number
}

export interface NextDue extends DuePayment {
  key: string
  label: string
}

export interface Interest {
  year: number
  lines: InterestLine[]
  total_dop_cents: number // no incluye los US$ sin tasa
  unconverted_usd_cents: number
  next_due: NextDue | null // el próximo pago con fecha límite de hoy en adelante
}

/** Algo pendiente (`GET /api/pending`): un gasto compartido o un cambio de divisas. */
export interface PendingItem {
  kind: 'shared' | 'exchange'
  fingerprint: string // la del primer gasto del grupo o la de la primera pata: abre su pantalla
  day: string
  merchant: string
  account_label: string
  who: string // «Con quién» del grupo o la nota (recortada); puede ir vacío
  pending_cents: number
  currency: 'DOP' | 'USD'
  pending_dop_cents: number | null // null: en US$ sin ninguna tasa
  age_days: number
  rate: string | null // RD$ por US$ de `pending_dop_cents`: la del cambio o la más reciente
  expense_count: number // gastos del grupo (1 en un cambio)
  parts: CurrencyCents[] // lo pendiente por moneda
}

/** Quién te debe y a quién debes, de todos los meses. En RD$, cada cambio a su propia tasa y
 * los compartidos en US$ a la más reciente (`rate`). */
export interface Pending {
  owed_to_me_dop_cents: number
  i_owe_dop_cents: number
  net_dop_cents: number
  unconverted_usd_cents: { owed_to_me: number; i_owe: number } // US$ sin ninguna tasa
  rate_month: string | null
  rate: Rate | null
  owed_to_me: PendingItem[]
  i_owe: PendingItem[]
}

export type SharedStatus = 'pending' | 'settled' | 'written_off'

/** Un gasto de un grupo en Compartidos: su reparto y si ya está saldado (en su moneda). */
export interface SharedListExpense extends Split {
  fingerprint: string
  day: string
  merchant: string
  account_label: string
  amount_cents: number // el gasto completo (antes de repartir)
  currency: string
  share_cents: number
  reimbursed_cents: number
  pending_cents: number
  written_off_cents: number
}

/** Un reembolso de un grupo: un crédito enlazado o uno anotado a mano. */
export interface SharedListRefund {
  key: string // la huella del crédito o "manual:<id>"
  manual: boolean
  day: string
  description: string // del crédito: comercio; a mano: la persona (puede ir vacío)
  account_label: string // del crédito: su cuenta; a mano: el "dónde" ("" = efectivo)
  amount_cents: number // positivo
  currency: string
}

/** Un grupo en Compartidos (`GET /api/shared`). */
export interface SharedListGroup {
  id: number
  title: string // nombre, si no «Con quién», si no el comercio del primer gasto
  name: string
  with_whom: string
  status: SharedStatus
  first_fingerprint: string // el primer gasto: abre la pantalla del grupo
  first_day: string
  last_day: string
  last_activity: string // el gasto o el reembolso más reciente
  expenses: SharedListExpense[] // del más viejo al más nuevo
  refunds: SharedListRefund[]
  paid: CurrencyCents[] // Σ montos de los gastos
  reimbursed: CurrencyCents[] // Σ reembolsos, por su moneda
  pending: CurrencyCents[] // te deben (vacío si nada)
  pending_dop_cents: number | null // ≈ RD$ de lo pendiente; null sin pendiente o sin tasa
  unconverted_usd_cents: number
  excess: CurrencyCents[] // te devolvieron de más
}

/** Todos los grupos compartidos, de todos los meses, y sus totales. */
export interface SharedList {
  owed_dop_cents: number
  reimbursed_year_dop_cents: number
  year: number
  open_count: number
  unconverted: { owed_usd_cents: number; reimbursed_usd_cents: number } // US$ sin tasa
  rate: Rate | null
  groups: SharedListGroup[] // la última actividad primero
}

export interface EditBody {
  category?: string | null
  category_id?: number
  one_off?: boolean | null
  scope?: 'transaction' | 'merchant'
  note?: string
  shared?: SharedBody | null // null: ya no es compartido
  written_off?: boolean
}

/** PATCH /api/transactions: la categoría («solo esta») de varias a la vez, con un motivo. */
export interface BatchBody {
  fingerprints: string[]
  category_id: number
  reason?: string
}

export type SkipReason = 'vinculo' | 'caja' | 'direccion' | 'sin_cambio' | 'desconocida'

export interface BatchResult {
  applied: string[]
  skipped: { fingerprint: string; reason: SkipReason; message: string }[]
  entry_id: number | null // la entrada de la bitácora (null si nada cambió)
}

export interface RateBody {
  value: string | number
}

export interface PriceChange {
  before_cents: number
  after_cents: number
  day: string
}

export type RecurringStatus = 'activo' | 'inactivo' | 'cancelado' | 'terminado'
export type MarkStatus = 'confirmed' | 'dismissed' | 'cancelled'
export type AlertKind = 'nuevo' | 'subio' | 'cobro_tras_cancelar'

export interface RecurringItem {
  merchant: string
  currency: string
  category: string
  group: string
  cadence: 'mensual' | 'anual'
  status: RecurringStatus
  typical_cents: number // en la moneda original del cargo
  variable: boolean
  monthly_cents: number | null // RD$; null sin tasa para los US$
  yearly_cents: number | null
  first_day: string
  last_day: string
  charges: number
  price_change: PriceChange | null
  installments_left: number | null
  mark: MarkStatus | null
  charged_after_cancel: boolean
  name: string // nombre visible (el del proveedor); `merchant` es la clave con que se marca
  members: string[] // los comercios de la serie (más de uno: se puede «Separar»)
  provider: boolean // un proveedor de la lista
  extras_year_cents: number // préstamos: abonos extra del año, en la moneda del cargo
  group_key: string // clave estable del grupo ('' en Cuotas)
}

export interface GroupTotal {
  group: string
  monthly_cents: number
  yearly_cents: number
  count: number
}

export interface RecurringAlert {
  kind: AlertKind
  merchant: string
  currency: string
  detail: string
  name: string
}

export interface Provider {
  key: string
  name: string
}

export interface Recurring {
  as_of: string | null
  first_month: string | null // mes del primer movimiento
  monthly_cents: number
  groups: GroupTotal[]
  items: RecurringItem[]
  dismissed: RecurringItem[]
  alerts: RecurringAlert[]
  providers: Provider[] // la lista fija (destinos de «Unir con…»)
}

export type RecurringGroupKey =
  | 'vivienda'
  | 'prestamos'
  | 'servicios'
  | 'seguros'
  | 'suscripciones'
  | 'cargos'
  | 'otros'

/** «Es recurrente…» desde una transacción (POST /api/transactions/{huella}/recurring). */
export interface TxRecurringBody {
  cadence: 'mensual' | 'anual'
  group?: RecurringGroupKey | null
  installments_left?: number | null
}

/** Qué es la transacción para Recurrentes (GET /api/transactions/{huella}/recurring). */
export interface TxRecurring {
  eligible: boolean
  reason: string // por qué no se puede marcar ('' si se puede)
  key: string
  name: string
  currency: string
  recurring: boolean // ya aparece en Recurrentes
  mark: MarkStatus | null
  group: string
  loan: boolean // categoría Préstamos: se ofrecen las cuotas
}

/** «Unir con…»: los comercios de la serie `merchant` pasan a la serie `target`. */
export interface JoinBody {
  merchant: string
  target: string
}

/** `installments_left` ausente = no tocar las cuotas; null = borrarlas. */
export interface MarkBody {
  merchant: string
  currency: string
  status: MarkStatus | null
  installments_left?: number | null
  /** «Grupo en Recurrentes»: ausente no lo toca; null vuelve al de la categoría. */
  group?: RecurringGroupKey | null
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const WRITE_METHODS = new Set(['PATCH', 'PUT', 'POST', 'DELETE'])
const NO_CONTENT = 204

/** Pide `path` a la API; los que escriben llevan `X-Finanzas: 1` y cuerpo JSON. Un 204 (sin
 * cuerpo) devuelve `undefined`. */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  headers.set('X-Finanzas', '1')
  if (WRITE_METHODS.has(method)) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, method, headers })
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
  if (response.status === NO_CONTENT) return undefined as T
  return (await response.json()) as T
}

/** Como `request`, pero la respuesta es texto (p. ej. el dossier en Markdown), con sus cabeceras. */
export async function requestText(path: string): Promise<{ text: string; headers: Headers }> {
  const response = await fetch(path, { headers: { 'X-Finanzas': '1' } })
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
  return { text: await response.text(), headers: response.headers }
}

/** Mensaje de error de FastAPI: `detail` de texto, o la lista de validación de pydantic
 * (se unen sus `msg`). Si no hay nada usable, el texto de estado. */
export async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    const message = detailMessage(body.detail)
    if (message) return message
  } catch {
    // La respuesta no era JSON: se usa el texto de estado.
  }
  return response.statusText || `error ${response.status}`
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return null
  const messages = detail
    .map((item: unknown) =>
      typeof item === 'object' && item !== null && 'msg' in item ? item.msg : null,
    )
    .filter((msg): msg is string => typeof msg === 'string' && msg !== '')
  return messages.length ? messages.join('; ') : null
}
