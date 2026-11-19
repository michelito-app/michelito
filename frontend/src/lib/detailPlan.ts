// The phone's transaction detail (pure logic): what the transaction already belongs to (shown
// on top with "Open") and which actions apply to it (the "More actions" list).
import { t } from '@/i18n'
import type { Tx } from './api'
import { showCashBox } from './cashBox'
import { linkSummaries, showExchange, showInvestment, showReimbursement } from './links'

/** What a sheet of the phone's detail holds. */
export type SheetKind =
  | 'category'
  | 'note'
  | 'oneOff'
  | 'shared'
  | 'reimbursement'
  | 'exchange'
  | 'investment'
  | 'cashBox'
  | 'reserve'
  | 'recurring'
  | 'history'

export interface LinkLine {
  kind: SheetKind
  title: string
  text: string
}

/** What the transaction already belongs to (shown on top) and what else can be done with it
 * (the "More actions" list): only what applies to its direction, type and state. */
export interface DetailPlan {
  links: LinkLine[]
  actions: SheetKind[]
  /** Why the expense cannot go to a reserve (a one-line note, not an action), or null. */
  reserveNote: string | null
}

/** A reserve as the transaction sees it: the one covering it, whether it can be linked now and,
 * if not, why. */
export interface ReserveState {
  linked: string | null
  canLink: boolean
  reason: string
}

export interface PlanInput {
  tx: Tx
  reserve: ReserveState
  recurring: { linked: string | null; available: boolean }
}

/** Pure: the links and the actions of the phone's detail. */
export function detailPlan({ tx, reserve, recurring }: PlanInput): DetailPlan {
  const links: LinkLine[] = linkSummaries(tx)
    .filter((summary) => tx.link === summary.kind)
    .map((summary) => ({ kind: summary.kind, title: summary.title, text: summary.text }))
  const cashLinked = tx.cash_box_role !== '' || tx.cash_entry_id !== null
  if (cashLinked) {
    links.push({
      kind: 'cashBox',
      title: t('transactions.actions.cashBox'),
      text: t('transactions.links.cashBox'),
    })
  }
  if (reserve.linked !== null) {
    links.push({
      kind: 'reserve',
      title: t('transactions.actions.reserve'),
      text: t('transactions.reserve.covered', { name: reserve.linked }),
    })
  }
  if (recurring.linked !== null) {
    links.push({
      kind: 'recurring',
      title: t('transactions.actions.recurring'),
      text: t('transactions.recurring.state', { name: recurring.linked }),
    })
  }
  const linked = new Set(links.map((line) => line.kind))
  const actions: SheetKind[] = []
  const offer = (kind: SheetKind, applies: boolean) => {
    if (applies && !linked.has(kind)) actions.push(kind)
  }
  offer('oneOff', tx.kind === 'expense')
  offer('reimbursement', showReimbursement(tx))
  offer('investment', showInvestment(tx))
  offer('cashBox', showCashBox(tx))
  // Only when it can really be linked; otherwise the reason, at most, as a note.
  offer('reserve', reserve.linked === null && reserve.canLink)
  offer('recurring', recurring.available)
  offer('exchange', showExchange(tx))
  actions.push('history')
  const reserveNote =
    reserve.linked === null && !reserve.canLink && reserve.reason ? reserve.reason : null
  return { links, actions, reserveNote }
}
