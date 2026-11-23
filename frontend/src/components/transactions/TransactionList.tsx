import { ChevronRight, StickyNote } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { t } from '@/i18n'
import type { Tx } from '@/lib/api'
import { shortAccountLabel, splitLabel } from '@/lib/accounts'
import { colorFor, customColors } from '@/lib/categories'
import { type LinkBadge, linkBadges } from '@/lib/links'
import { bankName, receiptTitle } from '@/lib/receipts'
import { installmentTag } from '@/lib/installments'
import { useCategories } from '@/lib/queries'
import {
  AMOUNT_TONE_CLASS,
  amountLines,
  amountTone,
  compactDayLabel,
  dayGroups,
  isoToday,
  fieldGroups,
  groupLine,
  kindBadge,
  oneOffBadge,
  outOfView,
  type FieldGroup,
  type GroupBy,
  type SortBy,
} from '@/lib/transactions'
import { visibleRows } from '@/lib/selection'
import { useLongPress } from '@/lib/useLongPress'
import { shortDay } from '@/lib/months'
import { cn } from '@/lib/utils'
import { FOCUS, PANEL } from '@/components/summary/styles'

// A single line from @xl: merchant (with its badges) | category | account | amount (with the
// original US$ next to it). Narrower, two lines: merchant and amount; below, category · account.
const GRID =
  'grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 @xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(9.5rem,auto)] @xl:gap-x-3.5'

// Day and group headers: they stay on top while their group scrolls by.
const STICKY_HEADER = 'sticky top-0 z-10 border-b border-[#EFEFEA] bg-[#FAFAF8]'

interface TransactionListProps {
  items: Tx[]
  selected: string | null
  ranking: readonly string[]
  stale: boolean
  group: GroupBy
  sort: SortBy
  onSelect: (tx: Tx) => void
  /** Selection mode: each row is a checkbox (`chosen`) instead of opening the detail. */
  picking?: Picking | null
  /** Phone: holding a row enters selection mode with it chosen. */
  onLongPress?: ((tx: Tx) => void) | null
  /** Phone: short day headers ("Hoy", "Ayer", "mar 12 nov"). */
  compact?: boolean
}

export interface Picking {
  chosen: ReadonlySet<string>
  onToggle: (tx: Tx) => void
  /** The visible rows (with groups, only those of the open ones), every time they change. */
  onVisible: (fingerprints: string[]) => void
}

/** List grouped by day, category or merchant; each row is a button that opens the detail (or,
 * in selection mode, a checkbox). */
export function TransactionList({
  items,
  selected,
  ranking,
  stale,
  group,
  sort,
  onSelect,
  picking = null,
  onLongPress = null,
  compact = false,
}: TransactionListProps) {
  const rowProps = { selected, ranking, onSelect, picking, onLongPress }
  const today = isoToday()
  const section = useRef<HTMLElement>(null)
  // On a phone a new list (the whole merchant, say) also brings the chosen row into view.
  const phoneItems = compact ? items : null
  // When the chosen row changes (also when arriving from the Summary, Pending or "Back") the list
  // brings it into view if it is not visible; folding or unfolding a group does not move it.
  useEffect(() => {
    if (!selected) return
    const row = section.current?.querySelector<HTMLElement>(
      `[data-fingerprint="${CSS.escape(selected)}"]`,
    )
    if (row) bringIntoView(row, compact)
  }, [selected, compact, phoneItems])
  const onVisible = picking?.onVisible
  // By day everything is visible; by groups, `FieldGroups` reports it from the open ones.
  useEffect(() => {
    if (onVisible && group === 'day') onVisible(items.map((t) => t.fingerprint))
  }, [onVisible, group, items])
  const groups = useMemo(
    () =>
      group === 'day'
        ? { kind: 'day' as const, days: dayGroups(items, sort) }
        : { kind: 'field' as const, field: group, fields: fieldGroups(items, group, sort) },
    [items, group, sort],
  )
  return (
    <section
      ref={section}
      aria-label={t('transactions.list.label')}
      aria-busy={stale}
      className={cn(
        PANEL,
        // `clip`, not `hidden`: it cuts the corners without breaking the sticky headers.
        '@container min-w-0 flex-[3_1_560px] overflow-clip transition-opacity',
        stale && 'opacity-60',
      )}
    >
      {groups.kind === 'day' ? (
        groups.days.map((day) => (
          <div key={day.day} role="group" aria-label={day.label}>
            <div
              data-day-header
              className={cn(
                STICKY_HEADER,
                'px-4 py-2 text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase sm:px-5',
              )}
            >
              {compact ? compactDayLabel(day.day, today) : day.label}
            </div>
            <Rows items={day.items} {...rowProps} />
          </div>
        ))
      ) : (
        // Changing the grouping closes every group.
        <FieldGroups
          key={groups.field}
          groups={groups.fields}
          field={groups.field}
          {...rowProps}
        />
      )}
    </section>
  )
}

/** Centers the row if it is not fully visible. On a tablet the detail sheet covers almost all of
 * it: what matters is that it is in view when the sheet closes. On a phone (`instant`) the
 * full-screen detail hides the list, so it jumps there at once: when the detail closes the row is
 * already in place (no scroll still running). */
function bringIntoView(row: HTMLElement, instant: boolean) {
  if (!outOfView(row.getBoundingClientRect(), window.innerHeight)) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  row.scrollIntoView({ block: 'center', behavior: reduce || instant ? 'auto' : 'smooth' })
}

interface RowsProps {
  items: Tx[]
  selected: string | null
  ranking: readonly string[]
  onSelect: (tx: Tx) => void
  picking: Picking | null
  onLongPress: ((tx: Tx) => void) | null
}

function Rows({ items, selected, ranking, onSelect, picking, onLongPress }: RowsProps) {
  const custom = customColors(useCategories().data ?? [])
  return items.map((tx) =>
    picking ? (
      <PickRow
        key={tx.fingerprint}
        tx={tx}
        color={colorFor(ranking, tx.category, custom)}
        checked={picking.chosen.has(tx.fingerprint)}
        onToggle={picking.onToggle}
      />
    ) : (
      <Row
        key={tx.fingerprint}
        tx={tx}
        color={colorFor(ranking, tx.category, custom)}
        selected={tx.fingerprint === selected}
        onSelect={onSelect}
        onLongPress={onLongPress}
      />
    ),
  )
}

interface FieldGroupsProps extends Omit<RowsProps, 'items'> {
  groups: FieldGroup[]
  field: 'category' | 'merchant'
}

/** Groups by category or merchant, closed at first (except the chosen row's group). */
function FieldGroups({
  groups,
  field,
  selected,
  ranking,
  onSelect,
  picking,
  onLongPress,
}: FieldGroupsProps) {
  const custom = customColors(useCategories().data ?? [])
  const baseId = useId()
  const [open, setOpen] = useState<ReadonlySet<string>>(() => {
    const chosen = groups.find((g) => g.items.some((t) => t.fingerprint === selected))
    return new Set(chosen ? [chosen.key] : [])
  })
  const onVisible = picking?.onVisible
  useEffect(() => {
    if (onVisible) onVisible(visibleRows(groups, open).map((t) => t.fingerprint))
  }, [onVisible, groups, open])

  function toggle(key: string) {
    setOpen((current) => {
      const next = new Set(current)
      if (!next.delete(key)) next.add(key)
      return next
    })
  }

  return groups.map((group, index) => {
    const expanded = open.has(group.key)
    const panelId = `${baseId}-${index}`
    return (
      <div key={group.key} role="group" aria-label={group.key}>
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => toggle(group.key)}
          className={cn(
            STICKY_HEADER,
            'flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-left hover:bg-[#F4F4F0] sm:px-5',
            FOCUS,
            'focus-visible:ring-inset',
          )}
        >
          <ChevronRight
            size={16}
            aria-hidden="true"
            className={cn(
              'shrink-0 text-muted-foreground transition-transform',
              expanded && 'rotate-90',
            )}
          />
          {field === 'category' && <Swatch color={colorFor(ranking, group.key, custom)} />}
          <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
            <span className="max-w-full truncate text-sm font-semibold text-foreground">
              {group.key}
            </span>{' '}
            <span className="text-xs text-muted-foreground tabular-nums">{groupLine(group)}</span>
          </span>
        </button>
        <div id={panelId} hidden={!expanded}>
          {expanded && (
            <Rows
              items={group.items}
              selected={selected}
              ranking={ranking}
              onSelect={onSelect}
              picking={picking}
              onLongPress={onLongPress}
            />
          )}
        </div>
      </div>
    )
  })
}

interface RowProps {
  tx: Tx
  color: string
  selected: boolean
  onSelect: (tx: Tx) => void
  onLongPress: ((tx: Tx) => void) | null
}

function Row({ tx, color, selected, onSelect, onLongPress }: RowProps) {
  const press = useLongPress(onLongPress && (() => onLongPress(tx)))
  return (
    <button
      type="button"
      aria-pressed={selected}
      data-fingerprint={tx.fingerprint}
      onClick={() => onSelect(tx)}
      {...press}
      className={cn(
        press && 'select-none [-webkit-touch-callout:none]',
        GRID,
        'relative min-h-11 w-full scroll-mt-16 cursor-pointer items-center border-b border-[#F2F2EE] px-4 py-1.5 text-left text-foreground transition-colors last:border-b-0 sm:px-5',
        selected ? 'bg-[#F1F7F5]' : 'bg-card hover:bg-[#FAFAF8]',
        FOCUS,
        'focus-visible:ring-inset',
      )}
    >
      {selected && (
        <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-primary" />
      )}
      <RowBody tx={tx} color={color} />
    </button>
  )
}

interface PickRowProps {
  tx: Tx
  color: string
  checked: boolean
  onToggle: (tx: Tx) => void
}

/** A row in selection mode: the checkbox (44 px) and the same as the normal row; tapping
 * anywhere checks or unchecks it. */
function PickRow({ tx, color, checked, onToggle }: PickRowProps) {
  return (
    <label
      data-fingerprint={tx.fingerprint}
      className={cn(
        'relative flex min-h-11 w-full cursor-pointer items-stretch border-b border-[#F2F2EE] text-foreground transition-colors last:border-b-0 focus-within:ring-3 focus-within:ring-ring/30 focus-within:ring-inset',
        checked ? 'bg-[#F1F7F5]' : 'bg-card hover:bg-[#FAFAF8]',
      )}
    >
      <span className="flex w-11 shrink-0 items-center justify-center">
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onToggle(tx)}
          aria-label={pickLabel(tx)}
          className="size-5 cursor-pointer accent-[var(--color-primary)]"
        />
      </span>
      <span className={cn(GRID, 'min-w-0 flex-1 items-center py-1.5 pr-4 sm:pr-5')}>
        <RowBody tx={tx} color={color} />
      </span>
    </label>
  )
}

/** "Select <day> <merchant> <amount>": the day tells two identical rows apart. The name is the
 * row's visible title (a receipt's, when it has one), so what is read out is what is seen. */
function pickLabel(tx: Tx): string {
  return t('transactions.list.pick', {
    day: shortDay(tx.day),
    merchant: receiptTitle(tx) ?? tx.merchant,
    amount: amountLines(tx).main,
  })
}

/** What a row shows (in the `GRID` of its container). */
function RowBody({ tx, color }: { tx: Tx; color: string }) {
  const amount = amountLines(tx)
  return (
    <>
      <span className="col-start-1 row-start-1 flex min-w-0 flex-col">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="min-w-[9ch] truncate text-sm font-semibold">
            {receiptTitle(tx) ?? tx.merchant}
          </span>
          {/* The badges give up space before the name: each one is cut with "…". */}
          <span className="flex min-w-0 shrink items-center gap-1.5 overflow-hidden">
            <Badges tx={tx} />
          </span>
        </span>
        {/* A merchant receipt took the title: what the statement printed goes under it. */}
        {bankName(tx) && (
          <span data-testid="bank-name" className="truncate text-xs text-muted-foreground">
            {tx.merchant}
          </span>
        )}
        {tx.installment && (
          <span data-testid="installment-tag" className="truncate text-xs font-medium text-primary">
            {installmentTag(tx)}
          </span>
        )}
      </span>
      <span
        className={cn(
          'col-start-1 row-start-2 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground @xl:hidden',
          !amount.original && 'col-span-2',
        )}
      >
        <Swatch color={color} />
        <span className="truncate max-md:rounded-full max-md:bg-muted max-md:px-1.5 max-md:leading-[18px] max-md:text-ink-2">
          {tx.category}
          <span className="max-md:hidden"> ·</span>
        </span>
        {/* The account gives up space before the category. */}
        <span className="flex min-w-0 shrink-4">
          <AccountLabel label={tx.account_label} />
        </span>
      </span>
      <span className="hidden min-w-0 items-center gap-2 text-[13px] text-ink-2 @xl:col-start-2 @xl:row-start-1 @xl:flex">
        <Swatch color={color} />
        <span className="truncate">{tx.category}</span>
      </span>
      <span className="hidden min-w-0 text-[13px] text-muted-foreground @xl:col-start-3 @xl:row-start-1 @xl:flex">
        <AccountLabel label={tx.account_label} />
      </span>
      {amount.original && (
        // Narrow: below the amount, on the right. From @xl it goes on the same line (below).
        <span className="col-start-2 row-start-2 justify-self-end text-xs text-muted-foreground tabular-nums @xl:hidden">
          {amount.original}
        </span>
      )}
      <span className="col-start-2 row-start-1 flex items-baseline justify-self-end gap-2 whitespace-nowrap tabular-nums @xl:col-start-4">
        {amount.original && (
          <span className="hidden text-xs text-muted-foreground @xl:inline">{amount.original}</span>
        )}
        <span className={cn('text-sm font-semibold', AMOUNT_TONE_CLASS[amountTone(tx)])}>
          {amount.main}
        </span>
      </span>
    </>
  )
}

/** Pending statement, kind, one-off and correction as small labels next to the name. */
function Badges({ tx }: { tx: Tx }) {
  const links = linkBadges(tx)
  // A link (reimbursement, exchange) says more than the kind: the kind is left out.
  const kind = links.length && tx.link !== 'shared' ? null : kindBadge(tx)
  const oneOff = oneOffBadge(tx)
  return (
    <>
      {tx.provisional && (
        <Badge className="bg-[#FFF6E5] text-[#7A4B00] dark:bg-[#3A2A0A] dark:text-[#F5C97A]">
          {t('transactions.badge.provisional')}
        </Badge>
      )}
      {(tx.cash_state === 'pending' || tx.cash_state === 'unconfirmed') && (
        <Badge data-testid="cash-state-badge" className="bg-muted text-muted-foreground">
          {tx.cash_state === 'pending'
            ? t('cashBox.lineDetail.pending')
            : t('cashBox.lineDetail.unconfirmed')}
        </Badge>
      )}
      {tx.approved && (
        <Badge data-testid="approved-badge" className="bg-[#FDECEC] text-[#8A1F1F] dark:bg-[#3A1414] dark:text-[#F5A3A3]">
          {t('forwarding.badge.approved')}
        </Badge>
      )}
      {kind && (
        <Badge
          className={
            tx.kind === 'income' ? 'bg-down-soft text-down' : 'bg-muted text-muted-foreground'
          }
        >
          {kind}
        </Badge>
      )}
      {oneOff && tx.one_off && <Badge className="bg-up-soft text-up-ink">{oneOff}</Badge>}
      {oneOff && !tx.one_off && (
        <Badge className="border border-dashed border-up/40 bg-card text-up-ink">{oneOff}</Badge>
      )}
      {tx.corrected && (
        <Badge className="bg-secondary text-secondary-foreground">
          {t('transactions.badge.corrected')}
        </Badge>
      )}
      {links.map((badge) => (
        <Badge key={badge.label} className={LINK_TONE[badge.tone]}>
          {badge.label}
        </Badge>
      ))}
      {tx.note && (
        <span
          role="img"
          aria-label={t('transactions.list.hasNote')}
          title={tx.note}
          className="shrink-0 text-muted-foreground"
        >
          <StickyNote size={13} aria-hidden="true" />
        </span>
      )}
    </>
  )
}

const LINK_TONE: Record<LinkBadge['tone'], string> = {
  shared: 'bg-[#EEF3FB] text-[#2F4F7F]',
  linked: 'bg-muted text-muted-foreground',
  suggested: 'border border-dashed border-primary/40 bg-card text-primary',
}

/** Account with its last digits always visible: only the name is truncated. A bank account uses
 * its short name; the full one goes in `title`. */
function AccountLabel({ label }: { label: string }) {
  const { name, tail } = splitLabel(shortAccountLabel(label))
  return (
    <span className="flex min-w-0 gap-1" title={label}>
      <span className="truncate">{name}</span>
      {tail && <span className="shrink-0">{tail}</span>}
    </span>
  )
}

function Swatch({ color }: { color: string }) {
  return (
    <span
      aria-hidden="true"
      className="size-2 shrink-0 rounded-[3px]"
      style={{ background: color }}
    />
  )
}

interface BadgeProps {
  className: string
  children: string
}

/** A label that is cut with "…" when it does not fit (the full text goes in `title`). */
function Badge({ className, children }: BadgeProps) {
  return (
    <span
      title={children}
      className={cn(
        'max-w-full min-w-[3ch] truncate rounded-full px-1.5 text-[10.5px] leading-[18px] font-semibold',
        className,
      )}
    >
      {children}
    </span>
  )
}
