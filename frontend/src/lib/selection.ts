// Multiple selection in Transactions (pure logic). The rules on what changes live on the server
// (src/michelito/web/batch_edit.py); here, what is offered and how it is said.
import { type MessageKey, t } from '@/i18n'
import type { BatchResult, Category, LinkKind, SkipReason, Tx } from './api'
import { choosable } from './categories'
import { formatDop } from './money'

/** The maximum size of a batch (`batch_edit.BATCH_MAX`). */
export const BATCH_MAX = 500

/** The links that fix the category of their transactions (the server skips them). */
const FIXED_BY_LINK: readonly LinkKind[] = ['cash_box', 'investment', 'reimbursement', 'group', 'exchange']

export function fixedByLink(tx: Pick<Tx, 'link'>): boolean {
  return FIXED_BY_LINK.includes(tx.link)
}

/** The chosen ones still in the list (when filters change, those that leave are dropped). */
export function visibleChosen<T extends Pick<Tx, 'fingerprint'>>(
  items: readonly T[],
  chosen: ReadonlySet<string>,
): T[] {
  return items.filter((t) => chosen.has(t.fingerprint))
}

/** The chosen ones still in `items` (the same set if none leaves): when filters change, those no
 * longer shown are dropped and do not come back when the filter is removed. */
export function pruned(
  chosen: ReadonlySet<string>,
  items: readonly Pick<Tx, 'fingerprint'>[],
): ReadonlySet<string> {
  const present = new Set(items.map((t) => t.fingerprint))
  if ([...chosen].every((fp) => present.has(fp))) return chosen
  return new Set([...chosen].filter((fp) => present.has(fp)))
}

/** The visible rows: with groups (category, merchant), only those of the open groups. */
export function visibleRows<T>(
  groups: readonly { key: string; items: readonly T[] }[],
  open: ReadonlySet<string>,
): T[] {
  return groups.filter((g) => open.has(g.key)).flatMap((g) => [...g.items])
}

/** Adds or removes a fingerprint (returns a new set). */
export function toggled(chosen: ReadonlySet<string>, fingerprint: string): Set<string> {
  const next = new Set(chosen)
  if (!next.delete(fingerprint)) next.add(fingerprint)
  return next
}

type Counted = Pick<Tx, 'amount_cents' | 'amount_dop_cents'>

/** "<count> · RD$ 15,000" (RD$ amounts unsigned); with debits and credits mixed, "<count> ·
 * <in> · <out>"; those without a rate (US$ of a month without a rate) do not add up and the text
 * says how many. */
export function counterText(items: readonly Counted[]): string {
  const count = t('common.selection.count', { count: items.length })
  const rated = items.filter((t) => t.amount_dop_cents !== null)
  const sum = (list: readonly Counted[]) =>
    list.reduce((total, t) => total + Math.abs(t.amount_dop_cents ?? 0), 0)
  const incoming = rated.filter((t) => t.amount_cents < 0)
  const outgoing = rated.filter((t) => t.amount_cents >= 0)
  const money =
    incoming.length && outgoing.length
      ? t('common.selection.inOut', {
          incoming: formatDop(sum(incoming)),
          outgoing: formatDop(sum(outgoing)),
        })
      : formatDop(sum(rated))
  const unrated = items.length - rated.length
  const missing = unrated === 0 ? '' : ` · ${t('common.selection.unrated', { count: unrated })}`
  return `${count} · ${money}${missing}`
}

export interface BatchOptions {
  categories: Category[]
  notice: string | null
}

/** The categories offered for the chosen ones: without hidden ones or those set by their link;
 * with any debit, no income ones either (a debit is not income). With debits and credits mixed,
 * a notice says why income is missing. */
export function batchOptions(
  categories: readonly Category[],
  items: readonly Pick<Tx, 'amount_cents'>[],
): BatchOptions {
  const debits = items.some((t) => t.amount_cents > 0)
  const credits = items.some((t) => t.amount_cents < 0)
  const shown = choosable(categories).filter((c) => !c.hidden && !(debits && c.kind === 'income'))
  const notice =
    debits && credits ? t('common.selection.mixedNotice') : null
  return { categories: shown, notice }
}

/** How many chosen ones a link fixes (they will not change), to warn beforehand. */
export function linkedText(items: readonly Pick<Tx, 'link'>[]): string | null {
  const count = items.filter(fixedByLink).length
  if (count === 0) return null
  return t('common.selection.linked', { count })
}

const SKIPPED = {
  cash_box: 'common.selection.skipped.cashBox',
  linked: 'common.selection.skipped.linked',
  direction: 'common.selection.skipped.direction',
  unchanged: 'common.selection.skipped.unchanged',
  unknown: 'common.selection.skipped.unknown',
} as const satisfies Record<SkipReason, MessageKey>
const ORDER: readonly SkipReason[] = [
  'linked',
  'cash_box',
  'direction',
  'unchanged',
  'unknown',
]

/** How many moved to `category`, then each reason some were skipped, joined with " · ". */
export function resultText(result: BatchResult, category: string): string {
  const applied = result.applied.length
  const head = t('common.selection.applied', { count: applied, category })
  const parts = ORDER.flatMap((reason) => {
    const count = result.skipped.filter((s) => s.reason === reason).length
    if (count === 0) return []
    return [t(SKIPPED[reason], { count })]
  })
  return [head, ...parts].join(' · ')
}
