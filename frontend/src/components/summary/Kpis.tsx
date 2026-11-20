import { type ReactNode, useState } from 'react'
import { Link } from 'react-router'
import { t } from '@/i18n'
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
  provisionalNote,
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
  /** Colour of the flow (income, spending, third parties): a mark next to the name, like the
   * chart legend. */
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
      {/* The figure never wraps: it shrinks with the card width (20–32 px). */}
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

/** Sentence against the usual; when the month is not compared, it says why. */
function Versus({ amount, summary }: { amount: number; summary: Summary }) {
  if (summary.habitual_cents === null) {
    const why = summary.option.partial
      ? t('summary.kpi.partialMonth')
      : t('summary.kpi.noPreviousMonths')
    return <span className="text-muted-foreground">{why}</span>
  }
  const diff = versusHabitual(amount, summary.habitual_cents)
  return (
    <span className={cn(diff.tone === 'same' ? 'text-ink-2' : [TONE_TEXT[diff.tone], 'font-semibold'])}>
      {diff.text.replace(/RD\$ /g, 'RD$\u00a0')}
    </span>
  )
}

/** Keeps "RD$ 134,900" or "August rate" from breaking at the end of a line. */
function keepTogether(text: string): string {
  return text.replaceAll(' ', '\u00a0')
}

const INLINE_ACTION = cn(
  'relative font-semibold text-primary hover:text-secondary-foreground',
  // 44 px touch area without moving the text.
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
  if (where === null) return <span className="text-muted-foreground">{t('summary.kpi.noneThisMonth')}</span>
  const href = transactionsHref({ month: summary.option.month }, selection)
  return (
    <Link to={href} className={cn(INLINE_ACTION, 'no-underline')}>
      {t('summary.kpi.oneOffsLink', { where })}
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
        aria-label={t('summary.kpi.thirdPartyLinkLabel')}
        className={cn(INLINE_ACTION, 'no-underline')}
      >
        {t('summary.kpi.see')}
      </Link>
    </span>
  )
}

function Dollars({ summary, onEdit }: { summary: Summary; onEdit: () => void }) {
  const { rate, usd_in_dop_cents: inDop } = summary
  const edit = (
    <button type="button" onClick={onEdit} className={INLINE_ACTION}>
      {t('summary.kpi.editRate')}
    </button>
  )
  if (summary.usd_cents === 0) {
    return (
      <span className="text-muted-foreground">
        {t('summary.kpi.noDollarPurchases')}
        {rate && t('summary.kpi.rateSuffix', { rate: rateText(rate.value) })} · {edit}
      </span>
    )
  }
  if (rate === null || inDop === null) {
    return (
      <span className="text-up">
        <span className="font-semibold">{t('summary.kpi.noRate')}</span> · {edit}
      </span>
    )
  }
  const note = rateNote(rate, summary.option.month)
  return (
    <span className="text-ink-2">
      {t('summary.kpi.inDop', { amount: keepTogether(formatDop(inDop)), rate: rateText(rate.value) })}
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
        {t('summary.kpi.noIncome')}
      </span>
    )
  }
  const href = transactionsHref({ month: summary.option.month, kind: 'income' }, selection)
  return (
    <span className="flex flex-col gap-2">
      <span>
        {cut}
        <Link to={href} className={cn(INLINE_ACTION, 'no-underline')}>
          {t('summary.kpi.incomeLink')}
        </Link>
      </span>
      <IncomeLines summary={summary} selection={selection} />
    </span>
  )
}

/** Income by category (the 3 largest, one per line: "Salary RD$ 85,000", "Crypto RD$ 15,000"),
 * each with its link to Transactions; "Crypto" goes apart from "Other income". */
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
            { month: summary.option.month, kind: 'income', category: line.category },
            selection,
          )}
          className="truncate text-ink-2 no-underline hover:underline"
        >
          {line.category} {formatDop(line.amount_cents).replace('RD$ ', 'RD$\u00a0')}
        </Link>
      ))}
      {rest > 0 && <span className="text-muted-foreground">{t('summary.kpi.andMore', { count: rest })}</span>}
    </span>
  )
}

/** Under "Spending": the comparison with the usual and, below, the link to what it was spent on. */
function SpendingNote({ summary, selection }: SectionProps) {
  const versus = <Versus amount={summary.total_cents} summary={summary} />
  if (summary.total_cents <= 0) return versus
  return (
    <span className="flex flex-col gap-2">
      {versus}
      <ProvisionalLine cents={summary.provisional_cents} />
      <span>
        <Link to={spendingHref(summary.option.month, selection)} className={cn(INLINE_ACTION, 'no-underline')}>
          {t('summary.kpi.spendingLink')}
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

/** "after setting aside for your reserves (RD$ X/month): RD$ Y" (informative: the main figure does
 * not change), with a link to Budget. */
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

/** How much is still without a statement (only when part of the month comes from bank alerts). */
export function ProvisionalLine({ cents }: { cents: number }) {
  const note = provisionalNote(cents)
  if (note === null) return null
  return (
    <span data-testid="provisional-total" className="text-[13px] text-ink-2">
      {note.replace(/RD\$ /g, 'RD$\u00a0')}
    </span>
  )
}

interface KeptNoteProps {
  testId: string
  note: string | null
  to: string
}

/** "of that, RD$ X went to investments" (link to Investments with the chosen accounts) or "… to the
 * cash box" (link to Accounts): a contribution or a stored withdrawal does not subtract from what
 * you kept. */
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

/** With some accounts chosen: what left them for other accounts of yours. */
function OwnMoves({ summary }: { summary: Summary }) {
  const note = ownMovesNote(summary.to_cards_cents, summary.to_own_cents)
  if (note === null) return null
  return (
    <p className="text-[13px] text-ink-2">
      {note.replace(/RD\$ /g, 'RD$\u00a0')}{' '}
      <span className="text-muted-foreground">{t('summary.kpi.ownMovesNote')}</span>
    </p>
  )
}

interface StatProps {
  label: string
  value: string
  accent?: string
  children: ReactNode
}

/** A figure of the secondary strip: name, figure and its note on the same line when they fit. */
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

/** The month's flow (income, spending, what was left and the % saved) and, below, a thin strip
 * with the detail: without one-off expenses, one-off expenses, third-party transfers and in
 * dollars. The links to Transactions carry the chosen accounts. */
export function Kpis({ summary, selection = null }: { summary: Summary; selection?: Selection }) {
  const [editing, setEditing] = useState(false)
  const tone = summary.net_cents === null ? 'good' : netTone(summary.net_cents)
  return (
    <section aria-label={t('summary.kpi.sectionLabel')} className="flex flex-col gap-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <Kpi label={t('summary.kpi.income')} value={formatDop(summary.income_cents)} accent={FLOW_COLORS.income.strong}>
          <IncomeNote summary={summary} selection={selection} />
        </Kpi>
        <Kpi label={t('summary.kpi.spending')} value={formatDop(summary.total_cents)} accent={FLOW_COLORS.expense.strong}>
          <SpendingNote summary={summary} selection={selection} />
        </Kpi>
        <Kpi
          label={t('summary.kpi.net')}
          value={netText(summary.net_cents)}
          valueClass={
            summary.net_cents === null ? 'text-muted-foreground' : tone === 'up' ? 'text-up' : 'text-primary'
          }
        >
          <NetNote summary={summary} selection={selection} />
        </Kpi>
        <Kpi label={t('summary.kpi.savings')} value={savingsText(summary.savings_rate)}>
          <SavingsNote summary={summary} />
        </Kpi>
      </div>
      <div
        role="group"
        aria-label={t('summary.kpi.detailLabel')}
        className="grid grid-cols-1 gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-2 xl:grid-cols-4"
      >
        <Stat label={t('summary.kpi.regular')} value={formatDop(summary.regular_total_cents)}>
          <Versus amount={summary.regular_total_cents} summary={summary} />
        </Stat>
        <Stat label={t('summary.kpi.oneOffs')} value={formatDop(summary.one_offs_cents)}>
          <OneOffs summary={summary} selection={selection} />
        </Stat>
        <Stat
          label={t('summary.kpi.thirdParty')}
          value={formatDop(summary.third_party_cents)}
          accent={FLOW_COLORS.transfer.strong}
        >
          <ThirdParty summary={summary} selection={selection} />
        </Stat>
        <Stat label={t('summary.kpi.dollars')} value={formatUsd(summary.usd_cents)}>
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
