import { type ReactNode, useState } from 'react'
import { Link } from 'react-router'
import { hrefWithSelection, type Selection, transactionsHref } from '@/lib/accountFilter'
import type { Summary } from '@/lib/api'
import { BUILTIN, builtinName, THIRD_PARTY } from '@/lib/categories'
import { FLOW_COLORS } from '@/lib/colors'
import { CASH_BOX_HREF, cashBoxNote } from '@/lib/cashBox'
import { INVESTMENTS_PATH, investedNote } from '@/lib/investments'
import { afterReservesNote, BUDGET_PATH } from '@/lib/budget'
import { useBudgetOverview } from '@/lib/budgetQueries'
import { formatDop, formatUsd } from '@/lib/money'
import { useCategories } from '@/lib/queries'
import {
  netDetail,
  netText,
  netTone,
  NO_FLOW_NOTE,
  ownMovesNote,
  oneOffsText,
  rateNote,
  rateText,
  incomeThroughNote,
  savingsNote,
  savingsText,
  spendingHref,
  thirdPartyHref,
  thirdPartyNote,
  versusHabitual,
} from '@/lib/summary'
import { cn } from '@/lib/utils'
import { RateEditor } from './RateEditor'
import { FOCUS, PANEL, TONE_TEXT } from './styles'

interface KpiProps {
  label: string
  value: string
  valueClass?: string
  /** Color del flujo (ingresos, gastos, terceros): una marca junto al nombre, como la leyenda
   * del gráfico. */
  accent?: string
  children: ReactNode
}

function Kpi({ label, value, valueClass, accent, children }: KpiProps) {
  return (
    <div
      className={cn(
        PANEL,
        '@container flex min-w-0 flex-col gap-2 px-[22px] py-5',
      )}
    >
      <span className="flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground">
        {accent && (
          <span aria-hidden="true" className="size-2 shrink-0 rounded-[3px]" style={{ background: accent }} />
        )}
        {label}
      </span>
      {/* La cifra nunca se parte: se achica con el ancho de la tarjeta (20–32 px). */}
      <span
        className={cn(
          'font-bold whitespace-nowrap tracking-[-0.02em] tabular-nums',
          'text-[clamp(1.25rem,13cqi,2rem)]',
          valueClass,
        )}
      >
        {value}
      </span>
      <div className="text-[13px]">{children}</div>
    </div>
  )
}

/** Frase contra lo habitual; si el mes no se compara, dice por qué. */
function Versus({ amount, summary }: { amount: number; summary: Summary }) {
  if (summary.habitual_cents === null) {
    const why = summary.option.partial
      ? 'Mes incompleto: no se compara'
      : 'Aún no hay meses completos anteriores para comparar'
    return <span className="text-muted-foreground">{why}</span>
  }
  const diff = versusHabitual(amount, summary.habitual_cents)
  return (
    <span className={cn(diff.tone === 'same' ? 'text-ink-2' : [TONE_TEXT[diff.tone], 'font-semibold'])}>
      {diff.text.replace(/RD\$ /g, 'RD$\u00a0')}
    </span>
  )
}

/** Evita que "RD$ 134,900" o "tasa de agosto" se partan al final de una línea. */
function keepTogether(text: string): string {
  return text.replaceAll(' ', '\u00a0')
}

const INLINE_ACTION = cn(
  'relative font-semibold text-primary hover:text-secondary-foreground',
  // Área táctil de 44 px sin mover el texto.
  'before:absolute before:-inset-x-2 before:-inset-y-3.5 before:content-[""]',
  FOCUS,
  'rounded-sm',
)

interface SectionProps {
  summary: Summary
  selection: Selection
}

function OneOffs({ summary, selection }: SectionProps) {
  const where = oneOffsText(summary.categories)
  if (where === null) return <span className="text-muted-foreground">Ninguno este mes</span>
  const href = transactionsHref({ mes: summary.option.month }, selection)
  return (
    <Link to={href} className={cn(INLINE_ACTION, 'no-underline')}>
      {where} · ver
    </Link>
  )
}

function ThirdParty({ summary, selection }: SectionProps) {
  const categories = useCategories()
  const name = builtinName(categories.data ?? [], BUILTIN.thirdParty, THIRD_PARTY)
  const note = thirdPartyNote(summary.third_party_cents)
  if (summary.third_party_cents === 0) return <span className="text-muted-foreground">{note}</span>
  return (
    <span className="text-ink-2">
      {note} ·{' '}
      <Link
        to={thirdPartyHref(summary.option.month, selection, name)}
        aria-label="Ver transferencias a terceros"
        className={cn(INLINE_ACTION, 'no-underline')}
      >
        ver
      </Link>
    </span>
  )
}

function Dollars({ summary, onEdit }: { summary: Summary; onEdit: () => void }) {
  const { rate, usd_in_dop_cents: inDop } = summary
  const edit = (
    <button type="button" onClick={onEdit} className={INLINE_ACTION}>
      editar tasa
    </button>
  )
  if (summary.usd_cents === 0) {
    return (
      <span className="text-muted-foreground">
        Sin compras en dólares{rate && ` · tasa ${rateText(rate.value)}`} · {edit}
      </span>
    )
  }
  if (rate === null || inDop === null) {
    return (
      <span className="text-up">
        <span className="font-semibold">Sin tasa: los US$ no están en el total</span> · {edit}
      </span>
    )
  }
  const note = rateNote(rate, summary.option.month)
  return (
    <span className="text-ink-2">
      ≈ {keepTogether(formatDop(inDop))} a {rateText(rate.value)}
      {note && <span className="font-semibold text-up"> · {keepTogether(note)}</span>} · {edit}
    </span>
  )
}

const INCOME_LINES = 3

function IncomeNote({ summary, selection }: SectionProps) {
  const through = incomeThroughNote(summary.income_through)
  const cut = through && <span className="text-muted-foreground">{keepTogether(through)} · </span>
  if (summary.income_cents <= 0) {
    return (
      <span className="text-muted-foreground">
        {cut}
        Sin ingresos este mes
      </span>
    )
  }
  const href = transactionsHref({ mes: summary.option.month, tipo: 'ingresos' }, selection)
  return (
    <span className="flex flex-col gap-2">
      <span>
        {cut}
        <Link to={href} className={cn(INLINE_ACTION, 'no-underline')}>
          Ver de dónde vino
        </Link>
      </span>
      <IncomeLines summary={summary} selection={selection} />
    </span>
  )
}

/** Los ingresos por categoría (las 3 mayores, una por línea: «Salario RD$ 85,000», «Cripto
 * RD$ 15,000»), cada una con su enlace a Transacciones; «Cripto» va aparte de «Otros ingresos». */
function IncomeLines({ summary, selection }: SectionProps) {
  const lines = summary.incomes ?? []
  if (lines.length === 0) return null
  const shown = lines.slice(0, INCOME_LINES)
  const rest = lines.length - shown.length
  return (
    <span data-testid="income-lines" className="flex flex-col gap-0.5 text-ink-2">
      {shown.map((line) => (
        <Link
          key={line.category}
          to={transactionsHref(
            { mes: summary.option.month, tipo: 'ingresos', categoria: line.category },
            selection,
          )}
          className="truncate text-ink-2 no-underline hover:underline"
        >
          {line.category} {formatDop(line.amount_cents).replace('RD$ ', 'RD$\u00a0')}
        </Link>
      ))}
      {rest > 0 && <span className="text-muted-foreground">y {rest} más</span>}
    </span>
  )
}

/** Bajo «Gastos»: la comparación con lo habitual y, debajo, el enlace a en qué se gastó. */
function SpendingNote({ summary, selection }: SectionProps) {
  const versus = <Versus amount={summary.total_cents} summary={summary} />
  if (summary.total_cents <= 0) return versus
  return (
    <span className="flex flex-col gap-2">
      {versus}
      <span>
        <Link to={spendingHref(summary.option.month, selection)} className={cn(INLINE_ACTION, 'no-underline')}>
          Ver en qué se gastó
        </Link>
      </span>
    </span>
  )
}

function SavingsNote({ summary }: { summary: Summary }) {
  if (summary.needs_income) return <span className="text-muted-foreground">{NO_FLOW_NOTE}</span>
  const text = savingsNote(summary.savings_rate, summary.income_through)
  const muted = summary.savings_rate === null || summary.income_through !== null
  return <span className={muted ? 'text-muted-foreground' : 'text-ink-2'}>{text}</span>
}

function NetNote({ summary, selection }: SectionProps) {
  if (summary.net_cents === null) {
    return <span className="text-muted-foreground">{NO_FLOW_NOTE}</span>
  }
  const tone = netTone(summary.net_cents)
  return (
    <span className="flex flex-col gap-2">
      <span className={tone === 'up' ? 'font-semibold text-up' : 'text-ink-2'}>
        {netDetail(summary.net_cents, summary.third_party_cents).replace(/RD\$ /g, 'RD$\u00a0')}
      </span>
      <KeptNote
        testId="invested-note"
        note={investedNote(summary.invested_cents)}
        to={hrefWithSelection(INVESTMENTS_PATH, {}, selection)}
      />
      <KeptNote
        testId="cash-box-note"
        note={cashBoxNote(summary.cash_box_cents)}
        to={CASH_BOX_HREF}
      />
      <ReservesNote summary={summary} selection={selection} />
    </span>
  )
}

/** «después de apartar para tus reservas (RD$ X/mes): RD$ Y» (informativa: el número principal
 * no cambia), con enlace a Presupuesto. */
function ReservesNote({ summary, selection }: SectionProps) {
  const overview = useBudgetOverview(summary.option.month, selection)
  const note = afterReservesNote(summary.net_cents, overview.data?.monthly_cents ?? 0)
  return (
    <KeptNote
      testId="reserves-note"
      note={note}
      to={hrefWithSelection(BUDGET_PATH, {}, selection)}
    />
  )
}

interface KeptNoteProps {
  testId: string
  note: string | null
  to: string
}

/** «de eso, RD$ X fueron a inversiones» (enlace a Inversiones con las cuentas elegidas) o «… a la
 * caja fuerte» (enlace a Cuentas): un aporte o un retiro guardado no resta de lo que te quedó. */
function KeptNote({ testId, note, to }: KeptNoteProps) {
  if (note === null) return null
  return (
    <span data-testid={testId} className="text-ink-2">
      <Link to={to} className={cn(INLINE_ACTION, 'no-underline')}>
        {note.replace(/RD\$ /g, 'RD$\u00a0')}
      </Link>
    </span>
  )
}

/** Con algunas cuentas elegidas: lo que salió de ellas hacia otras cuentas tuyas. */
function OwnMoves({ summary }: { summary: Summary }) {
  const note = ownMovesNote(summary.to_cards_cents, summary.to_own_cents)
  if (note === null) return null
  return (
    <p className="text-[13px] text-ink-2">
      {note.replace(/RD\$ /g, 'RD$\u00a0')}{' '}
      <span className="text-muted-foreground">· no se resta: sigue siendo tu dinero</span>
    </p>
  )
}

interface StatProps {
  label: string
  value: string
  accent?: string
  children: ReactNode
}

/** Una cifra de la franja secundaria: nombre, cifra y su nota en la misma línea si caben. */
function Stat({ label, value, accent, children }: StatProps) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 bg-card px-4 py-2.5">
      <span className="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
        {accent && (
          <span aria-hidden="true" className="size-2 shrink-0 rounded-[3px]" style={{ background: accent }} />
        )}
        {label}
      </span>
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-[15px] font-bold whitespace-nowrap tabular-nums">{value}</span>
        <span className="text-[12.5px]">{children}</span>
      </div>
    </div>
  )
}

/** Flujo del mes (ingresos, gastos, lo que quedó y el % ahorrado) y, debajo, una franja fina
 * con el detalle: sin gastos únicos, gastos únicos, transferencias a terceros y en dólares. Los enlaces a
 * Transacciones llevan las cuentas elegidas. */
export function Kpis({ summary, selection = null }: { summary: Summary; selection?: Selection }) {
  const [editing, setEditing] = useState(false)
  const tone = summary.net_cents === null ? 'good' : netTone(summary.net_cents)
  return (
    <section aria-label="Indicadores" className="flex flex-col gap-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <Kpi label="Ingresos" value={formatDop(summary.income_cents)} accent={FLOW_COLORS.income.strong}>
          <IncomeNote summary={summary} selection={selection} />
        </Kpi>
        <Kpi label="Gastos" value={formatDop(summary.total_cents)} accent={FLOW_COLORS.expense.strong}>
          <SpendingNote summary={summary} selection={selection} />
        </Kpi>
        <Kpi
          label="Te quedó"
          value={netText(summary.net_cents)}
          valueClass={
            summary.net_cents === null ? 'text-muted-foreground' : tone === 'up' ? 'text-up' : 'text-primary'
          }
        >
          <NetNote summary={summary} selection={selection} />
        </Kpi>
        <Kpi label="% ahorrado" value={savingsText(summary.savings_rate)}>
          <SavingsNote summary={summary} />
        </Kpi>
      </div>
      <div
        role="group"
        aria-label="Detalle del mes"
        className="grid grid-cols-1 gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-2 xl:grid-cols-4"
      >
        <Stat label="Sin gastos únicos" value={formatDop(summary.regular_total_cents)}>
          <Versus amount={summary.regular_total_cents} summary={summary} />
        </Stat>
        <Stat label="Gastos únicos" value={formatDop(summary.one_offs_cents)}>
          <OneOffs summary={summary} selection={selection} />
        </Stat>
        <Stat
          label="Transferencias a terceros"
          value={formatDop(summary.third_party_cents)}
          accent={FLOW_COLORS.transfer.strong}
        >
          <ThirdParty summary={summary} selection={selection} />
        </Stat>
        <Stat label="En dólares" value={formatUsd(summary.usd_cents)}>
          {editing ? (
            <RateEditor
              key={summary.option.month}
              month={summary.option.month}
              current={summary.rate?.value ?? null}
              onClose={() => setEditing(false)}
            />
          ) : (
            <Dollars summary={summary} onEdit={() => setEditing(true)} />
          )}
        </Stat>
      </div>
      <OwnMoves summary={summary} />
    </section>
  )
}
