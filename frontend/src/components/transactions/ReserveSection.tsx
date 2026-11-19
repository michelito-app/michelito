import { useState } from 'react'
import { Link } from 'react-router'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import type { Tx } from '@/lib/api'
import { BUDGET_PATH } from '@/lib/budget'
import { useChangeReserve, useLinkToReserve, useTxReserve } from '@/lib/budgetQueries'
import { monthPhrase } from '@/lib/months'
import { cn } from '@/lib/utils'
import { Action, FIELD, SECTION, SECTION_TITLE } from './linkParts'

const LINK = 'inline-flex min-h-11 items-center font-semibold text-primary'

/** In the detail of an expense: "covered by reserve X" (with a button to remove it) or a button
 * that links it to a reserve (the suggested one first). */
export function ReserveSection({ tx }: { tx: Tx }) {
  const debit = tx.kind === 'expense' && tx.amount_cents > 0
  const state = useTxReserve(tx.fingerprint, debit)
  const [open, setOpen] = useState(false)
  const unlink = useChangeReserve()
  if (!debit || !state.data) return null
  const data = state.data
  if (data.reserve) {
    const reserve = data.reserve
    return (
      <section aria-label={t('transactions.reserve.title')} className={SECTION}>
        <h3 className={SECTION_TITLE}>{t('transactions.reserve.title')}</h3>
        <p data-testid="reserve-state" className="text-[13px] text-ink-2">
          {tn('transactions.reserve.covered', {
            name: <span className="font-semibold">{reserve.name}</span>,
          })}
        </p>
        <p className="text-[13px] text-muted-foreground">{t('transactions.reserve.removeFirst')}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Action
            onClick={() =>
              unlink.mutate({ action: 'unlink', id: reserve.id, fingerprint: tx.fingerprint })
            }
            disabled={unlink.isPending}
          >
            {t('transactions.reserve.remove')}
          </Action>
          <Link to={BUDGET_PATH} className={LINK}>
            {t('transactions.reserve.seeBudget')}
          </Link>
        </div>
        {unlink.isError && (
          <p role="alert" className="text-[13px] text-up-ink">
            {t('transactions.reserve.removeError', { message: unlink.error.message })}
          </p>
        )}
      </section>
    )
  }
  if (!data.can_link) {
    if (!data.reason || data.options.length === 0) return null
    return (
      <section aria-label={t('transactions.reserve.title')} className={SECTION}>
        <h3 className={SECTION_TITLE}>{t('transactions.reserve.title')}</h3>
        <p data-testid="reserve-reason" className="text-[13px] text-muted-foreground">
          {t('transactions.reserve.cannotLink', { reason: data.reason })}
        </p>
      </section>
    )
  }
  return (
    <section aria-label={t('transactions.reserve.title')} className={SECTION}>
      <h3 className={SECTION_TITLE}>{t('transactions.reserve.title')}</h3>
      {!open ? (
        <div>
          <Action onClick={() => setOpen(true)}>{t('transactions.reserveBatch.placeholder')}</Action>
        </div>
      ) : (
        <LinkForm tx={tx} options={data.options} onCancel={() => setOpen(false)} />
      )}
    </section>
  )
}

interface LinkFormProps {
  tx: Tx
  options: { id: number; name: string; category: string; next_due: string | null }[]
  onCancel: () => void
}

function LinkForm({ tx, options, onCancel }: LinkFormProps) {
  const [chosen, setChosen] = useState(String(options[0]?.id ?? ''))
  const link = useLinkToReserve()
  const submit = () => {
    if (chosen) link.mutate({ id: Number(chosen), fingerprints: [tx.fingerprint] })
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-ink-2">
        {t('transactions.reserve.intro')}
      </p>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
        {t('transactions.reserve.title')}
        <select
          aria-label={t('transactions.reserve.title')}
          value={chosen}
          onChange={(event) => setChosen(event.target.value)}
          className={cn(FIELD, 'cursor-pointer font-medium')}
        >
          {options.map((option) => (
            <option key={option.id} value={String(option.id)}>
              {option.name}
              {option.next_due
                ? t('transactions.reserve.due', { month: monthPhrase(option.next_due) })
                : ''}
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-wrap gap-2">
        <Action primary onClick={submit} disabled={link.isPending || !chosen}>
          {t('transactions.reserve.link')}
        </Action>
        <Action onClick={onCancel}>{t('transactions.cancel')}</Action>
      </div>
      {link.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('transactions.reserveBatch.error', { message: link.error.message })}
        </p>
      )}
    </div>
  )
}
