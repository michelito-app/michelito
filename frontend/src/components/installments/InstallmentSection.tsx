import { Check } from 'lucide-react'
import { useState } from 'react'
import { Action, Failure, SECTION, SECTION_TITLE } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { Tx } from '@/lib/api'
import { useChangeInstallmentLink, useInstallments } from '@/lib/installmentQueries'
import { canBeInstallment, linkedLine, planOf, planSummary } from '@/lib/installments'
import { useCardAccounts } from './useCardAccounts'
import { InstallmentSheet } from './InstallmentSheet'

interface InstallmentSectionProps {
  tx: Tx
  /** Inside the phone's sheet: no frame of its own. */
  bare?: boolean
  /** After "It is not part of this plan" (the phone closes its sheet). */
  onUnlinked?: () => void
}

/** In the detail: the row's installment ("Installment 3 of 6 · Phone", the plan's summary and
 * "It is not part of this plan") or, on a card charge, "It is an installment…". */
export function InstallmentSection({ tx, bare, onUnlinked }: InstallmentSectionProps) {
  const cards = useCardAccounts()
  const [note, setNote] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const offer = canBeInstallment(tx, cards)
  if (!tx.installment && !offer && note === null) return null
  return (
    <section
      data-testid="installment-section"
      aria-label={t('installments.detail.title')}
      className={bare ? 'flex flex-col gap-3' : SECTION}
    >
      {!bare && <h3 className={SECTION_TITLE}>{t('installments.detail.title')}</h3>}
      {tx.installment ? (
        <Linked
          tx={tx}
          onUnlinked={() => {
            setNote(t('installments.detail.unlinked'))
            onUnlinked?.()
          }}
        />
      ) : (
        offer && (
          <>
            <p className="text-[13px] text-ink-2">{t('installments.detail.offer')}</p>
            <div>
              <Action onClick={() => setOpen(true)}>{t('installments.detail.create')}</Action>
            </div>
          </>
        )
      )}
      {note && (
        <p role="status" className="inline-flex items-center gap-1.5 text-[13px] font-medium text-primary">
          <Check size={14} aria-hidden="true" />
          {note}
        </p>
      )}
      {open && (
        <InstallmentSheet
          tx={tx}
          onClose={() => setOpen(false)}
          onCreated={() => {
            setOpen(false)
            setNote(t('installments.detail.created'))
          }}
        />
      )}
    </section>
  )
}

function Linked({ tx, onUnlinked }: { tx: Tx; onUnlinked: () => void }) {
  const plans = useInstallments()
  const change = useChangeInstallmentLink()
  const tag = tx.installment!
  const plan = planOf(plans.data, tag.plan_id)
  return (
    <>
      <p data-testid="installment-linked" className="text-sm font-semibold text-foreground">
        {linkedLine(tag)}
      </p>
      {plan && <p className="text-[13px] text-ink-2 tabular-nums">{planSummary(plan)}</p>}
      <div>
        <Action
          label={t('installments.detail.unlinkLabel', { name: tag.name })}
          disabled={change.isPending}
          onClick={() =>
            change.mutate(
              { planId: tag.plan_id, fingerprint: tx.fingerprint, number: null },
              { onSuccess: onUnlinked },
            )
          }
        >
          {t('installments.detail.unlink')}
        </Action>
      </div>
      <Failure error={change.error} />
    </>
  )
}
