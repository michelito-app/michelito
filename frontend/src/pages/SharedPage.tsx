import { ChevronDown, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { LoadError } from '@/components/LoadError'
import { AddExpenseButton } from '@/components/shared/AddExpenseButton'
import { AddExpenseSheet } from '@/components/shared/AddExpenseSheet'
import { NewGroupSheet } from '@/components/shared/NewGroupSheet'
import { Avatar, PageTitle } from '@/components/shared/parts'
import { LIST_CARD, ROW_BUTTON, TONE_CLASS } from '@/components/shared/styles'
import { ReviewPeopleSheet } from '@/components/shared/ReviewPeopleSheet'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { EmptyState, SharedIllustration } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { LinkedTx } from '@/lib/api'
import {
  balanceTone,
  groupBalanceText,
  groupSides,
  personBalanceText,
  splitSettled,
  totalsLines,
} from '@/lib/ledger'
import { formatMoney, groupPath } from '@/lib/links'
import { shortDay } from '@/lib/months'
import type { GroupRow, Person, SharedHome } from '@/lib/sharedApi'
import { useSharedHome } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'

type View = 'people' | 'groups'

/** `?view=`: People (default) or Groups; kept in the URL so Back restores it. */
function viewOf(params: URLSearchParams): View {
  return params.get('view') === 'groups' ? 'groups' : 'people'
}

/** Shared: the net balance on top, People | Groups, and one "+ Add expense" (floating above
 * the bottom bar on a phone, a header button on a wider screen). */
export function SharedPage() {
  const home = useSharedHome()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
  const view = viewOf(params)
  const [adding, setAdding] = useState<{ tx: LinkedTx | null } | null>(null)
  const [creating, setCreating] = useState(false)
  const [reviewDone, setReviewDone] = useState(false)
  const from = { from: `${location.pathname}${location.search}` }

  function openGroup(id: number) {
    navigate(groupPath(id), { state: from })
  }

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <PageTitle>{t('shared.title')}</PageTitle>
      <AddExpenseButton onClick={() => setAdding({ tx: null })} />
    </div>
  )

  if (home.isPending) {
    return (
      <div aria-busy="true" aria-label={t('shared.loading')} className="flex flex-col gap-5">
        {header}
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    )
  }
  if (home.isError) {
    return (
      <div className="flex flex-col gap-5">
        {header}
        <LoadError what={t('shared.load')} error={home.error} onRetry={() => home.refetch()} />
      </div>
    )
  }

  const data = home.data
  const empty = data.groups.length === 0
  return (
    <div className="flex min-w-0 flex-col gap-5 max-md:pb-16">
      {header}
      {empty ? (
        data.suggestions.length > 0 ? (
          <Suggestions items={data.suggestions} onSplit={(tx) => setAdding({ tx })} />
        ) : (
          <EmptyState
            icon={<SharedIllustration />}
            title={t('shared.empty.title')}
            text={t('shared.empty.text')}
            action={{ label: t('shared.empty.action'), onClick: () => setCreating(true) }}
          />
        )
      ) : (
        <>
          <Totals data={data} />
          <div
            role="group"
            aria-label={t('shared.view.label')}
            className="grid grid-cols-2 gap-1 rounded-xl bg-muted p-1"
          >
            {(['people', 'groups'] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={view === option}
                onClick={() =>
                  setParams(
                    (current) => {
                      const next = new URLSearchParams(current)
                      if (option === 'people') next.delete('view')
                      else next.set('view', option)
                      return next
                    },
                    { replace: true },
                  )
                }
                className={cn(
                  'min-h-11 rounded-lg text-sm font-semibold',
                  FOCUS,
                  view === option ? 'bg-card text-foreground shadow-sm' : 'text-ink-2',
                )}
              >
                {option === 'people' ? t('shared.view.people') : t('shared.view.groups')}
              </button>
            ))}
          </div>
          {view === 'people' ? (
            <PeopleList people={data.people} from={from} />
          ) : (
            <GroupList groups={data.groups} onOpen={openGroup} onNew={() => setCreating(true)} />
          )}
        </>
      )}

      {adding && (
        <AddExpenseSheet
          tx={adding.tx}
          onClose={() => setAdding(null)}
          onSaved={(group) => {
            setAdding(null)
            openGroup(group.id)
          }}
        />
      )}
      {creating && (
        <NewGroupSheet
          onClose={() => setCreating(false)}
          onCreated={(group) => {
            setCreating(false)
            openGroup(group.id)
          }}
        />
      )}
      {data.review_people && !reviewDone && (
        <ReviewPeopleSheet people={data.people} onClose={() => setReviewDone(true)} />
      )}
    </div>
  )
}

function Totals({ data }: { data: SharedHome }) {
  const lines = totalsLines(data.totals)
  const [first, ...rest] = lines
  return (
    <section aria-label={t('shared.totals.label')} className={cn(PANEL, 'flex flex-col gap-1 px-5 py-4')}>
      <p data-testid="shared-totals" className="text-[22px] leading-tight font-bold tracking-[-0.01em]">
        {first ?? t('shared.totals.none')}
      </p>
      {rest.map((line) => (
        <p key={line} className="text-[15px] font-semibold text-ink-2">
          {line}
        </p>
      ))}
    </section>
  )
}

function PeopleList({ people, from }: { people: Person[]; from: { from: string } }) {
  const [open, setOpen] = useState(false)
  const { open: owing, settled } = splitSettled(people)
  return (
    <div className="flex flex-col gap-3">
      {owing.length > 0 ? (
        <ul aria-label={t('shared.people.label')} className={LIST_CARD}>
          {owing.map((person) => (
            <PersonRow key={person.id} person={person} from={from} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{t('shared.people.none')}</p>
      )}
      {settled.length > 0 && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            aria-expanded={open}
            aria-controls="settled-people"
            onClick={() => setOpen((value) => !value)}
            className={cn(
              '-mx-2 inline-flex min-h-11 items-center gap-1.5 self-start rounded-lg px-2 text-sm font-semibold text-ink-2 hover:bg-muted',
              FOCUS,
            )}
          >
            <ChevronDown
              size={16}
              aria-hidden="true"
              className={cn('transition-transform', !open && '-rotate-90')}
            />
            {t('shared.people.settled', { count: settled.length })}
          </button>
          {open && (
            <ul id="settled-people" aria-label={t('shared.people.settledLabel')} className={LIST_CARD}>
              {settled.map((person) => (
                <PersonRow key={person.id} person={person} from={from} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function PersonRow({ person, from }: { person: Person; from: { from: string } }) {
  const tone = balanceTone(person.balance)
  return (
    <li>
      <Link to={`/shared/people/${person.id}`} state={from} className={ROW_BUTTON}>
        <Avatar name={person.name} />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[15px] font-semibold">{person.name}</span>
          <span className="text-[13px] text-muted-foreground">
            {t('shared.people.inGroups', { count: person.group_count })}
          </span>
        </span>
        <span className={cn('shrink-0 text-right text-sm font-semibold', TONE_CLASS[tone])}>
          {personBalanceText(person.balance)}
        </span>
      </Link>
    </li>
  )
}

function GroupList({
  groups,
  onOpen,
  onNew,
}: {
  groups: GroupRow[]
  onOpen: (id: number) => void
  onNew: () => void
}) {
  return (
    <div className="flex flex-col gap-3">
      <ul aria-label={t('shared.groups.label')} className={LIST_CARD}>
        {groups.map((group) => {
          const parts = groupSides(group.owed_to_me, group.i_owe)
          const tone = balanceTone(parts)
          return (
            <li key={group.id}>
              <button type="button" onClick={() => onOpen(group.id)} className={ROW_BUTTON}>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-[15px] font-semibold">{group.name}</span>
                  <span className="truncate text-[13px] text-muted-foreground">
                    {[
                      group.people.join(', '),
                      group.archived ? t('shared.groups.archived') : '',
                      group.unattributed
                        ? t('shared.groups.unattributed', { count: group.unattributed })
                        : '',
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </span>
                <span className={cn('shrink-0 text-right text-sm font-semibold', TONE_CLASS[tone])}>
                  {groupBalanceText(parts)}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      <button
        type="button"
        onClick={onNew}
        className={cn(
          'inline-flex min-h-11 items-center gap-2 self-start rounded-xl border border-border bg-card px-4 text-sm font-semibold text-primary hover:bg-muted',
          FOCUS,
        )}
      >
        <Plus size={16} aria-hidden="true" />
        {t('shared.groups.new')}
      </button>
    </div>
  )
}

/** No groups yet, but expenses that look shared: "These dinners look shared" with
 * "Split" (straight to "I paid it" with it). */
function Suggestions({ items, onSplit }: { items: LinkedTx[]; onSplit: (tx: LinkedTx) => void }) {
  return (
    <section aria-labelledby="shared-suggestions" className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
      <div className="flex flex-col gap-1">
        <h2 id="shared-suggestions" className="text-[17px] font-[650] tracking-tight">
          {t('shared.suggestions.title')}
        </h2>
        <p className="text-[13px] text-muted-foreground">{t('shared.suggestions.text')}</p>
      </div>
      <ul className={LIST_CARD}>
        {items.map((tx) => (
          <li key={tx.fingerprint} className="flex items-center gap-3 px-3.5 py-2">
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-sm font-semibold">{tx.merchant}</span>
              <span className="truncate text-[13px] text-muted-foreground">
                {shortDay(tx.day)} · {formatMoney(Math.abs(tx.amount_cents), tx.currency)}
              </span>
            </span>
            <button
              type="button"
              aria-label={t('shared.suggestions.splitLabel', { merchant: tx.merchant })}
              onClick={() => onSplit(tx)}
              className={cn(
                'inline-flex min-h-11 shrink-0 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/85',
                FOCUS,
              )}
            >
              {t('shared.suggestions.split')}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
