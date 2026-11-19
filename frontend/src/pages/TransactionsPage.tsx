import { type ReactNode, useCallback, useState } from 'react'
import { useSearchParams } from 'react-router'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { LoadError } from '@/components/LoadError'
import { MonthHeader } from '@/components/MonthHeader'
import { PANEL } from '@/components/summary/styles'
import { Filters } from '@/components/transactions/Filters'
import { BatchNotice, SelectionBar } from '@/components/transactions/SelectionBar'
import { DETAIL_TITLE_ID, TransactionDetail } from '@/components/transactions/TransactionDetail'
import { TransactionList } from '@/components/transactions/TransactionList'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import {
  type AccountRef,
  normalize,
  readStored,
  resolveSelection,
  scopeText,
  type Selection,
  writeStored,
} from '@/lib/accountFilter'
import type { Transactions, Tx } from '@/lib/api'
import { neighbors, resolveMonth, returnTarget } from '@/lib/months'
import { usePublishNavMonth } from '@/lib/navMonth'
import {
  useAccounts,
  useCategories,
  useMonths,
  useSummary,
  useTransactions,
} from '@/lib/queries'
import {
  clearFilters,
  hasNarrowing,
  parseFilters,
  toParams,
  totalsParts,
  type TxFilters,
} from '@/lib/transactions'
import { visibleChosen } from '@/lib/selection'
import { useTxSelection } from '@/lib/useTxSelection'
import { usePersistUrlSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

const NO_RANKING: readonly string[] = []

/** Transactions screen: filters and selection in the URL (`month`, `accounts`, `kind`,
 * `category`, `q`, `tx`, `group`, `sort`), a list by day, category or merchant and a panel to
 * correct the category or mark a one-off expense. Without `accounts` in the URL the accounts
 * remembered from the Summary apply (or the single `account` of older links). The month is
 * chosen in the same header as the Summary. */
export function TransactionsPage() {
  const [params, setParams] = useSearchParams()
  const fromUrl = parseFilters(params)
  const accounts = useAccounts()
  const stored = readStored()
  const ready = !accounts.isPending || (fromUrl.accounts === null && stored === null)
  const selection = effectiveSelection(fromUrl.accounts, stored, accounts.data, accounts.isError)
  usePersistUrlSelection(fromUrl.accounts, stored, accounts.data)
  const filters: TxFilters = { ...fromUrl, accounts: selection }
  const months = useMonths(selection, ready)
  const month = months.data ? resolveMonth(months.data, filters.month) : null
  const list = useTransactions(month, filters)
  const categories = useCategories()
  // The month's Summary gives the spending order: category colors match its table.
  const summary = useSummary(month, selection)
  // The chosen (or just saved) row stays in the detail even if it leaves the list.
  const [pinned, setPinned] = useState<Tx | null>(null)
  // Selection mode: the checked fingerprints, the visible rows and the batch result.
  const picker = useTxSelection(list.data?.items)
  const { chosen } = picker
  const picking = chosen !== null
  const home = months.data && month ? returnTarget(months.data, month) : null
  usePublishNavMonth(home ? month : null)

  const navigate = useCallback(
    (update: (current: TxFilters) => TxFilters, replace = false) =>
      setParams((current) => toParams(update(parseFilters(current))), { replace }),
    [setParams],
  )
  const onSearch = useCallback(
    (q: string) => navigate((current) => ({ ...current, q }), true),
    [navigate],
  )

  if (months.isError) {
    return (
      <LoadError
        what={t('transactions.load.months')}
        error={months.error}
        onRetry={() => months.refetch()}
      />
    )
  }
  if (!ready || months.isPending) return <PageSkeleton />
  if (month === null) return <NoStatements />

  const option = months.data.find((o) => o.month === month)!
  const items = list.data?.items ?? []
  const selected = filters.tx
    ? (items.find((t) => t.fingerprint === filters.tx) ??
      (pinned?.fingerprint === filters.tx ? pinned : null))
    : null
  const ranking = summary.data?.categories.map((c) => c.category) ?? NO_RANKING

  function select(tx: Tx | null) {
    setPinned(tx)
    navigate((current) => ({ ...current, month, tx: tx?.fingerprint ?? null }), true)
  }

  function startPicking() {
    select(null)
    picker.start()
  }

  function clearAll() {
    writeStored(null)
    navigate(clearFilters)
  }

  function changeFilters(patch: Partial<TxFilters>) {
    if (patch.accounts !== undefined) writeStored(patch.accounts)
    navigate((current) => ({ ...current, month, ...patch }))
  }

  // Changing the month keeps the other filters; the chosen row belongs to another month and is
  // released. Without a month (the "back to" button) the default one applies.
  function goTo(target: string | null) {
    setPinned(null)
    navigate((current) => ({ ...current, month: target, tx: null }))
  }

  const accountList = accounts.data ?? []
  return (
    <>
      <MonthHeader
        title={t('transactions.title')}
        month={month}
        label={option.label}
        months={months.data}
        neighbors={neighbors(months.data, month)}
        onNavigate={goTo}
        home={home}
        onReturn={() => goTo(null)}
        scope={scopeText(filters.accounts, accountList)}
        picker={
          accountList.length > 1 && (
            <AccountPicker
              selection={filters.accounts}
              accounts={accountList}
              onChange={(next) => changeFilters({ accounts: next })}
            />
          )
        }
      >
        {list.data && <Totals data={list.data} />}
      </MonthHeader>

      <Filters
        filters={filters}
        categories={categories.data ?? []}
        onChange={changeFilters}
        onSearch={onSearch}
      >
        {!picking && items.length > 0 && (
          <button
            type="button"
            onClick={startPicking}
            className="flex h-11 items-center rounded-xl border border-border bg-card px-3.5 text-sm font-semibold text-foreground hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/30 focus-visible:outline-none"
          >
            {t('transactions.select')}
          </button>
        )}
      </Filters>

      {picker.note && <BatchNotice note={picker.note} onClose={picker.dismissNote} />}

      <div className="flex flex-wrap items-start gap-6">
        {list.isError ? (
          <div className="min-w-0 flex-[3_1_560px]">
            <LoadError
              what={t('transactions.load.list')}
              error={list.error}
              onRetry={() => list.refetch()}
            />
          </div>
        ) : !list.data ? (
          <ListSkeleton />
        ) : items.length === 0 ? (
          <EmptyList onClear={hasNarrowing(filters) ? clearAll : null} />
        ) : (
          <TransactionList
            items={items}
            selected={selected?.fingerprint ?? null}
            ranking={ranking}
            stale={list.isPlaceholderData}
            group={filters.group}
            sort={filters.sort}
            onSelect={select}
            picking={
              chosen && { chosen, onToggle: picker.toggle, onVisible: picker.onVisible }
            }
          />
        )}
        <DetailPanel open={selected !== null} onClose={() => select(null)}>
          {selected ? (
            <TransactionDetail
              key={selected.fingerprint}
              tx={selected}
              categories={categories.data ?? []}
              inList={items.some((t) => t.fingerprint === selected.fingerprint)}
              onSaved={setPinned}
              onClose={() => select(null)}
              onShowMerchant={(merchant) =>
                navigate((current) => ({ ...current, month, category: null, q: merchant }))
              }
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              {t('transactions.detail.empty')}
            </p>
          )}
        </DetailPanel>
      </div>
      {chosen && (
        <SelectionBar
          chosen={visibleChosen(items, chosen)}
          visible={picker.visible.length}
          allVisibleChosen={picker.visible.every((fp) => chosen.has(fp))}
          categories={categories.data ?? []}
          onSelectAll={picker.selectVisible}
          onCancel={picker.cancel}
          onDone={picker.done}
        />
      )}
    </>
  )
}

/** The URL's accounts (or the older single `account`) win; otherwise the remembered ones. If the
 * accounts do not load, all of them. */
function effectiveSelection(
  fromUrl: Selection,
  stored: string | null,
  accounts: readonly AccountRef[] | undefined,
  failed: boolean,
): Selection {
  if (failed) return null
  return fromUrl !== null ? normalize(fromUrl, accounts) : resolveSelection(null, stored, accounts)
}

function Totals({ data }: { data: Transactions }) {
  const parts = totalsParts(data)
  return (
    <span className="text-sm text-ink-2 tabular-nums" aria-live="polite">
      {parts.count}
      {parts.total && (
        <>
          {' · '}
          <strong className="font-semibold text-foreground">{parts.total}</strong>
        </>
      )}
      {parts.income && (
        <>
          {' · '}
          <span className="whitespace-nowrap">{parts.income}</span>
        </>
      )}
      {parts.unconverted && (
        <span className="text-muted-foreground"> · {parts.unconverted}</span>
      )}
    </span>
  )
}

interface DetailPanelProps {
  open: boolean
  onClose: () => void
  children: ReactNode
}

/** Side panel from `xl`; narrower, a bottom sheet that only appears with a selection. */
function DetailPanel({ open, onClose, children }: DetailPanelProps) {
  return (
    <>
      {open && (
        <div
          aria-hidden="true"
          onClick={onClose}
          className="fixed inset-0 z-40 bg-[#1B1D21]/30 animate-in fade-in-0 xl:hidden"
        />
      )}
      <aside
        aria-labelledby={open ? DETAIL_TITLE_ID : undefined}
        aria-label={open ? undefined : t('transactions.detail.label')}
        className={cn(
          'border border-border bg-card p-5 sm:p-6',
          // Phone and tablet: bottom sheet.
          'fixed inset-x-0 bottom-0 z-50 max-h-[88dvh] overflow-y-auto rounded-t-2xl shadow-[0_-8px_32px_rgba(27,29,33,0.16)] animate-in slide-in-from-bottom-8 fade-in-0 duration-200',
          // Desktop: sticky column next to the list.
          'xl:sticky xl:top-6 xl:z-auto xl:max-h-[calc(100dvh-48px)] xl:min-w-0 xl:flex-[2_1_340px] xl:rounded-2xl xl:shadow-none xl:animate-none',
          !open && 'hidden xl:block',
        )}
      >
        {children}
      </aside>
    </>
  )
}

/** Empty list; the button only appears when there are filters to clear. */
function EmptyList({ onClear }: { onClear: (() => void) | null }) {
  return (
    <div
      className={cn(
        PANEL,
        'flex min-w-0 flex-[3_1_560px] flex-col items-center gap-3 px-6 py-14 text-center',
      )}
    >
      <p className="text-[15px] font-semibold">{t('transactions.empty')}</p>
      {onClear && (
        <Button
          variant="outline"
          className="h-11 rounded-xl bg-card px-4 text-sm font-semibold"
          onClick={onClear}
        >
          {t('transactions.clearFilters')}
        </Button>
      )}
    </div>
  )
}

function NoStatements() {
  return (
    <div className={cn(PANEL, 'flex flex-col gap-2 px-6 py-10 text-center')}>
      <h1 className="text-xl font-bold tracking-tight">{t('transactions.title')}</h1>
      <p className="text-sm text-muted-foreground">
        {tn('transactions.noStatements', {
          command: (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[13px] text-foreground">
              uv run michelito sync
            </code>
          ),
        })}
      </p>
    </div>
  )
}

function ListSkeleton() {
  return (
    <div aria-busy="true" className={cn(PANEL, 'min-w-0 flex-[3_1_560px] overflow-hidden')}>
      <Skeleton className="h-9 rounded-none" />
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="flex h-11 items-center gap-3 border-b border-[#F2F2EE] px-5">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-20" />
        </div>
      ))}
    </div>
  )
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label={t('transactions.loading')} className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-9 w-64 rounded-[10px]" />
        <Skeleton className="h-4 w-80 max-w-full" />
      </div>
      <Skeleton className="h-11 rounded-xl" />
      <ListSkeleton />
    </div>
  )
}
