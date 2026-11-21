import type { ReactNode } from 'react'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import type { Summary } from '@/lib/api'
import { useBudgetOverview } from '@/lib/budgetQueries'
import {
  budgetHref,
  fillRows,
  type Invitation,
  recurringHref,
  recurringSource,
  SHARED_GROUPS_PATH,
  upcoming,
  visibleInvitations,
} from '@/lib/home'
import { useDismissedInvitations, usePace } from '@/lib/homeQueries'
import { localToday } from '@/lib/months'
import { pendingHref } from '@/lib/pending'
import { cashSource, CASH_ACCOUNT_HREF } from '@/lib/cashBox'
import { useCashBox, usePending, useRecurring } from '@/lib/queries'
import { useSharedHome } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { BudgetCard } from './BudgetCard'
import { CategoriesCard } from './CategoriesCard'
import { FlowCard } from './FlowCard'
import { InvitationCard } from './InvitationCard'
import { LatestCard } from './LatestCard'
import { ReviewCountCard } from './ReviewCountCard'
import { SharedCard } from './SharedCard'
import { SpendingCard } from './SpendingCard'
import { UpcomingCard } from './UpcomingCard'

interface HomeCardsProps {
  summary: Summary
  selection: Selection
}

/** A slot of the stack: its card, or (when the card does not apply yet) its invitation. */
interface Slot {
  id: string
  /** Spans two columns from the tablet up. */
  wide?: boolean
  /** Whether the card applies; undefined while that is loading. Without it, it always applies. */
  invitation?: { kind: Invitation; applies: boolean | undefined; href: string }
  card: () => ReactNode
}

/** The Summary's cards, in one ordered list: one column on a phone, two on a tablet and three on
 * a desktop («Month spending» across two). The cards of a row stretch to the same height, so
 * rows have no holes. A card that does not apply yet becomes an invitation (at most two at once,
 * by usefulness, each dismissible); the invitations shown go together in one row, where the
 * first of them would be; the rest stay hidden. */
export function HomeCards({ summary, selection }: HomeCardsProps) {
  const month = summary.option.month
  const overview = useBudgetOverview(month, selection)
  const recurring = useRecurring(month, selection)
  const shared = useSharedHome()
  const pending = usePending(selection)
  const cash = useCashBox()
  const cashSchedules = cash.data?.schedules ?? []
  const pace = usePace(month, selection)
  const [dismissed, dismiss] = useDismissedInvitations()
  const today = pace.data?.today ?? localToday()

  const recurringLink = recurringHref(selection)
  const slots: Slot[] = [
    {
      id: 'spending',
      wide: true,
      card: () => <SpendingCard summary={summary} selection={selection} />,
    },
    { id: 'flow', card: () => <FlowCard summary={summary} selection={selection} /> },
    {
      id: 'budget',
      invitation: {
        kind: 'budget',
        // Without the overview, the card says why (its own error).
        applies: overview.isError ? true : overview.data?.active,
        href: budgetHref(month, selection),
      },
      card: () => <BudgetCard month={month} selection={selection} />,
    },
    { id: 'review', card: () => <ReviewCountCard month={month} selection={selection} /> },
    {
      id: 'upcoming',
      invitation: {
        kind: 'recurring',
        // Undefined (not shown yet) until both sources answer: no card swapping in later.
        applies:
          recurring.isError || cashSchedules.length > 0
            ? true
            : cash.isPending
              ? undefined
              : recurring.data && recurring.data.items.length > 0,
        href: recurringLink,
      },
      card: () => (
        <UpcomingCard
          items={upcoming(
            [
              recurringSource(recurring.data?.items ?? [], recurringLink),
              cashSource(cashSchedules, CASH_ACCOUNT_HREF),
            ],
            today,
          )}
          alerts={recurring.data?.alerts ?? []}
          today={today}
          href={recurringLink}
          failure={
            recurring.isError
              ? { error: recurring.error, retry: () => void recurring.refetch() }
              : undefined
          }
        />
      ),
    },
    { id: 'latest', card: () => <LatestCard month={month} selection={selection} /> },
    {
      id: 'shared',
      invitation: {
        kind: 'shared',
        applies: shared.isError
          ? true
          : shared.data && (shared.data.groups.length > 0 || shared.data.people.length > 0),
        href: SHARED_GROUPS_PATH,
      },
      card: () => (
        <SharedCard
          totals={shared.data?.totals ?? []}
          href="/shared"
          pending={pending.data}
          pendingHref={pendingHref(selection)}
          failure={
            shared.isError ? { error: shared.error, retry: () => void shared.refetch() } : undefined
          }
        />
      ),
    },
    {
      id: 'categories',
      card: () => (
        <CategoriesCard month={month} categories={summary.categories} selection={selection} />
      ),
    },
  ]

  const notApplying = new Set(
    slots.flatMap((slot) =>
      slot.invitation && slot.invitation.applies === false ? [slot.invitation.kind] : [],
    ),
  )
  const invited = visibleInvitations(notApplying, dismissed)
  const invitationSlots = slots.filter(
    (slot) => slot.invitation && invited.includes(slot.invitation.kind),
  )

  // What goes in the grid, in order: each card that applies, and the invitations shown together
  // (a whole row) in place of the first one.
  const items = slots.flatMap((slot): GridItem[] => {
    const invitation = slot.invitation
    if (!invitation || invitation.applies === true) {
      return [{ key: slot.id, span: slot.wide ? 2 : 1, node: slot.card() }]
    }
    if (invitationSlots[0]?.id !== slot.id) return []
    const node = invitationSlots.map(({ invitation: shown }) =>
      shown ? (
        <InvitationCard
          key={shown.kind}
          kind={shown.kind}
          href={shown.href}
          onDismiss={() => dismiss(shown.kind)}
        />
      ) : null,
    )
    return [{ key: 'invitations', span: Infinity, node, invitations: true }]
  })
  const tablet = fillRows(
    items.map((item) => item.span),
    2,
  )
  const desktop = fillRows(
    items.map((item) => item.span),
    3,
  )

  return (
    <div
      data-testid="summary-cards"
      aria-label={t('home.cards.label')}
      role="region"
      className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
    >
      {items.map((item, index) => (
        <div
          key={item.key}
          data-testid={item.invitations ? 'invitations' : undefined}
          className={cn(
            'grid min-w-0',
            TABLET_SPAN[tablet[index]],
            DESKTOP_SPAN[desktop[index]],
            // One invitation takes the whole row; two share it.
            item.invitations && 'gap-4 md:grid-cols-[repeat(auto-fit,minmax(260px,1fr))]',
          )}
        >
          {item.node}
        </div>
      ))}
    </div>
  )
}

interface GridItem {
  key: string
  span: number // columns wanted (Infinity: a whole row)
  node: ReactNode
  invitations?: boolean
}

const TABLET_SPAN: Record<number, string> = { 1: 'md:col-span-1', 2: 'md:col-span-2' }
const DESKTOP_SPAN: Record<number, string> = {
  1: 'xl:col-span-1',
  2: 'xl:col-span-2',
  3: 'xl:col-span-3',
}
