import { ChevronRight } from 'lucide-react'
import { HostedEmpty } from '@/components/onboarding/HostedEmpty'
import { isHosted, useMode } from '@/lib/demo'
import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { LoadError } from '@/components/LoadError'
import { FOCUS, PANEL, PANEL_TITLE, ROW_DIVIDER } from '@/components/summary/styles'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { Pending, PendingItem } from '@/lib/api'
import { groupPath, linkPagePath } from '@/lib/links'
import {
  ageText,
  EMPTY_TEXT,
  type Figure,
  isEmpty,
  itemAmount,
  itemMeta,
  netTone,
  type NetTone,
  pendingFigures,
  rateNote,
} from '@/lib/pending'
import { usePending } from '@/lib/queries'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

const NET_CLASS: Record<NetTone, string> = {
  positive: 'text-down',
  negative: 'text-up',
  zero: 'text-foreground',
}

/** Pending screen: who owes you and whom you owe, from every month, with the chosen accounts
 * (the Summary's: URL `accounts` or the remembered ones). Each row opens its link's screen and
 * "Back" returns here. */
export function PendingPage() {
  const { selection, accounts, ready, select } = useAccountSelection()
  const pending = usePending(selection, ready)

  const picker = accounts.length > 1 && (
    <AccountPicker selection={selection} accounts={accounts} onChange={select} />
  )
  if (pending.isError) {
    return (
      <>
        <Header>{picker}</Header>
        <LoadError what={t('pending.load')} error={pending.error} onRetry={() => pending.refetch()} />
      </>
    )
  }
  if (!ready || pending.isPending) return <PageSkeleton />

  const data = pending.data
  return (
    <>
      <Header>{picker}</Header>
      {isEmpty(data) ? <Empty /> : <Content data={data} />}
    </>
  )
}

function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">
          {t('pending.title')}
        </h1>
        {children}
      </div>
      <p className="text-[13px] text-muted-foreground">
        {t('pending.subtitle')}
      </p>
    </header>
  )
}

function Content({ data }: { data: Pending }) {
  const note = rateNote(data)
  return (
    <div className="flex max-w-[960px] flex-col gap-6">
      <section aria-label={t('pending.totalsLabel')} className="flex flex-col gap-2">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {pendingFigures(data).map((figure) => (
            <FigureCard
              key={figure.key}
              figure={figure}
              tone={figure.key === 'net' ? netTone(data.net_dop_cents) : null}
            />
          ))}
        </div>
        {note && <p className="text-[13px] text-muted-foreground">{note}</p>}
      </section>
      <ItemList
        title={t('pending.figure.owed')}
        empty={t('pending.owedEmpty')}
        items={data.owed_to_me}
      />
      <ItemList title={t('pending.figure.owe')} empty={t('pending.oweEmpty')} items={data.i_owe} />
    </div>
  )
}

function FigureCard({ figure, tone }: { figure: Figure; tone: NetTone | null }) {
  return (
    <div className={cn(PANEL, 'flex flex-col gap-1 px-5 py-4')}>
      <span className="text-[13px] font-medium text-ink-2">{figure.label}</span>
      <strong
        data-testid={`pending-${figure.key}`}
        className={cn(
          'text-[24px] leading-tight font-bold tracking-[-0.01em] whitespace-nowrap tabular-nums',
          tone && NET_CLASS[tone],
        )}
      >
        {figure.value}
      </strong>
      {figure.extra && <span className="text-[13px] text-muted-foreground">{figure.extra}</span>}
    </div>
  )
}

interface ItemListProps {
  title: string
  empty: string
  items: PendingItem[]
}

function ItemList({ title, empty, items }: ItemListProps) {
  return (
    <section aria-label={title} className={cn(PANEL, 'flex flex-col px-5 pt-4 pb-2 sm:px-6')}>
      <h2 className={cn(PANEL_TITLE, 'pb-1')}>
        {title} <span className="text-sm font-medium text-muted-foreground">· {items.length}</span>
      </h2>
      {items.length === 0 ? (
        <p className="py-3 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col">
          {items.map((item) => (
            <Row key={`${item.kind}-${item.fingerprint}`} item={item} />
          ))}
        </ul>
      )}
    </section>
  )
}

function Row({ item }: { item: PendingItem }) {
  const location = useLocation()
  const amount = itemAmount(item)
  const meta = itemMeta(item)
  return (
    <li className={ROW_DIVIDER}>
      <Link
        to={
          item.kind === 'shared' && item.link_id != null
            ? groupPath(item.link_id)
            : linkPagePath(item.fingerprint)
        }
        state={{ from: `${location.pathname}${location.search}` }}
        className={cn(
          '-mx-2 flex min-w-0 items-center gap-3 rounded-md px-2 py-3 text-foreground no-underline transition-colors hover:bg-muted/60',
          FOCUS,
        )}
      >
        {/* On narrow screens the account and the age move to another line. */}
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex min-w-0 items-baseline justify-between gap-3">
            <span className="min-w-0 truncate text-sm font-semibold">{item.merchant}</span>
            <span className="shrink-0 text-sm font-semibold whitespace-nowrap tabular-nums">
              {amount.main}
            </span>
          </span>
          <span className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 text-[13px] text-muted-foreground">
            <span className="min-w-0 flex-[1_1_220px] truncate" title={meta}>
              {meta}
            </span>
            <span className="ml-auto whitespace-nowrap tabular-nums">
              {amount.approx ? `${amount.approx} · ` : ''}
              {ageText(item.age_days)}
            </span>
          </span>
        </span>
        <ChevronRight size={16} aria-hidden="true" className="shrink-0 text-muted-foreground" />
      </Link>
    </li>
  )
}

function Empty() {
  if (isHosted(useMode())) return <HostedEmpty view="pending" />
  return (
    <div className={cn(PANEL, 'flex max-w-[960px] flex-col gap-1.5 px-6 py-10 text-center')}>
      <p className="text-[15px] font-semibold">{EMPTY_TEXT}</p>
      <p className="text-[13px] text-muted-foreground">
        {t('pending.emptyHelp')}
      </p>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label={t('pending.loading')} className="flex flex-col gap-6">
      <Skeleton className="h-9 w-56 rounded-[10px]" />
      <div className="grid max-w-[960px] grid-cols-1 gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-48 max-w-[960px] rounded-2xl" />
    </div>
  )
}
