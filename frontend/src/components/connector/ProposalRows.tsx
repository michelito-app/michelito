import { FileCheck } from 'lucide-react'
import { ROW_DIVIDER } from '@/components/summary/styles'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { t } from '@/i18n'
import { formatMoney } from '@/lib/links'
import { shortDay } from '@/lib/months'
import type { ImportRow, ProposalItem, StatementInfo } from '@/lib/proposals'
import { cn } from '@/lib/utils'

interface TickProps {
  on: boolean
  onChange: (on: boolean) => void
}

/** A category change: the transaction, from → to, "only this one" or the merchant's rule. */
export function ItemRow({ item, on, onChange }: { item: ProposalItem } & TickProps) {
  const label = `proposal-item-${item.id}`
  return (
    <li className={cn(ROW_DIVIDER, 'flex items-start gap-3 py-3')} data-testid="proposal-item">
      <Checkbox aria-labelledby={label} checked={on} onCheckedChange={(value) => onChange(value === true)} className="mt-1" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-baseline justify-between gap-3">
          <span id={label} className="truncate text-sm font-semibold">
            {item.merchant || item.description}
          </span>
          <span className="shrink-0 text-sm tabular-nums">{formatMoney(item.amount_cents, item.currency)}</span>
        </div>
        <p className="text-xs text-muted-foreground">
          {shortDay(item.day)} ·{' '}
          {t('connector.proposals.move', { from: item.from_category, to: item.to_category || t('connector.proposals.missingCategory') })}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={item.scope === 'merchant' ? 'default' : 'secondary'}>
            {item.scope === 'merchant' ? t('connector.proposals.rule') : t('connector.proposals.onlyThis')}
          </Badge>
          {item.reason && <span className="text-xs text-ink-2">{item.reason}</span>}
        </div>
      </div>
    </li>
  )
}

/** A loose row of an import: what it is, when, how much, and whether it seems already there. */
export function ImportRowView({ row, on, onChange }: { row: ImportRow } & TickProps) {
  const label = `proposal-row-${row.id}`
  const amount = formatMoney(row.amount_cents, row.currency)
  return (
    <li className={cn(ROW_DIVIDER, 'flex items-start gap-3 py-3')} data-testid="proposal-row">
      <Checkbox aria-labelledby={label} checked={on} onCheckedChange={(value) => onChange(value === true)} className="mt-1" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-baseline justify-between gap-3">
          <span id={label} className="truncate text-sm font-semibold">
            {row.description}
          </span>
          <span className={cn('shrink-0 text-sm tabular-nums', row.direction === 'in' && 'text-down')}>
            {row.direction === 'in' ? `+${amount}` : amount}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          {[shortDay(row.day), row.direction === 'in' ? t('connector.proposals.income') : null, row.category || null]
            .filter(Boolean)
            .join(' · ')}
        </p>
        {row.duplicate_of && (
          <Badge variant="outline" className="self-start" data-testid="proposal-duplicate">
            {t('connector.proposals.duplicate')}
          </Badge>
        )}
      </div>
    </li>
  )
}

/** A statement import: its period, size and that it squares. */
export function StatementView({ statement }: { statement: StatementInfo }) {
  const period = statement.period_start
    ? t('connector.proposals.statementPeriod', { start: shortDay(statement.period_start), end: shortDay(statement.period_end) })
    : t('connector.proposals.statementCut', { end: shortDay(statement.period_end) })
  return (
    <div className="flex items-start gap-3 rounded-xl bg-muted px-4 py-3" data-testid="proposal-statement">
      <FileCheck size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-primary" />
      <div className="flex flex-col gap-0.5 text-sm">
        <span className="font-semibold">
          {period} · {statement.period_end.slice(0, 4)}
        </span>
        <span className="text-ink-2">
          {t('connector.proposals.statementRows', { count: statement.transactions })} · {statement.currencies.join(' + ')}
        </span>
        {statement.sections.map((section) => (
          <span key={section.currency} className="text-ink-2 tabular-nums" data-testid="proposal-section">
            {t('connector.proposals.sectionTotals', {
              currency: section.currency,
              debits: money(section.debits_cents, section.currency),
              credits: money(section.credits_cents, section.currency),
              closing: money(section.closing_cents, section.currency),
            })}
          </span>
        ))}
        <span className="text-xs text-muted-foreground">{t('connector.proposals.statementSquares')}</span>
        {statement.sections
          .filter((section) => section.continues === false)
          .map((section) => (
            <span key={section.currency} role="note" className="text-xs font-semibold text-destructive">
              {t('connector.proposals.breaks', { currency: section.currency })}
            </span>
          ))}
      </div>
    </div>
  )
}

function money(cents: number | null, currency: string): string {
  return cents === null ? t('connector.proposals.notGiven') : formatMoney(cents, currency)
}
