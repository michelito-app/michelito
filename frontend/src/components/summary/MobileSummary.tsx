import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { t } from '@/i18n'
import { hrefWithSelection, type AccountRef, includesCard, type Selection } from '@/lib/accountFilter'
import type { Summary } from '@/lib/api'
import { BUDGET_PATH, overviewText } from '@/lib/budget'
import { useBudgetOverview } from '@/lib/budgetQueries'
import { formatDop } from '@/lib/money'
import { useOpenSections } from '@/lib/openSections'
import { pendingHref } from '@/lib/pending'
import { usePending } from '@/lib/queries'
import { netDetail, netText, netTone, savingsText, spendingHref, versusHabitual } from '@/lib/summary'
import { transactionsHref } from '@/lib/accountFilter'
import { cn } from '@/lib/utils'
import { BudgetCard } from './BudgetCard'
import { ByAccount } from './ByAccount'
import { CategoryTable } from './CategoryTable'
import { InterestCard } from './InterestCard'
import { Kpis } from './Kpis'
import { MonthReading } from './MonthReading'
import { PendingCard } from './PendingCard'
import { RecurringCard } from './RecurringCard'
import { ReviewCard } from './ReviewCard'
import { FOCUS, PANEL, TONE_TEXT } from './styles'
import { TrendBars } from './TrendBars'

interface MobileSummaryProps {
  summary: Summary
  onSelectMonth: (month: string) => void
  selection: Selection
  accounts: readonly AccountRef[]
  /** The month's note (partial or in progress), at the end. */
  note: string | null
}

/** The Summary on a phone: what you kept (large, with what came in and went out), a strip of
 * indicators that scrolls sideways, "To review" and the rest in sections that start closed and
 * remember whether they were opened. */
export function MobileSummary({
  summary,
  onSelectMonth,
  selection,
  accounts,
  note,
}: MobileSummaryProps) {
  const { option } = summary
  const chosen = summary.trend.find((point) => point.month === option.month)
  const cards = selection === null || includesCard(selection, accounts)
  return (
    <>
      <KeptCard summary={summary} />
      <Indicators summary={summary} selection={selection} />
      <ReviewCard key={`rev-${option.month}`} month={option.month} selection={selection} />
      <div className="flex flex-col gap-3">
        <Collapsible id="reading" title={t('summary.mobile.section.reading')}>
          <MonthReading
            key={`reading-${option.month}`}
            month={option.month}
            point={chosen}
            whatHappened={summary.what_happened}
            changes={summary.changes}
            partial={option.partial}
            comparable={summary.habitual_cents !== null}
            selection={selection}
          />
        </Collapsible>
        <Collapsible id="upcoming" title={t('summary.mobile.section.upcoming')}>
          <BudgetCard month={option.month} selection={selection} />
        </Collapsible>
        <Collapsible id="categories" title={t('summary.mobile.section.categories')}>
          <CategoryTable
            key={`cat-${option.month}`}
            month={option.month}
            categories={summary.categories}
            selection={selection}
          />
        </Collapsible>
        <Collapsible id="trend" title={t('summary.mobile.section.trend')}>
          <TrendBars trend={summary.trend} month={option.month} onSelect={onSelectMonth} />
        </Collapsible>
        <Collapsible id="details" title={t('summary.mobile.section.details')}>
          <Kpis key={option.month} summary={summary} selection={selection} />
          <RecurringCard month={option.month} selection={selection} />
          <PendingCard selection={selection} />
          {cards && <InterestCard month={option.month} selection={selection} />}
          <ByAccount key={`acc-${option.month}`} accounts={summary.by_account} rate={summary.rate} />
        </Collapsible>
      </div>
      {note && <p className="text-[13px] text-muted-foreground">{note}</p>}
    </>
  )
}

const NBSP = (text: string) => text.replace(/RD\$ /g, 'RD$ ')

function KeptCard({ summary }: { summary: Summary }) {
  const net = summary.net_cents
  const tone = net === null ? null : netTone(net)
  return (
    <section
      aria-label={t('summary.mobile.kept')}
      className={cn(PANEL, '@container flex min-w-0 flex-col gap-2 px-5 py-5')}
    >
      <span className="text-[13px] font-medium text-muted-foreground">
        {t('summary.mobile.kept')}
      </span>
      <span
        data-testid="kept-value"
        className={cn(
          'font-bold whitespace-nowrap tracking-[-0.02em] tabular-nums',
          'text-[clamp(1.5rem,14cqi,2.75rem)] leading-tight',
          tone === null ? 'text-muted-foreground' : tone === 'up' ? 'text-up' : 'text-primary',
        )}
      >
        {netText(net)}
      </span>
      {net !== null && (
        <span className="text-[13px] text-ink-2">
          {NBSP(netDetail(net, summary.third_party_cents))}
        </span>
      )}
      <dl className="mt-1 grid grid-cols-2 gap-3 border-t border-border pt-3">
        <Flow label={t('summary.mobile.in')} value={formatDop(summary.income_cents)} />
        <Flow label={t('summary.mobile.out')} value={formatDop(summary.total_cents)} />
      </dl>
    </section>
  )
}

function Flow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-[12px] font-medium text-muted-foreground">{label}</dt>
      <dd className="truncate text-[15px] font-bold tabular-nums">{NBSP(value)}</dd>
    </div>
  )
}

interface SectionProps {
  summary: Summary
  selection: Selection
}

/** The strip of indicators: it scrolls sideways (with the screen's own scroll, not a gesture). */
function Indicators({ summary, selection }: SectionProps) {
  const month = summary.option.month
  const overview = useBudgetOverview(month, selection)
  const pending = usePending(selection)
  const versus =
    summary.habitual_cents === null ? null : versusHabitual(summary.total_cents, summary.habitual_cents)
  return (
    <section aria-label={t('summary.mobile.indicators')} className="-mx-4 min-w-0">
      <ul
        data-testid="indicators"
        className="flex snap-x snap-mandatory scroll-px-4 gap-2.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none]"
      >
        <Indicator
          label={t('summary.mobile.spending')}
          value={formatDop(summary.total_cents)}
          to={spendingHref(month, selection)}
        >
          {versus && (
            <span className={cn(versus.tone === 'same' ? 'text-ink-2' : TONE_TEXT[versus.tone])}>
              {NBSP(versus.text)}
            </span>
          )}
        </Indicator>
        <Indicator label={t('summary.mobile.savings')} value={savingsText(summary.savings_rate)} />
        {overview.data?.active && (
          <Indicator
            label={t('summary.mobile.budget')}
            to={hrefWithSelection(BUDGET_PATH, { month }, selection)}
          >
            <span className={(overview.data.over_count ?? 0) > 0 ? 'font-semibold text-up' : 'text-ink-2'}>
              {NBSP(overviewText(overview.data))}
            </span>
          </Indicator>
        )}
        {pending.data && pending.data.owed_to_me_dop_cents > 0 && (
          <Indicator
            label={t('summary.mobile.owed')}
            value={formatDop(pending.data.owed_to_me_dop_cents)}
            to={pendingHref(selection)}
          >
            <span className="text-muted-foreground">{t('summary.mobile.owedNote')}</span>
          </Indicator>
        )}
        {summary.one_offs_cents > 0 && (
          <Indicator
            label={t('summary.mobile.oneOffs')}
            value={formatDop(summary.one_offs_cents)}
            to={transactionsHref({ month }, selection)}
          />
        )}
      </ul>
    </section>
  )
}

interface IndicatorProps {
  label: string
  value?: string
  to?: string
  children?: ReactNode
}

function Indicator({ label, value, to, children }: IndicatorProps) {
  const body = (
    <>
      <span className="text-[12px] font-medium text-muted-foreground">{label}</span>
      {value && (
        <span className="text-[17px] font-bold whitespace-nowrap tabular-nums">{value}</span>
      )}
      {children && <span className="text-[12.5px] leading-snug">{children}</span>}
    </>
  )
  const box = cn(
    PANEL,
    'flex h-full w-max max-w-[15rem] min-w-[9rem] flex-col gap-1 px-4 py-3 text-foreground no-underline',
  )
  return (
    <li className="flex shrink-0 snap-start">
      {to ? (
        <Link to={to} className={cn(box, FOCUS)}>
          {body}
        </Link>
      ) : (
        <div className={box}>{body}</div>
      )}
    </li>
  )
}

interface CollapsibleProps {
  id: string
  title: string
  children: ReactNode
}

/** A section that starts closed; opening or closing it is remembered in this browser. Its
 * content only mounts (and loads) once open. */
function Collapsible({ id, title, children }: CollapsibleProps) {
  const [openIds, setOpen] = useOpenSections()
  const open = openIds.includes(id)
  const panel = `summary-section-${id}`
  return (
    <section className={cn(PANEL, 'min-w-0 overflow-clip')} data-section={id}>
      <h2>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          onClick={() => setOpen(id, !open)}
          className={cn(
            'flex min-h-12 w-full items-center justify-between gap-3 px-4 text-left text-[15px] font-[650] tracking-tight',
            FOCUS,
            'focus-visible:ring-inset',
          )}
        >
          {title}
          <ChevronDown
            size={18}
            aria-hidden="true"
            className={cn('shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')}
          />
        </button>
      </h2>
      <div id={panel} hidden={!open} className="flex flex-col gap-4 border-t border-border p-3">
        {open && children}
      </div>
    </section>
  )
}
