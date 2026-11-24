import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { LoadError } from '@/components/LoadError'
import { AddExpenseButton } from '@/components/shared/AddExpenseButton'
import { AddExpenseSheet } from '@/components/shared/AddExpenseSheet'
import { GroupMenu } from '@/components/shared/GroupMenu'
import { GroupTimeline } from '@/components/shared/GroupTimeline'
import { ItemSheet } from '@/components/shared/ItemSheet'
import { Avatar, BackButton, MenuButton, PageTitle } from '@/components/shared/parts'
import { TONE_CLASS } from '@/components/shared/styles'
import { CoverPlanSheet } from '@/components/shared/CoverPlanSheet'
import { PaymentSheet } from '@/components/shared/PaymentSheet'
import { UnattributedSheet } from '@/components/shared/UnattributedSheet'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { ApiError } from '@/lib/api'
import { approxText, balanceTone, groupSentence, groupSides, memberBalanceText } from '@/lib/ledger'
import { moneyList } from '@/lib/links'
import type { CoverSuggestion, Group, Payment, TimelineItem } from '@/lib/sharedApi'
import { ledger, useGroup, useLedgerWrite } from '@/lib/sharedQueries'
import { useTags } from '@/lib/tagQueries'
import { cn } from '@/lib/utils'

type Open =
  | { kind: 'add' }
  | { kind: 'menu' }
  | { kind: 'pay'; person: number | null }
  | { kind: 'link'; payment: Payment }
  | { kind: 'item'; item: TimelineItem }
  | { kind: 'plan' }
  | { kind: 'unattributed' }

/** A group's page (`/shared/<id>`): Back, name and "⋯"; the one-sentence balance with "Record
 * payment"; per-person cards (tap: a prefilled payment); unattributed payments; the timeline. */
export function SharedGroupPage() {
  const { id = '' } = useParams()
  const groupId = Number(id)
  const query = useGroup(Number.isInteger(groupId) ? groupId : null)
  const [open, setOpen] = useState<Open | null>(null)
  // `?cover=<payment>` ("To review"'s "Yes"): the group's suggestion reviewed in one sheet, once.
  const [params, setParams] = useSearchParams()
  const coverParam = Number(params.get('cover'))
  const [coverOpened, setCoverOpened] = useState<number | null>(null)
  const close = () => {
    setOpen(null)
    if (params.has('cover')) setParams({}, { replace: true })
  }
  if (coverParam && coverParam !== coverOpened && query.data) {
    setCoverOpened(coverParam)
    if (query.data.cover?.payment_ids.includes(coverParam)) setOpen({ kind: 'plan' })
  }

  if (query.isPending) {
    return (
      <div aria-busy="true" aria-label={t('shared.loading')} className="flex flex-col gap-5">
        <BackButton fallback="/shared?view=groups" />
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    )
  }
  if (query.isError) {
    const missing = query.error instanceof ApiError && query.error.status === 404
    return (
      <div className="flex flex-col gap-4">
        <BackButton fallback="/shared?view=groups" />
        {missing ? (
          <p className={cn(PANEL, 'px-6 py-10 text-center text-sm')}>{t('shared.group.notFound')}</p>
        ) : (
          <LoadError what={t('shared.load')} error={query.error} onRetry={() => query.refetch()} />
        )}
      </div>
    )
  }

  const group = query.data
  // The open row follows the fresh group (after a write); a deleted one keeps its sheet (undo).
  const item =
    open?.kind === 'item'
      ? (group.timeline.find((i) => i.kind === open.item.kind && i.id === open.item.id) ??
        open.item)
      : null

  return (
    <div className="flex min-w-0 flex-col gap-5 max-md:pb-16">
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <BackButton fallback="/shared?view=groups" />
          <MenuButton
            label={t('shared.menuOf', { name: group.name })}
            onClick={() => setOpen({ kind: 'menu' })}
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <PageTitle key={group.id}>{group.name}</PageTitle>
          <AddExpenseButton onClick={() => setOpen({ kind: 'add' })} />
        </div>
        {group.archived && (
          <p className="text-[13px] text-muted-foreground">{t('shared.group.archivedNote')}</p>
        )}
        <GroupTagLink groupId={group.id} />
      </div>

      <Balance group={group} onPay={(person) => setOpen({ kind: 'pay', person })} />

      {group.cover && (
        <CoverNotice cover={group.cover} onYes={() => setOpen({ kind: 'plan' })} group={group} />
      )}

      {group.unattributed.length > 0 && (
        <div
          data-testid="unattributed-band"
          className="flex items-center justify-between gap-3 rounded-xl border border-dashed border-up/40 bg-up-soft px-3.5 py-1.5 text-sm text-up-ink"
        >
          <span className="min-w-0 font-semibold">
            {t('shared.unattributed.band', { count: group.unattributed.length })}
          </span>
          <button
            type="button"
            onClick={() => setOpen({ kind: 'unattributed' })}
            className={cn(
              'inline-flex min-h-11 shrink-0 items-center rounded-xl px-3 font-semibold text-primary hover:bg-card/60',
              FOCUS,
            )}
          >
            {t('shared.unattributed.assign')}
          </button>
        </div>
      )}

      <GroupTimeline
        items={group.timeline}
        onOpen={(i) => setOpen({ kind: 'item', item: i })}
        onLink={(payment) => setOpen({ kind: 'link', payment })}
      />

      {open?.kind === 'add' && (
        <AddExpenseSheet groupId={group.id} onClose={close} onSaved={close} />
      )}
      {open?.kind === 'menu' && <GroupMenu group={group} onClose={close} />}
      {open?.kind === 'pay' && <PaymentSheet group={group} personId={open.person} onClose={close} />}
      {open?.kind === 'link' && <PaymentSheet group={group} linking={open.payment} onClose={close} />}
      {open?.kind === 'unattributed' && <UnattributedSheet group={group} onClose={close} />}
      {item && (
        <ItemSheet
          group={group}
          item={item}
          onClose={close}
          onLink={(payment) => setOpen({ kind: 'link', payment })}
        />
      )}
      {open?.kind === 'plan' && group.cover && (
        <CoverPlanSheet group={group} cover={group.cover} onClose={close} />
      )}
    </div>
  )
}

/** "Owed to you RD$ 2,100 in this group" with "Record payment", and a card per person (scrolls
 * sideways) that opens the payment prefilled with them. */
function Balance({ group, onPay }: { group: Group; onPay: (person: number | null) => void }) {
  const others = group.members.filter((m) => !m.is_me)
  const parts = groupSides(group.owed_to_me, group.i_owe)
  const tone = balanceTone(parts)
  return (
    <section aria-label={t('shared.totals.label')} className={cn(PANEL, 'flex flex-col gap-3 px-4 py-4 sm:px-5')}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <p data-testid="group-sentence" className={cn('text-[17px] font-bold', TONE_CLASS[tone])}>
            {groupSentence(parts)}
          </p>
          {group.total && (
            <p data-testid="group-total" className="text-[13px] font-medium text-muted-foreground">
              {approxText(group.total)}
            </p>
          )}
        </div>
        {others.length > 0 && (
          <button
            type="button"
            aria-haspopup="dialog"
            onClick={() => onPay(null)}
            className={cn(
              'inline-flex min-h-11 shrink-0 items-center rounded-xl border border-border bg-card px-4 text-sm font-semibold text-ink-2 hover:bg-muted',
              FOCUS,
            )}
          >
            {t('shared.group.recordPayment')}
          </button>
        )}
      </div>
      {group.excess.length > 0 && (
        <p className="text-[13px] text-muted-foreground">
          {t('shared.group.excess', { amount: moneyList(group.excess) })}
        </p>
      )}
      {others.length > 0 && (
        <ul
          aria-label={t('shared.group.cards')}
          className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1 sm:-mx-5 sm:px-5"
        >
          {others.map((member) => {
            const balance = memberBalanceText(member)
            const total = approxText(member.total)
            return (
              <li key={member.id} className="shrink-0 snap-start">
                <button
                  type="button"
                  aria-haspopup="dialog"
                  aria-label={t('shared.group.cardLabel', { name: member.name, balance })}
                  onClick={() => onPay(member.id)}
                  className={cn(
                    'flex min-h-11 w-40 flex-col items-start gap-1 rounded-xl border border-border bg-card px-3 py-2.5 text-left hover:bg-muted',
                    FOCUS,
                  )}
                >
                  <span className="flex w-full min-w-0 items-center gap-2">
                    <Avatar name={member.name} />
                    <span className="min-w-0 truncate text-sm font-semibold">{member.name}</span>
                  </span>
                  <span className={cn('text-[13px] font-semibold', TONE_CLASS[balanceTone(member.balance)])}>
                    {member.written_off ? t('shared.person.writtenOff') : balance}
                  </span>
                  {total && !member.written_off && (
                    <span className="text-[12px] text-muted-foreground">{total}</span>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

interface CoverNoticeProps {
  group: Group
  cover: CoverSuggestion
  onYes: () => void
}

/** "Ana paid RD$ 54,644 too much in 3 payments and Beto owes US$ 990.76. Were those payments
 * for Beto too?": "Yes" opens the review of every payment (the user confirms all of them as one
 * change); "No" is kept for each of those payments, as one change (undoable in the log). */
function CoverNotice({ group, cover, onYes }: CoverNoticeProps) {
  const write = useLedgerWrite()
  return (
    <section
      aria-label={t('shared.cover.title')}
      data-testid="cover-notice"
      className="flex flex-col gap-2 rounded-xl border border-dashed border-up/40 bg-up-soft px-3.5 py-3 text-sm text-up-ink"
    >
      <p className="min-w-0 font-semibold break-words">{cover.text}</p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          aria-haspopup="dialog"
          aria-label={t('shared.cover.yesLabel', { name: cover.payer_name })}
          onClick={onYes}
          className={cn(
            'inline-flex min-h-11 items-center rounded-xl bg-primary px-4 font-semibold text-primary-foreground hover:bg-primary/85',
            FOCUS,
          )}
        >
          {t('shared.cover.yes')}
        </button>
        <button
          type="button"
          aria-label={t('shared.cover.noLabel', { name: cover.payer_name })}
          disabled={write.isPending}
          onClick={() => write.mutate(() => ledger.dismissCovers(group.id, cover.payment_ids))}
          className={cn(
            'inline-flex min-h-11 items-center rounded-xl border border-border bg-card px-4 font-semibold text-ink-2 hover:bg-muted',
            FOCUS,
          )}
        >
          {t('shared.cover.no')}
        </button>
      </div>
    </section>
  )
}

/** The group's tag (its purpose): what the trip or event cost the user, beside its debts. */
function GroupTagLink({ groupId }: { groupId: number }) {
  const tags = useTags()
  const tag = tags.data?.find((found) => found.group_id === groupId)
  if (!tag) return null
  return (
    <Link to={`/tags/${tag.id}`} className="text-[13px] font-medium text-primary underline-offset-4 hover:underline">
      {t('tags.page.title')} · {tag.name}
    </Link>
  )
}
