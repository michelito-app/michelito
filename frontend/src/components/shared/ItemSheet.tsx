import { useState } from 'react'
import { Link } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { Action, ConfirmBox, Failure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { t } from '@/i18n'
import type { LinkedTx } from '@/lib/api'
import {
  displayName,
  differenceText,
  entryLine,
  paymentLine,
  rateText,
  splitLineText,
} from '@/lib/ledger'
import { formatMoney, linkedAmount } from '@/lib/links'
import { useUndo } from '@/lib/logQueries'
import { longDay, shortDay } from '@/lib/months'
import type { Entry, Group, Payment, TimelineItem } from '@/lib/sharedApi'
import { lastLogId, ledger, useLedgerWrite } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { coverStart, useCoverDraft } from '@/lib/coverDraft'
import { payerChoices } from '@/lib/paymentPayer'
import { AlsoPaidFor } from './AlsoPaidFor'
import { ExpenseForm } from './ExpenseForm'
import { Chip } from './parts'
import { LIST_CARD } from './styles'

const LABEL = 'text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase'

interface ItemSheetProps {
  group: Group
  item: TimelineItem
  onClose: () => void
  /** "Link" an unlinked payment (the payment sheet's second step). */
  onLink: (payment: Payment) => void
  /** Open a payment's "Also paid for…" at once, with these people checked (the suggestion's
   * "Yes"); null: the plain detail. */
  cover?: readonly number[] | null
}

/** A timeline row's detail: the full split (or the payment's ends), the linked bank transaction
 * with "Open", and only the actions that apply: edit, accept a difference, link, unlink, assign
 * and delete (with undo, through the log). */
export function ItemSheet({ group, item, onClose, onLink, cover = null }: ItemSheetProps) {
  const [editing, setEditing] = useState(false)
  const [covering, setCovering] = useState<readonly number[] | null>(cover)
  const [deleted, setDeleted] = useState<{ logId: number | null } | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [changingPayer, setChangingPayer] = useState(false)
  const write = useLedgerWrite()
  const undo = useUndo()
  const title = item.kind === 'entry' ? t('shared.detail.entry') : t('shared.detail.payment')

  function remove() {
    const kind = item.kind === 'entry' ? 'group_entry_delete' : 'group_payment_delete'
    write.mutate(
      () => (item.kind === 'entry' ? ledger.deleteEntry(item.id) : ledger.deletePayment(item.id)),
      {
        onSuccess: async () => {
          setConfirming(false)
          setDeleted({ logId: await lastLogId(kind).catch(() => null) })
        },
      },
    )
  }

  if (deleted) {
    return (
      <BottomSheet title={title} onClose={onClose}>
        <p role="status" className="text-sm font-semibold">
          {undo.isSuccess ? t('shared.detail.undone') : t('shared.detail.deleted')}
        </p>
        {deleted.logId !== null && !undo.isSuccess && (
          <Action primary disabled={undo.isPending} onClick={() => undo.mutate(deleted.logId!)}>
            {t('shared.detail.undo')}
          </Action>
        )}
        <Failure error={undo.error} />
        <Action wide onClick={onClose}>
          {t('shared.done')}
        </Action>
      </BottomSheet>
    )
  }

  if (editing && item.kind === 'entry') {
    return (
      <BottomSheet title={t('shared.add.editTitle')} onClose={onClose} full>
        <ExpenseForm
          tx={null}
          groups={[]}
          groupId={group.id}
          onGroup={() => {}}
          onNewGroup={() => {}}
          entry={item}
          onSaved={onClose}
        />
      </BottomSheet>
    )
  }

  const canCover =
    item.kind === 'payment' &&
    item.to_me &&
    item.from_contact !== null &&
    group.members.filter((m) => !m.is_me).length > 1

  if (covering && item.kind === 'payment' && canCover) {
    return (
      <BottomSheet title={t('shared.detail.alsoPaidFor')} onClose={onClose}>
        <CoverBody group={group} payment={item} preselect={covering} onDone={() => setCovering(null)} />
      </BottomSheet>
    )
  }

  return (
    <BottomSheet title={title} onClose={onClose}>
      {item.kind === 'entry' ? <EntryBody entry={item} /> : <PaymentBody group={group} payment={item} />}
      <div className="flex flex-wrap gap-2">
        {item.kind === 'entry' && (
          <Action onClick={() => setEditing(true)}>{t('shared.detail.edit')}</Action>
        )}
        {canCover && (
          <Action onClick={() => setCovering([])}>{t('shared.detail.alsoPaidFor')}</Action>
        )}
        {item.kind === 'payment' && payerChoices(item, group.members).length > 0 && (
          <Action onClick={() => setChangingPayer(!changingPayer)}>{t('shared.detail.changePayer')}</Action>
        )}
        {item.kind === 'payment' && !item.transaction && (
          <Action onClick={() => onLink(item)}>{t('shared.payment.link')}</Action>
        )}
        {item.kind === 'payment' && item.transaction && (
          <Action
            disabled={write.isPending}
            onClick={() => write.mutate(() => ledger.patchPayment(item.id, { unlink: true }))}
          >
            {t('shared.detail.unlink')}
          </Action>
        )}
        {item.kind === 'payment' && item.difference_cents !== null && !item.accepted && (
          <Action
            primary
            disabled={write.isPending}
            onClick={() => write.mutate(() => ledger.patchPayment(item.id, { accepted: true }))}
          >
            {t('shared.detail.acceptDifference')}
          </Action>
        )}
        {!confirming && (
          <Action onClick={() => setConfirming(true)}>{t('shared.detail.delete')}</Action>
        )}
      </div>
      {changingPayer && item.kind === 'payment' && (
        <ChangePayer group={group} payment={item} onDone={() => setChangingPayer(false)} />
      )}
      {confirming && (
        <ConfirmBox
          label={t('shared.detail.delete')}
          confirmLabel={t('shared.detail.deleteConfirm')}
          busy={write.isPending}
          onConfirm={remove}
          onCancel={() => setConfirming(false)}
        >
          {t('shared.detail.deleteHint')}
        </ConfirmBox>
      )}
      <Failure error={write.error} />
    </BottomSheet>
  )
}

function EntryBody({ entry }: { entry: Entry }) {
  return (
    <>
      <div className="flex flex-col gap-1">
        <p className="text-[15px] font-semibold break-words">{entryLine(entry)}</p>
        <p className="text-[13px] text-muted-foreground">{longDay(entry.day)}</p>
        {entry.pending_cents > 0 && (
          <p className="text-[13px] text-down">
            {t('shared.detail.pending', { amount: formatMoney(entry.pending_cents, entry.currency) })}
          </p>
        )}
        {entry.written_off_cents > 0 && (
          <p className="text-[13px] text-muted-foreground">
            {t('shared.detail.writtenOff', {
              amount: formatMoney(entry.written_off_cents, entry.currency),
            })}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <h3 className={LABEL}>{t('shared.detail.split')}</h3>
        <ul className={LIST_CARD} aria-label={t('shared.detail.split')}>
          {entry.splits.map((split) => (
            <li key={split.contact_id} className="flex min-h-11 items-center justify-between gap-3 px-3.5 text-sm">
              <span className="min-w-0 truncate">{displayName(split.name, split.is_me)}</span>
              <span className="shrink-0 font-semibold tabular-nums">
                {splitLineText(split, entry.currency)}
              </span>
            </li>
          ))}
        </ul>
      </div>
      {entry.transaction && <BankLine tx={entry.transaction} />}
    </>
  )
}

function PaymentBody({ group, payment }: { group: Group; payment: Payment }) {
  const write = useLedgerWrite()
  const difference = differenceText(payment)
  const others = group.members.filter((m) => !m.is_me)
  return (
    <>
      <div className="flex flex-col gap-1">
        <p className="text-[15px] font-semibold break-words">{paymentLine(payment)}</p>
        <p className="text-[13px] text-muted-foreground">{longDay(payment.day)}</p>
        {difference && <p className="text-[13px] text-ink-2">{difference}</p>}
        {payment.rate && (
          <p data-testid="payment-rate" className="text-[13px] text-muted-foreground">
            {t('shared.detail.rateUsed', { rate: rateText(payment.rate) })}
          </p>
        )}
        {payment.accepted && (
          <p className="text-[13px] text-muted-foreground">{t('shared.detail.accepted')}</p>
        )}
      </div>
      {payment.allocations.length > 1 && (
        <div className="flex flex-col gap-1.5">
          <h3 className={LABEL}>{t('shared.detail.coveredFor')}</h3>
          <ul className={LIST_CARD} aria-label={t('shared.detail.coveredFor')}>
            {payment.allocations.map((part) => (
              <li key={part.contact_id} className="flex min-h-11 items-center justify-between gap-3 px-3.5 text-sm">
                <span className="min-w-0 truncate">{displayName(part.name, part.is_me)}</span>
                <span className="shrink-0 font-semibold tabular-nums">
                  {formatMoney(part.cents, payment.currency)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {payment.from_contact === null && (
        <fieldset className="flex flex-col gap-2">
          <legend className={cn(LABEL, 'pb-2')}>{t('shared.unattributed.hint')}</legend>
          <div className="flex flex-wrap gap-2">
            {others.map((member) => (
              <Chip
                key={member.id}
                on={false}
                onClick={() => write.mutate(() => ledger.patchPayment(payment.id, { from_contact: member.id }))}
              >
                {t('shared.unattributed.from', { name: member.name })}
              </Chip>
            ))}
          </div>
          <Failure error={write.error} />
        </fieldset>
      )}
      {payment.transaction && <BankLine tx={payment.transaction} />}
    </>
  )
}

/** "Change who paid": the group's other people; picking one gives them all of the payment (who
 * else it covered starts over), as one change in the log. */
function ChangePayer({ group, payment, onDone }: { group: Group; payment: Payment; onDone: () => void }) {
  const write = useLedgerWrite()
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className={cn(LABEL, 'pb-2')}>{t('shared.detail.changePayer')}</legend>
      <p className="text-[13px] text-muted-foreground">{t('shared.detail.changePayerHint')}</p>
      <div className="flex flex-wrap gap-2">
        {payerChoices(payment, group.members).map((member) => (
          <Chip
            key={member.id}
            on={false}
            onClick={() =>
              !write.isPending &&
              write.mutate(() => ledger.patchPayment(payment.id, { from_contact: member.id }), {
                onSuccess: onDone,
              })
            }
          >
            {t('shared.unattributed.from', { name: member.name })}
          </Chip>
        ))}
      </div>
      <Failure error={write.error} />
    </fieldset>
  )
}

interface CoverBodyProps {
  group: Group
  payment: Payment
  /** People to check when it covers nobody else yet (the suggestion's). */
  preselect: readonly number[]
  onDone: () => void
}

/** "Also paid for…" on a payment another person made to the user: check people, see the
 * proposed amounts (payer first, converted), edit them and save, as one change in the log.
 * Unchecking everyone gives it back to the payer alone. */
function CoverBody({ group, payment, preselect, onDone }: CoverBodyProps) {
  const write = useLedgerWrite()
  const payer = group.members.find((m) => m.id === payment.from_contact) ?? null
  // One base everywhere: what it settles (an accepted difference included), as the server checks.
  const start = coverStart(payment, preselect)
  const draft = useCoverDraft({
    groupId: group.id,
    payer,
    amountCents: start.base,
    currency: payment.currency,
    day: payment.day,
    paymentId: payment.id,
    initialCovers: start.covers,
    initialShares: start.shares,
  })
  if (!payer) return null
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[15px] font-semibold break-words">{paymentLine(payment)}</p>
      <AlsoPaidFor
        draft={draft}
        payer={payer}
        people={group.members.filter((m) => !m.is_me && m.id !== payer.id)}
        currency={payment.currency}
        legend={t('shared.detail.alsoPaidFor')}
        hint={t('shared.detail.alsoPaidForHint', { name: payer.name })}
      />
      <Failure error={write.error} />
      <div className="flex flex-wrap gap-2">
        <Action
          primary
          disabled={!draft.ready || write.isPending}
          onClick={() =>
            draft.allocations &&
            write.mutate(() => ledger.setAllocations(payment.id, draft.allocations!), { onSuccess: onDone })
          }
        >
          {t('shared.detail.saveCovers')}
        </Action>
        <Action onClick={onDone}>{t('shared.group.removeCancel')}</Action>
      </div>
    </div>
  )
}

/** The linked bank transaction, with "Open" (Transactions, its month, the row chosen). */
function BankLine({ tx }: { tx: LinkedTx }) {
  const params = new URLSearchParams({ month: tx.day.slice(0, 7), tx: tx.fingerprint })
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className={LABEL}>{t('shared.detail.bank')}</h3>
      <div className="flex items-center gap-3 rounded-xl border border-border px-3.5 py-2">
        <span className="flex min-w-0 flex-1 flex-col text-[13px]">
          <span className="truncate font-semibold text-foreground">{tx.merchant}</span>
          <span className="truncate text-muted-foreground">
            {shortDay(tx.day)} · {tx.account_label} · {linkedAmount(tx)}
          </span>
        </span>
        <Link
          to={`/transactions?${params.toString()}`}
          aria-label={t('shared.detail.openLabel', { merchant: tx.merchant })}
          className={cn(
            'inline-flex min-h-11 shrink-0 items-center rounded-xl border border-border px-3.5 text-sm font-semibold text-ink-2 no-underline hover:bg-muted',
            FOCUS,
          )}
        >
          {t('shared.detail.open')}
        </Link>
      </div>
    </div>
  )
}
