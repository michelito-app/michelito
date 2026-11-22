// A transaction's side of Shared (its detail): the summary when it is in a group, and the
// sheet that records a credit as a payment received in a group.
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { Action, Failure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { Tx } from '@/lib/api'
import { formatMoney, groupPath, linkSummaries } from '@/lib/links'
import { ledger, useGroup, useLedgerWrite, useSharedHome } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { CreditGroupFlow } from './CreditGroupFlow'
import { Chip } from './parts'

const LABEL = 'text-[13px] font-semibold text-ink-2'

/** In a group: "Part of group X · your share RD$ Y" with "Open group", and "Remove from group"
 * (an entry) or "Unlink the payment" (a payment). */
export function SharedTxPanel({ tx }: { tx: Tx }) {
  const write = useLedgerWrite()
  const ledgerRef = tx.ledger
  if (ledgerRef === null) return null
  const summary = linkSummaries(tx).find((s) => s.kind === 'shared')
  return (
    <div className="flex flex-col gap-3" data-testid="tx-shared">
      <p data-testid="link-summary-shared" className="text-sm text-ink-2">
        {summary?.text}
      </p>
      <div className="flex flex-wrap gap-2">
        <Link
          to={groupPath(ledgerRef.group_id)}
          className={cn(
            'inline-flex min-h-11 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground no-underline hover:bg-primary/85',
            FOCUS,
          )}
        >
          {t('shared.tx.openGroup')}
        </Link>
        {ledgerRef.role === 'entry' && ledgerRef.entry_id !== null && (
          <Action
            disabled={write.isPending}
            onClick={() => write.mutate(() => ledger.deleteEntry(ledgerRef.entry_id!))}
          >
            {t('shared.tx.remove')}
          </Action>
        )}
        {ledgerRef.role === 'payment' && ledgerRef.payment_id !== null && (
          <Action
            disabled={write.isPending}
            onClick={() => write.mutate(() => ledger.patchPayment(ledgerRef.payment_id!, { unlink: true }))}
          >
            {t('shared.tx.unlink')}
          </Action>
        )}
      </div>
      <Failure error={write.error} />
    </div>
  )
}

/** "It is a payment…": a credit recorded as what someone paid the user in a group (pick the group and
 * the person; the credit's amount, date and currency are the payment's), or in a new group made
 * here with the expense it pays back ("+ New group", `CreditGroupFlow`). */
export function CreditPaymentSheet({ tx, onClose }: { tx: Tx; onClose: () => void }) {
  const home = useSharedHome()
  const groups = (home.data?.groups ?? []).filter((g) => !g.archived)
  const [creating, setCreating] = useState(false)
  if (creating) {
    return (
      <BottomSheet title={t('shared.credit.newTitle')} onClose={onClose} full>
        <CreditGroupFlow
          tx={tx}
          onBack={groups.length > 0 ? () => setCreating(false) : null}
          onDone={onClose}
        />
      </BottomSheet>
    )
  }
  return <ExistingGroupSheet tx={tx} groups={groups} onClose={onClose} onNew={() => setCreating(true)} />
}

function ExistingGroupSheet({
  tx,
  groups,
  onClose,
  onNew,
}: {
  tx: Tx
  groups: { id: number; name: string }[]
  onClose: () => void
  onNew: () => void
}) {
  const [groupId, setGroupId] = useState<number | null>(null)
  const chosenGroup = groupId ?? groups[0]?.id ?? null
  const group = useGroup(chosenGroup)
  const [personId, setPersonId] = useState<number | null>(null)
  const write = useLedgerWrite()
  const members = group.data?.id === chosenGroup ? (group.data?.members ?? []) : []
  const me = members.find((m) => m.is_me)
  const others = members.filter((m) => !m.is_me)
  const person = others.find((m) => m.id === personId) ?? others[0] ?? null
  const amount = Math.abs(tx.amount_cents)

  return (
    <BottomSheet title={t('shared.credit.title')} onClose={onClose}>
      <p className="text-[13px] text-muted-foreground">{t('shared.credit.hint')}</p>
      <p className="text-sm font-semibold">
        {tx.merchant} · {formatMoney(amount, tx.currency)}
      </p>
      {groups.length === 0 ? (
        <>
          <p className="text-sm text-muted-foreground">{t('shared.credit.noGroups')}</p>
          <Button className="h-11 rounded-xl text-sm font-semibold" onClick={onNew}>
            <Plus size={16} aria-hidden="true" />
            {t('shared.credit.startNew')}
          </Button>
        </>
      ) : (
        <>
          <fieldset className="flex flex-col gap-2">
            <legend className={cn(LABEL, 'pb-2')}>{t('shared.add.group')}</legend>
            <div className="flex flex-wrap gap-2">
              {groups.map((row) => (
                <Chip key={row.id} on={row.id === chosenGroup} onClick={() => setGroupId(row.id)}>
                  {row.name}
                </Chip>
              ))}
              <Chip on={false} onClick={onNew}>
                <Plus size={16} aria-hidden="true" />
                {t('shared.credit.newGroup')}
              </Chip>
            </div>
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className={cn(LABEL, 'pb-2')}>{t('shared.pay.who')}</legend>
            <div className="flex flex-wrap gap-2">
              {others.map((member) => (
                <Chip key={member.id} on={member.id === person?.id} onClick={() => setPersonId(member.id)}>
                  {member.name}
                </Chip>
              ))}
            </div>
          </fieldset>
          <Failure error={write.error} />
          <Button
            className="h-11 rounded-xl text-sm font-semibold"
            disabled={!person || !me || chosenGroup === null || write.isPending}
            onClick={() =>
              write.mutate(
                () =>
                  ledger.addPayment(chosenGroup!, {
                    from_contact: person!.id,
                    to_contact: me!.id,
                    amount_cents: amount,
                    currency: tx.currency,
                    day: tx.day,
                    fingerprint: tx.fingerprint,
                  }),
                { onSuccess: onClose },
              )
            }
          >
            {t('shared.credit.record')}
          </Button>
        </>
      )}
    </BottomSheet>
  )
}
