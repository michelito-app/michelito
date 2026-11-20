import { ArrowLeftRight } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { Action, Failure, FIELD, LoadFailure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { LinkedTx } from '@/lib/api'
import { amountCents, differenceText, paymentDraft, paymentWarning } from '@/lib/ledger'
import { formatMoney } from '@/lib/links'
import { localToday, shortDay } from '@/lib/months'
import type { Group, Payment } from '@/lib/sharedApi'
import { ledger, type PaymentQuery, useLedgerWrite, usePaymentCandidates } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { Chip } from './parts'
import { LIST_CARD, ROW_BUTTON } from './styles'

const LABEL = 'text-[13px] font-semibold text-ink-2'

interface PaymentSheetProps {
  group: Group
  /** Who pays or is paid (a member other than the user); null: chosen in the sheet. */
  personId?: number | null
  /** Link an unlinked payment instead: only the "Is it in your bank yet?" step. */
  linking?: Payment | null
  onClose: () => void
}

type Step = 'details' | 'bank' | 'difference'

/** "Record payment" in two steps: who, direction (from the balance, one tap flips it), amount (the
 * whole balance, editable) and date; then "Is it in your bank yet?" with up to three transactions.
 * Linking one with a different amount shows the difference and "Accept difference"; "Not yet"
 * saves it unlinked. */
export function PaymentSheet({ group, personId = null, linking = null, onClose }: PaymentSheetProps) {
  const ids = useId()
  const others = group.members.filter((m) => !m.is_me)
  const me = group.members.find((m) => m.is_me)
  const firstOwing = others.find((m) => m.balance.some((b) => b.cents !== 0))
  const [who, setWho] = useState<number | null>(personId ?? firstOwing?.id ?? others[0]?.id ?? null)
  const member = others.find((m) => m.id === who) ?? null
  const start = paymentDraft(member?.balance ?? [])
  const [received, setReceived] = useState(start.received)
  const [amount, setAmount] = useState(start.cents ? (start.cents / 100).toFixed(2) : '')
  const [currency, setCurrency] = useState(start.currency)
  const [day, setDay] = useState(localToday())
  const [step, setStep] = useState<Step>(linking ? 'bank' : 'details')
  const [saved, setSaved] = useState<Payment | null>(null)
  const write = useLedgerWrite()

  function choose(id: number) {
    const next = paymentDraft(others.find((m) => m.id === id)?.balance ?? [])
    setWho(id)
    setReceived(next.received)
    setAmount(next.cents ? (next.cents / 100).toFixed(2) : '')
    setCurrency(next.currency)
  }

  const cents = linking ? linking.amount_cents : amountCents(amount)
  const name = member?.name ?? ''
  const query: PaymentQuery | null =
    step === 'bank' && (linking || (member && cents))
      ? linking
        ? {
            contact_id: (linking.to_me ? linking.from_contact : linking.to_contact) ?? me?.id ?? 0,
            received: linking.to_me,
            amount_cents: linking.amount_cents,
            day: linking.day,
            currency: linking.currency,
          }
        : { contact_id: member!.id, received, amount_cents: cents!, day, currency }
      : null
  const candidates = usePaymentCandidates(query)

  function record(fingerprint: string | null) {
    if (linking) {
      if (fingerprint === null) return onClose()
      write.mutate(() => ledger.patchPayment(linking.id, { fingerprint }), {
        onSuccess: (fresh) => finish(fresh, fingerprint),
      })
      return
    }
    if (!member || !me || !cents) return
    write.mutate(
      () =>
        ledger.addPayment(group.id, {
          from_contact: received ? member.id : me.id,
          to_contact: received ? me.id : member.id,
          amount_cents: cents,
          currency,
          day,
          ...(fingerprint ? { fingerprint } : {}),
        }),
      { onSuccess: (fresh) => finish(fresh, fingerprint) },
    )
  }

  function finish(fresh: Group, fingerprint: string | null) {
    const payment = fingerprint
      ? fresh.timeline.find(
          (item): item is Payment =>
            item.kind === 'payment' && item.transaction?.fingerprint === fingerprint,
        )
      : undefined
    if (payment && payment.difference_cents !== null && !payment.accepted) {
      setSaved(payment)
      setStep('difference')
      return
    }
    onClose()
  }

  const title = step === 'details' ? t('shared.pay.title') : linking ? t('shared.pay.linkTitle') : t('shared.pay.bankTitle')
  const whole =
    member && start.cents > 0
      ? t(received ? 'shared.pay.all' : 'shared.pay.allYours', {
          amount: formatMoney(start.cents, start.currency),
        })
      : null

  const warning = member ? paymentWarning(member.balance, received, cents, currency, name) : null

  return (
    <BottomSheet title={title} onClose={onClose}>
      {step === 'details' && (
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (member && cents) setStep('bank')
          }}
        >
          <fieldset className="flex flex-col gap-2">
            <legend className={cn(LABEL, 'pb-2')}>{t('shared.pay.who')}</legend>
            <div className="flex flex-wrap gap-2">
              {others.map((m) => (
                <Chip key={m.id} on={m.id === who} onClick={() => choose(m.id)}>
                  {m.name}
                </Chip>
              ))}
            </div>
          </fieldset>
          {member && (
            <div className="flex items-center justify-between gap-3 rounded-xl bg-muted px-3.5 py-1.5">
              <span data-testid="payment-direction" className="min-w-0 text-[15px] font-semibold">
                {received ? t('shared.pay.paidYou', { name }) : t('shared.pay.youPaid', { name })}
              </span>
              <button
                type="button"
                aria-label={t('shared.pay.flip')}
                onClick={() => setReceived((value) => !value)}
                className={cn(
                  'flex size-11 shrink-0 items-center justify-center rounded-xl text-primary hover:bg-card',
                  FOCUS,
                )}
              >
                <ArrowLeftRight size={18} aria-hidden="true" />
              </button>
            </div>
          )}
          <div className="flex flex-col gap-2">
            <label htmlFor={`${ids}-amount`} className={LABEL}>
              {t('shared.pay.amount')}
            </label>
            <div className="flex items-center gap-2">
              <input
                id={`${ids}-amount`}
                inputMode="decimal"
                autoComplete="off"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                className={cn(FIELD, 'h-14 flex-1 text-[26px] font-bold tabular-nums')}
              />
              <div role="group" aria-label={t('shared.add.currency')} className="flex shrink-0 gap-1">
                {(['DOP', 'USD'] as const).map((code) => (
                  <Chip key={code} on={currency === code} onClick={() => setCurrency(code)}>
                    {code === 'DOP' ? 'RD$' : 'US$'}
                  </Chip>
                ))}
              </div>
            </div>
            {whole && <span className="text-[13px] text-muted-foreground">{whole}</span>}
            {warning && (
              <span role="status" data-testid="payment-warning" className="text-[13px] font-medium text-destructive">
                {warning}
              </span>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <label htmlFor={`${ids}-day`} className={LABEL}>
              {t('shared.add.day')}
            </label>
            <input
              id={`${ids}-day`}
              type="date"
              value={day}
              required
              onChange={(event) => setDay(event.target.value)}
              className={FIELD}
            />
          </div>
          <Button type="submit" className="h-11 rounded-xl text-sm font-semibold" disabled={!member || !cents}>
            {t('shared.next')}
          </Button>
        </form>
      )}

      {step === 'bank' && (
        <div className="flex flex-col gap-3">
          {!linking && <p className="text-sm font-semibold">{t('shared.pay.bankTitle')}</p>}
          <p className="text-[13px] text-muted-foreground">{t('shared.pay.bankHint')}</p>
          {candidates.isError ? (
            <LoadFailure what={t('shared.load')} error={candidates.error} />
          ) : candidates.isPending ? (
            <p className="text-[13px] text-muted-foreground">{t('shared.pay.searching')}</p>
          ) : candidates.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('shared.pay.noCandidates')}</p>
          ) : (
            <ul className={LIST_CARD} aria-label={t('shared.pay.bankTitle')}>
              {candidates.data.map((tx) => (
                <BankRow key={tx.fingerprint} tx={tx} busy={write.isPending} onPick={() => record(tx.fingerprint)} />
              ))}
            </ul>
          )}
          <Failure error={write.error} />
          <Action wide disabled={write.isPending} onClick={() => record(null)}>
            {t('shared.pay.notYet')}
          </Action>
        </div>
      )}

      {step === 'difference' && saved && (
        <div className="flex flex-col gap-3">
          <p className="text-sm font-semibold text-down">{t('shared.pay.saved')}</p>
          <p data-testid="payment-difference" className="text-sm text-ink-2">
            {differenceText(saved)}
          </p>
          <Failure error={write.error} />
          <Button
            className="h-11 rounded-xl text-sm font-semibold"
            disabled={write.isPending}
            onClick={() =>
              write.mutate(() => ledger.patchPayment(saved.id, { accepted: true }), { onSuccess: onClose })
            }
          >
            {t('shared.detail.acceptDifference')}
          </Button>
          <Action wide onClick={onClose}>
            {t('shared.done')}
          </Action>
        </div>
      )}
    </BottomSheet>
  )
}

function BankRow({ tx, busy, onPick }: { tx: LinkedTx; busy: boolean; onPick: () => void }) {
  const amount = formatMoney(Math.abs(tx.amount_cents), tx.currency)
  return (
    <li>
      <button
        type="button"
        disabled={busy}
        aria-label={t('shared.pay.linkLabel', { merchant: tx.merchant, amount, day: shortDay(tx.day) })}
        onClick={onPick}
        className={ROW_BUTTON}
      >
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-semibold">{tx.merchant}</span>
          <span className="truncate text-[13px] text-muted-foreground">
            {shortDay(tx.day)} · {tx.account_label}
          </span>
        </span>
        <span className="shrink-0 text-sm font-semibold tabular-nums">{amount}</span>
      </button>
    </li>
  )
}
