// Grupos compartidos, reembolsos y cambios de divisas en la interfaz (lógica pura). Las
// cuentas las hace el servidor (src/finanzas/analysis/shared.py y exchanges.py); aquí solo se
// arman textos, insignias y cuerpos de los pedidos.
import type {
  CurrencyCents,
  ExchangeInfo,
  GroupExpense,
  GroupRef,
  InvestmentRole,
  SharedTotal,
  LinkedTx,
  SharedInfo,
  Split,
  SplitBody,
  Tx,
} from './api'
import { formatDop, formatUsd } from './money'
import { monthName } from './months'

/** Monto en su moneda: RD$ sin decimales, US$ con dos. */
export function formatMoney(cents: number, currency: string): string {
  return currency === 'USD' ? formatUsd(cents) : formatDop(cents)
}

/** "2026-02-13" → "13 de febrero". */
export function shortDay(iso: string): string {
  return `${Number(iso.slice(8, 10))} de ${monthName(iso.slice(0, 7))}`
}

/** Montos en varias monedas: "RD$ 3,000 + US$ 120.00". Sin los que están en cero, salvo que
 * todos lo estén ("RD$ 0"). */
export function moneyList(parts: readonly CurrencyCents[]): string {
  const shown = parts.filter((p) => p.cents !== 0)
  if (shown.length === 0) return formatMoney(0, parts[0]?.currency ?? 'DOP')
  return shown.map((p) => formatMoney(p.cents, p.currency)).join(' + ')
}

/** Cómo se repartió un gasto: "Éramos 3", "Mi parte: RD$ 400", "Lo pagaste por otra persona". */
export function splitText(split: Split, currency: string): string {
  if (split.for_other) return 'Lo pagaste por otra persona'
  if (split.people !== null) return `Éramos ${split.people}`
  return `Mi parte: ${formatMoney(split.my_share_cents ?? 0, currency)}`
}

/** "Tu parte RD$ 617 · Devuelto RD$ 617 · Te deben RD$ 617" (cada cifra, por moneda). */
export interface SharedStat {
  label: string
  value: string
}

function byCurrency(totals: readonly SharedTotal[], pick: (t: SharedTotal) => number): string {
  return moneyList(totals.map((t) => ({ currency: t.currency, cents: pick(t) })))
}

/** Tu parte, lo devuelto y lo pendiente (o lo que no te van a pagar) del grupo, por moneda. */
export function sharedStats(group: SharedInfo): SharedStat[] {
  const totals = group.totals
  return [
    { label: 'Tu parte', value: byCurrency(totals, (t) => t.share_cents) },
    { label: 'Devuelto', value: byCurrency(totals, (t) => t.reimbursed_cents) },
    group.written_off
      ? { label: 'No pagarán', value: byCurrency(totals, (t) => t.written_off_cents) }
      : { label: 'Te deben', value: byCurrency(totals, (t) => t.pending_cents) },
  ]
}

/** Estado de un gasto del grupo tras imputar los reembolsos (del más viejo al más nuevo). */
export function expenseStatus(expense: GroupExpense): string {
  if (expense.written_off_cents > 0) {
    return `No pagarán ${formatMoney(expense.written_off_cents, expense.currency)}`
  }
  if (expense.pending_cents === 0) return 'Saldado'
  return `Pendiente ${formatMoney(expense.pending_cents, expense.currency)}`
}

/** Aviso si te devolvieron más de lo que te debían en todo el grupo: el exceso no cuenta;
 * suele ser un reembolso repetido. */
export function overWarning(group: SharedInfo): string | null {
  if (group.excess.length === 0) return null
  return `Te devolvieron ${moneyList(group.excess)} más de lo que te debían: eso no cuenta. ¿Hay un reembolso repetido (uno a mano y el mismo importado)? Quita uno.`
}

/** Aviso si algún reembolso no cuenta (o no del todo) por falta de la tasa de su mes. */
export function unconvertedWarning(group: SharedInfo): string | null {
  const n = group.unconverted.length
  if (n === 0) return null
  const which = n === 1 ? 'Un reembolso no cuenta' : `${n} reembolsos no cuentan`
  return `${which} (o no del todo): falta la tasa de su mes para pasarlo a la moneda del gasto.`
}

/** "Carola y Rafael · te deben US$ 912.37" (o "· saldado"). */
export function groupLabel(group: GroupRef): string {
  const owed = group.pending.length ? `te deben ${moneyList(group.pending)}` : 'saldado'
  return `${group.title} · ${owed}`
}

/** "1 gasto", "3 gastos". */
export function expenseCount(n: number): string {
  return count(n, 'gasto', 'gastos')
}

export interface LinkBadge {
  label: string
  tone: 'shared' | 'linked' | 'suggested'
}

/** Insignias de vínculos de una fila: compartido (con lo que te deben), reembolso o cambio, y
 * sus sugerencias. */
export function linkBadges(tx: Tx): LinkBadge[] {
  const badges: LinkBadge[] = []
  if (tx.link === 'shared' && tx.shared) {
    badges.push({ label: 'Compartido', tone: 'shared' })
    if (tx.pending_cents > 0) {
      badges.push({ label: `te deben ${formatMoney(tx.pending_cents, tx.currency)}`, tone: 'shared' })
    }
  }
  if (tx.link === 'reimbursement') badges.push({ label: 'Reembolso', tone: 'linked' })
  if (tx.suggested_group) badges.push({ label: '¿Reembolso?', tone: 'suggested' })
  if (tx.link === 'exchange') badges.push({ label: 'Cambio', tone: 'linked' })
  if (tx.suggested_exchange_with) badges.push({ label: '¿Cambio?', tone: 'suggested' })
  if (tx.link === 'investment') badges.push({ label: 'Inversión', tone: 'linked' })
  if (tx.suggested_investment) badges.push({ label: '¿Inversión?', tone: 'suggested' })
  if (tx.link === 'reserve') badges.push({ label: 'Reserva', tone: 'linked' })
  return badges
}

/** "CAFE FICTICIO (1 de enero)": otra transacción, para las preguntas y listas. */
export function linkedLabel(linked: LinkedTx): string {
  return `${linked.merchant} (${shortDay(linked.day)})`
}

/** Monto de otra transacción, con "+" si entra dinero; un crédito en la otra moneda del gasto
 * lleva lo que vale en ella ("+RD$ 600 ≈ US$ 10.00") o "sin tasa". */
export function linkedAmount(linked: LinkedTx): string {
  const text = formatMoney(Math.abs(linked.amount_cents), linked.currency)
  const signed = linked.amount_cents < 0 ? `+${text}` : text
  if (!linked.converted_currency) return signed
  if (linked.converted_cents == null) return `${signed} · sin tasa del mes`
  return `${signed} ≈ ${formatMoney(linked.converted_cents, linked.converted_currency)}`
}

/** Tasa con dos decimales: "62.5000" → "62.50". */
export function rateLabel(rate: string): string {
  const value = Number(rate)
  return Number.isFinite(value) ? value.toFixed(2) : rate
}

/** "Cambio: RD$ 120,000 ↔ US$ 1,500.00 · tasa 62.50 · pendiente US$ 420.00 ≈ RD$ 26,250". El
 * lado base va primero. */
export function exchangeLine(exchange: ExchangeInfo): string {
  const total = (currency: string) =>
    exchange.totals.find((t) => t.currency === currency)?.cents ?? 0
  const other = exchange.base === 'DOP' ? 'USD' : 'DOP'
  const sides = `${formatMoney(total(exchange.base), exchange.base)} ↔ ${formatMoney(total(other), other)}`
  const parts = [`Cambio: ${sides}`, `tasa ${rateLabel(exchange.rate)}`]
  if (exchange.closed) parts.push('completo')
  else if (exchange.pending_cents === 0) parts.push('sin pendiente')
  else {
    const pending = formatMoney(exchange.pending_cents, exchange.pending_currency)
    parts.push(
      exchange.pending_currency === 'DOP'
        ? `pendiente ${pending}`
        : `pendiente ${pending} ≈ ${formatDop(exchange.pending_dop_cents)}`,
    )
  }
  return parts.join(' · ')
}

/** "1,850.50" o "1850,5" → centavos; null si no es un monto positivo con hasta 2 decimales. */
export function parseCents(text: string): number | null {
  const clean = text.trim().replace(/^(RD|US)?\$\s*/i, '').replaceAll(',', '')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  const cents = Math.round(Number(clean) * 100)
  return cents > 0 ? cents : null
}

/** Cómo se reparte en el formulario del detalle. */
export type SplitMode = 'people' | 'share' | 'other'

export interface SplitDraft {
  mode: SplitMode
  people: string
  share: string
}

/** El borrador de un reparto: el de `split` (un gasto ya repartido, o el último agregado al
 * grupo, que se propone al sumar otro) o "Éramos 2". */
export function splitDraftOf(split: Split | null): SplitDraft {
  if (split === null) return { mode: 'people', people: '2', share: '' }
  const mode: SplitMode = split.for_other ? 'other' : split.people !== null ? 'people' : 'share'
  return {
    mode,
    people: String(split.people ?? 2),
    share: split.my_share_cents === null ? '' : (split.my_share_cents / 100).toFixed(2),
  }
}

/** Cuerpo del reparto, o el error que se muestra si el formulario no sirve. `amountCents`: el
 * monto del gasto (tu parte no puede pasarlo). */
export function sharedBody(
  draft: SplitDraft,
  amountCents: number,
): { body: SplitBody } | { error: string } {
  if (draft.mode === 'other') return { body: { for_other: true } }
  if (draft.mode === 'people') {
    const people = Number(draft.people)
    if (!Number.isInteger(people) || people < 2 || people > 100) {
      return { error: 'Pon cuántos eran: de 2 a 100' }
    }
    return { body: { people } }
  }
  const cents = parseCents(draft.share)
  if (cents === null) return { error: 'Pon tu parte: un monto mayor que 0' }
  if (cents > amountCents) return { error: 'Tu parte no puede pasar el gasto' }
  return { body: { my_share_cents: cents } }
}


/** El monto del estado (antes de repartir) de una fila. */
export function grossCents(tx: Tx): number {
  return tx.gross_cents ?? tx.amount_cents
}

/** ¿Va la sección Compartido? Un gasto que se puede compartir o uno ya marcado (aunque el
 * vínculo esté dormido: deja de compartirlo). */
export function showShared(tx: Tx): boolean {
  return tx.can_share || tx.link === 'shared'
}

/** ¿Va la sección Reembolso? Un crédito que puede serlo (reglas del servidor) o uno enlazado. */
export function showReimbursement(tx: Tx): boolean {
  return tx.can_reimburse || tx.link === 'reimbursement'
}

/** ¿Va la sección Cambio de divisas? */
export function showExchange(tx: Tx): boolean {
  return tx.can_exchange || tx.link === 'exchange'
}

/** ¿Va la sección Inversión? Un débito o un crédito bancario que puede serlo, o uno ya en una
 * inversión. */
export function showInvestment(tx: Tx): boolean {
  return tx.can_invest || tx.can_invest_credit || tx.link === 'investment'
}

/** Un crédito, una pata, un movimiento de una inversión o de la caja fuerte: su categoría la
 * define el vínculo. */
export function categoryLocked(tx: Tx): boolean {
  return (
    tx.link === 'reimbursement' ||
    tx.link === 'exchange' ||
    tx.link === 'investment' ||
    tx.link === 'cash_box'
  )
}

/** Conjunto nuevo con `key` agregada o quitada. */
export function toggled(current: ReadonlySet<string>, key: string): ReadonlySet<string> {
  const next = new Set(current)
  if (!next.delete(key)) next.add(key)
  return next
}

/** Qué vínculo resume una línea del panel. */
export type SummaryKind = 'shared' | 'reimbursement' | 'exchange' | 'investment'

/** Una línea del panel del detalle: el estado del vínculo y el botón que abre su pantalla. */
export interface LinkSummary {
  kind: SummaryKind
  title: string
  text: string
  action: 'Gestionar…' | 'Compartir…' | 'Es una inversión…' | 'Es de una inversión…'
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}

function sharedSummary(tx: Tx): LinkSummary {
  const base = { kind: 'shared', title: 'Compartido', action: 'Gestionar…' } as const
  const shared = tx.shared
  if (shared === null) {
    if (tx.link === 'shared') return { ...base, text: 'Estaba compartido, pero ya no es un gasto' }
    return {
      ...base,
      text: 'Cuenta solo tu parte; lo demás queda como «te deben»',
      action: 'Compartir…',
    }
  }
  const refunds = count(shared.reimbursements.length + shared.manual.length, 'reembolso', 'reembolsos')
  const lost = shared.totals.map((t) => ({ currency: t.currency, cents: t.written_off_cents }))
  const owed = shared.written_off
    ? `no te pagarán ${moneyList(lost)}`
    : shared.pending.length
      ? `te deben ${moneyList(shared.pending)}`
      : 'saldado'
  return { ...base, text: `Parte de ${shared.title} · ${owed} · ${refunds}` }
}

function reimbursementSummary(tx: Tx): LinkSummary {
  const base = { kind: 'reimbursement', title: 'Reembolso', action: 'Gestionar…' } as const
  if (tx.link !== 'reimbursement') return { ...base, text: '¿Es reembolso de un gasto compartido?' }
  if (tx.shared) return { ...base, text: `Es reembolso de ${groupLabel(tx.shared)}` }
  const of = tx.reimbursement_of
  return {
    ...base,
    text: of ? `Es reembolso de ${linkedLabel(of)}` : 'Reembolso de un gasto que ya no aparece',
  }
}

function exchangeSummary(tx: Tx): LinkSummary {
  const base = { kind: 'exchange', title: 'Cambio de divisas', action: 'Gestionar…' } as const
  const exchange = tx.exchange
  if (exchange === null) {
    if (tx.link === 'exchange') return { ...base, text: 'Cambio incompleto: le falta una pata' }
    return { ...base, text: '¿Es un cambio de divisas?' }
  }
  if (exchange.closed) return { ...base, text: 'Cambio: completo' }
  if (exchange.pending_cents === 0) return { ...base, text: 'Cambio: sin pendiente' }
  const pending = formatMoney(exchange.pending_cents, exchange.pending_currency)
  return { ...base, text: `Cambio: pendiente ${pending}` }
}

/** Tipo de un movimiento en su inversión: "Aporte", "Rendimiento", "Devolución de capital" o
 * "Mixto". */
export const ROLE_LABELS: Record<InvestmentRole, string> = {
  contribution: 'Aporte',
  return: 'Rendimiento',
  capital: 'Devolución de capital',
  mixed: 'Mixto',
}

function investmentSummary(tx: Tx): LinkSummary {
  const base = { kind: 'investment', title: 'Inversión', action: 'Gestionar…' } as const
  const investment = tx.investment
  if (investment === null) {
    if (tx.link === 'investment') return { ...base, text: 'De una inversión sin aportes a la vista' }
    if (tx.can_invest) {
      return {
        ...base,
        text: 'Dinero que mandaste para que lo inviertan: no resta de lo que te quedó',
        action: 'Es una inversión…',
      }
    }
    return {
      ...base,
      text: '¿Es un rendimiento o capital que te devuelven?',
      action: 'Es de una inversión…',
    }
  }
  const role = tx.investment_role === '' ? 'Movimiento' : ROLE_LABELS[tx.investment_role]
  return { ...base, text: `${role} de ${investment.title}` }
}

/** Las líneas de vínculos del panel (compartido, reembolso, cambio, inversión), en ese orden;
 * cada una abre la pantalla del vínculo. */
export function linkSummaries(tx: Tx): LinkSummary[] {
  const found: LinkSummary[] = []
  if (showShared(tx)) found.push(sharedSummary(tx))
  if (showReimbursement(tx)) found.push(reimbursementSummary(tx))
  if (showExchange(tx)) found.push(exchangeSummary(tx))
  if (showInvestment(tx)) found.push(investmentSummary(tx))
  return found
}

/** Ruta de la pantalla de vínculos de una transacción. */
export function linkPagePath(fingerprint: string): string {
  return `/transacciones/${encodeURIComponent(fingerprint)}`
}

/** Pantallas que abren la de un vínculo y a las que «Volver» regresa tal cual: la lista de
 * Transacciones, Pendientes, Compartidos e Inversiones. */
function isListPath(from: unknown): from is string {
  return (
    typeof from === 'string' &&
    /^\/(transacciones|pendientes|compartidos|inversiones)(\?|$)/.test(from)
  )
}

/** «Volver» sin la transacción (no existe o no cargó): la lista (o Pendientes) de la que se
 * vino o, si no, Transacciones. */
export function listPath(from: unknown): string {
  return isListPath(from) ? from : '/transacciones'
}

/** A dónde vuelve «Volver»: la lista de Transacciones (o Pendientes) de la que se vino o, si
 * se entró directo, el mes de la transacción con ella elegida. */
export function backPath(tx: Pick<Tx, 'fingerprint' | 'day'>, from: unknown): string {
  if (isListPath(from)) return from
  const params = new URLSearchParams({ mes: tx.day.slice(0, 7), tx: tx.fingerprint })
  return `/transacciones?${params.toString()}`
}
