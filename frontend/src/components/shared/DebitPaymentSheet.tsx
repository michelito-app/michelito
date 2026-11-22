// "It is a payment…" on a bank debit: what the user paid someone in a group (a transfer to a
// friend who had paid for everyone, say). Pick the group (or make one) and the person; the
// debit's amount, date and currency are the payment's, and it stays linked to the transaction.
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { Failure, LoadFailure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { Tx } from '@/lib/api'
import { afterPaying } from '@/lib/creditGroup'
import { formatMoney } from '@/lib/links'
import type { Member } from '@/lib/sharedApi'
import { ledger, useGroup, useLedgerWrite, useSharedHome } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { NewGroupSheet } from './NewGroupSheet'
import { Chip } from './parts'

const LABEL = 'text-[13px] font-semibold text-ink-2'

export function DebitPaymentSheet({ tx, onClose }: { tx: Tx; onClose: () => void }) {
  const home = useSharedHome()
  const groups = (home.data?.groups ?? []).filter((g) => !g.archived)
  const [groupId, setGroupId] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const chosenGroup = groupId ?? groups[0]?.id ?? null
  const title = t('shared.debit.title')

  // Until the groups arrive, saying "no groups yet" would be wrong.
  if (home.isPending) {
    return (
      <BottomSheet title={title} onClose={onClose}>
        <p className="text-[13px] text-muted-foreground">{t('shared.loading')}</p>
      </BottomSheet>
    )
  }
  if (home.isError) {
    return (
      <BottomSheet title={title} onClose={onClose}>
        <LoadFailure what={t('shared.load')} error={home.error} />
      </BottomSheet>
    )
  }

  return (
    <BottomSheet title={title} onClose={onClose}>
      <p className="text-[13px] text-muted-foreground">{t('shared.debit.hint')}</p>
      <p className="text-sm font-semibold">
        {tx.merchant} · {formatMoney(Math.abs(tx.amount_cents), tx.currency)}
      </p>
      {groups.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('shared.credit.noGroups')}</p>
      )}
      <fieldset className="flex flex-col gap-2">
        <legend className={cn(LABEL, 'pb-2')}>{t('shared.add.group')}</legend>
        <div className="flex flex-wrap gap-2">
          {groups.map((row) => (
            <Chip key={row.id} on={row.id === chosenGroup} onClick={() => setGroupId(row.id)}>
              {row.name}
            </Chip>
          ))}
          <Chip on={false} onClick={() => setCreating(true)}>
            <span className="inline-flex items-center gap-1.5">
              <Plus size={16} aria-hidden="true" />
              {t('shared.credit.newGroup')}
            </span>
          </Chip>
        </div>
      </fieldset>
      {chosenGroup !== null && <PersonAndRecord key={chosenGroup} tx={tx} groupId={chosenGroup} onDone={onClose} />}
      {creating && (
        <NewGroupSheet
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setGroupId(created.id)
            setCreating(false)
          }}
        />
      )}
    </BottomSheet>
  )
}

/** The person paid in the chosen group, what their balance becomes, and "Record the payment". */
function PersonAndRecord({ tx, groupId, onDone }: { tx: Tx; groupId: number; onDone: () => void }) {
  const group = useGroup(groupId)
  const write = useLedgerWrite()
  const [personId, setPersonId] = useState<number | null>(null)
  if (group.isPending) return <p className="text-[13px] text-muted-foreground">{t('shared.loading')}</p>
  if (group.isError) return <LoadFailure what={t('shared.load')} error={group.error} />
  const members = group.data.members
  const me = members.find((m) => m.is_me)
  const others = members.filter((m) => !m.is_me)
  const person = others.find((m) => m.id === personId) ?? others[0] ?? null
  const amount = Math.abs(tx.amount_cents)

  if (!person || !me) {
    return <p className="text-sm text-muted-foreground">{t('shared.debit.noPeople')}</p>
  }
  return (
    <>
      <fieldset className="flex flex-col gap-2">
        <legend className={cn(LABEL, 'pb-2')}>{t('shared.debit.to')}</legend>
        <div className="flex flex-wrap gap-2">
          {others.map((member) => (
            <Chip key={member.id} on={member.id === person.id} onClick={() => setPersonId(member.id)}>
              {member.name}
            </Chip>
          ))}
        </div>
      </fieldset>
      <p data-testid="debit-after" className="text-[13px] text-ink-2">
        {afterText(person, amount, tx.currency)}
      </p>
      <Failure error={write.error} />
      <Button
        className="h-11 rounded-xl text-sm font-semibold"
        disabled={write.isPending}
        onClick={() =>
          write.mutate(
            () =>
              ledger.addPayment(groupId, {
                from_contact: me.id,
                to_contact: person.id,
                amount_cents: amount,
                currency: tx.currency,
                day: tx.day,
                fingerprint: tx.fingerprint,
              }),
            { onSuccess: onDone },
          )
        }
      >
        {write.isPending ? t('shared.saving') : t('shared.credit.record')}
      </Button>
    </>
  )
}

function afterText(person: Member, paidCents: number, currency: string): string {
  const balance = person.balance.find((b) => b.currency === currency)?.cents ?? 0
  const after = afterPaying(balance, paidCents)
  const name = person.name
  const amount = formatMoney(after.cents, currency)
  if (after.kind === 'settled') return t('shared.debit.afterSettled', { name })
  return after.kind === 'owes'
    ? t('shared.debit.afterOwes', { name, amount })
    : t('shared.debit.afterOwe', { name, amount })
}
