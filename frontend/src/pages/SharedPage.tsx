import { type ReactNode, useId, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { LoadError } from '@/components/LoadError'
import { GroupRow } from '@/components/shared/GroupRow'
import { NewGroupPanel } from '@/components/shared/NewGroupPanel'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { Action, FIELD } from '@/components/transactions/linkParts'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { SharedList } from '@/lib/api'
import { useSharedList } from '@/lib/queries'
import {
  CHIPS,
  chipCounts,
  emptyText,
  filterGroups,
  GROUP_PARAM,
  noneText,
  parseChip,
  parseGroup,
  QUERY_PARAM,
  sharedFigures,
  sharedParams,
  STATUS_PARAM,
  withPinned,
} from '@/lib/sharedList'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

/** Shared screen: all the shared groups, from every month, with the chosen accounts (the
 * Summary's). The chip (`status`), the search (`q`) and the expanded group (`group`) live in the
 * URL: "Back" from a group's screen returns to the same view. */
export function SharedPage() {
  const { selection, accounts, ready, select } = useAccountSelection()
  const list = useSharedList(selection, ready)
  const [creating, setCreating] = useState(false)
  const panelId = useId()
  const location = useLocation()
  const from = `${location.pathname}${location.search}`

  const picker = accounts.length > 1 && (
    <AccountPicker selection={selection} accounts={accounts} onChange={select} />
  )
  const panel = creating && (
    <NewGroupPanel
      id={panelId}
      selection={selection}
      from={from}
      onClose={() => setCreating(false)}
    />
  )
  if (list.isError) {
    return (
      <>
        <Header>{picker}</Header>
        <LoadError what={t('shared.load')} error={list.error} onRetry={() => list.refetch()} />
      </>
    )
  }
  if (!ready || list.isPending) return <PageSkeleton />

  const data = list.data
  // The button is not unmounted when the panel opens: focus returns to it on closing.
  const newGroup = (
    <Action
      onClick={() => setCreating((open) => !open)}
      disclosure={{ expanded: creating, controls: panelId }}
    >
      {t('shared.newGroup.open')}
    </Action>
  )
  return (
    <>
      <Header>{picker}</Header>
      {data.groups.length === 0 ? (
        <>
          <Empty text={emptyText(selection !== null)}>{newGroup}</Empty>
          {panel}
        </>
      ) : (
        <Content data={data} newGroup={newGroup} panel={panel} />
      )}
    </>
  )
}

function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">
          {t('shared.title')}
        </h1>
        {children}
      </div>
      <p className="text-[13px] text-muted-foreground">
        {t('shared.subtitle')}
      </p>
    </header>
  )
}

interface ContentProps {
  data: SharedList
  newGroup: ReactNode
  panel: ReactNode
}

function Content({ data, newGroup, panel }: ContentProps) {
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const chip = parseChip(params.get(STATUS_PARAM))
  const query = params.get(QUERY_PARAM) ?? ''
  const open = parseGroup(params.get(GROUP_PARAM))
  // The group expanded on arrival (coming back from its screen) is shown and gets focus only once
  // (`arrived`); and it stays in the list even if it no longer matches the chip or the search
  // (`pinned`) until either of them changes.
  const [arrived, setArrived] = useState(open)
  const [pinned, setPinned] = useState(open)
  const shown = withPinned(data.groups, filterGroups(data.groups, chip, query), pinned)
  const counts = chipCounts(data.groups)

  const update = (next: Parameters<typeof sharedParams>[1]) => {
    if (next.chip !== undefined || next.query !== undefined) setPinned(null)
    // From the current URL, not the last render's: two changes in a row (a chip and right away
    // the search) do not overwrite each other.
    const current = new URLSearchParams(window.location.search)
    setParams(sharedParams(current, next), { replace: true })
  }
  const fromFor = (id: number) =>
    `${location.pathname}?${sharedParams(params, { group: id }).toString()}`

  return (
    <div className="flex max-w-[960px] min-w-0 flex-col gap-6">
      <Figures data={data} />
      {panel}
      <section
        aria-label={t('shared.groupsLabel')}
        className={cn(PANEL, 'flex min-w-0 flex-col gap-3 px-5 pt-4 pb-2 sm:px-6')}
      >
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            aria-label={t('shared.searchLabel')}
            placeholder={t('shared.searchPlaceholder')}
            value={query}
            onChange={(event) => update({ query: event.target.value })}
            className={cn(FIELD, 'flex-[1_1_240px]')}
          />
          {newGroup}
        </div>
        <div role="group" aria-label={t('shared.chipsLabel')} className="flex flex-wrap gap-2">
          {CHIPS.map((c) => (
            <ChipButton
              key={c.chip}
              label={c.label}
              count={counts[c.chip]}
              pressed={chip === c.chip}
              onClick={() => update({ chip: c.chip })}
            />
          ))}
        </div>
        {shown.length === 0 ? (
          <p className="py-3 text-sm text-muted-foreground">{noneText(chip, query)}</p>
        ) : (
          <ul aria-label={t('shared.listLabel')} className="flex flex-col">
            {shown.map((group) => (
              <GroupRow
                key={group.id}
                group={group}
                expanded={open === group.id}
                reveal={arrived === group.id}
                onRevealed={() => setArrived(null)}
                from={fromFor(group.id)}
                onToggle={() => update({ group: open === group.id ? null : group.id })}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

interface ChipButtonProps {
  label: string
  count: number
  pressed: boolean
  onClick: () => void
}

function ChipButton({ label, count, pressed, onClick }: ChipButtonProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        'inline-flex min-h-11 items-center gap-1.5 rounded-full border px-4 text-sm font-semibold',
        pressed
          ? 'border-transparent bg-secondary text-secondary-foreground'
          : 'border-[#D6D6D0] bg-card text-ink-2 hover:bg-muted',
        FOCUS,
      )}
    >
      {label}
      <span className="font-medium text-muted-foreground tabular-nums">{count}</span>
    </button>
  )
}

function Figures({ data }: { data: SharedList }) {
  return (
    <section aria-label={t('shared.totalsLabel')} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {sharedFigures(data).map((figure) => (
        <div key={figure.key} className={cn(PANEL, 'flex flex-col gap-1 px-5 py-4')}>
          <span className="text-[13px] font-medium text-ink-2">{figure.label}</span>
          <strong
            data-testid={`shared-${figure.key}`}
            className="text-[24px] leading-tight font-bold tracking-[-0.01em] whitespace-nowrap tabular-nums"
          >
            {figure.value}
          </strong>
          {figure.extra && (
            <span className="text-[13px] text-muted-foreground">{figure.extra}</span>
          )}
        </div>
      ))}
    </section>
  )
}

function Empty({ text, children }: { text: string; children: ReactNode }) {
  return (
    <div
      className={cn(PANEL, 'flex max-w-[960px] flex-col items-center gap-2 px-6 py-10 text-center')}
    >
      <p className="text-[15px] font-semibold">{text}</p>
      <p className="text-[13px] text-muted-foreground">
        {t('shared.emptyHelp')}
      </p>
      {children}
    </div>
  )
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label={t('shared.loading')} className="flex flex-col gap-6">
      <Skeleton className="h-9 w-56 rounded-[10px]" />
      <div className="grid max-w-[960px] grid-cols-1 gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-64 max-w-[960px] rounded-2xl" />
    </div>
  )
}
