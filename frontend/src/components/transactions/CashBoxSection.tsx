import { useState } from 'react'
import { Link } from 'react-router'
import { t } from '@/i18n'
import { CashEntryForm } from '@/components/cashBox/CashEntryForm'
import type { CashCurrency, Tx } from '@/lib/api'
import {
  CASH_BOX_HREF,
  cashBoxText,
  deleteWarning,
  depositBody,
  isNegative,
  localToday,
  showCashBox,
} from '@/lib/cashBox'
import { useCashBox, useChangeCashBox } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { Action, ConfirmBox, FIELD, Failure, SECTION, SECTION_TITLE } from './linkParts'

const BOX_LINK = 'inline-flex min-h-11 items-center font-semibold text-primary'

function symbol(currency: CashCurrency): string {
  return currency === 'USD' ? 'US$' : 'RD$'
}

/** In the detail: mark a withdrawal as stored in the cash box, or a bank credit as coming from
 * it, or undo that; and for an entry written by hand in the box, edit or delete it. */
interface CashBoxSectionProps {
  tx: Tx
  onSaved: (tx: Tx) => void
  /** Closes the detail (drops `?tx=`): after deleting a manual entry there is no row left. */
  onClose: () => void
}

export function CashBoxSection({ tx, onSaved, onClose }: CashBoxSectionProps) {
  if (tx.cash_entry_id !== null) return <ManualSection tx={tx} onClose={onClose} />
  if (!showCashBox(tx)) return null
  return <LinkSection tx={tx} onSaved={onSaved} />
}

function LinkSection({ tx, onSaved }: { tx: Tx; onSaved: (tx: Tx) => void }) {
  const change = useChangeCashBox()
  const [choosing, setChoosing] = useState(false)
  const [currency, setCurrency] = useState<CashCurrency>(tx.currency as CashCurrency)
  const [amount, setAmount] = useState('')
  const [error, setError] = useState<string | null>(null)
  // Unmarking something that is no longer in the flow answers without a body (204).
  const done = {
    onSuccess: (saved: unknown) => {
      if (saved) onSaved(saved as Tx)
    },
  }

  function deposit() {
    const body = depositBody(tx, currency, amount)
    if (typeof body === 'string') {
      setError(body)
      return
    }
    change.mutate({ action: 'deposit', fingerprint: tx.fingerprint, body }, done)
  }

  const other = currency === 'USD' ? 'DOP' : 'USD'
  return (
    <section aria-label={t('links.cashBox.title')} className={SECTION}>
      <h3 className={SECTION_TITLE}>{t('links.cashBox.title')}</h3>
      <p data-testid="cash-box-text" className="text-[13px] text-ink-2">
        {cashBoxText(tx)}
      </p>
      {choosing && (
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
            {t('links.cashBox.outIn')}
            <select
              aria-label={t('links.cashBox.currency')}
              className={FIELD}
              value={currency}
              onChange={(event) => {
                setCurrency(event.target.value as CashCurrency)
                setError(null)
              }}
            >
              <option value="DOP">RD$</option>
              <option value="USD">US$</option>
            </select>
          </label>
          {currency !== tx.currency && (
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
              {t('links.cashBox.howMuch', { currency: symbol(currency) })}
              <input
                className={FIELD}
                inputMode="decimal"
                value={amount}
                onChange={(event) => {
                  setAmount(event.target.value)
                  setError(null)
                }}
              />
            </label>
          )}
          {error && (
            <p role="alert" className="text-[13px] text-up-ink">
              {error}
            </p>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {tx.can_store && (
          <Action
            primary
            disabled={change.isPending}
            onClick={() => change.mutate({ action: 'store', fingerprint: tx.fingerprint }, done)}
          >
            {t('links.cashBox.store')}
          </Action>
        )}
        {tx.can_deposit && !choosing && (
          <Action
            disabled={change.isPending}
            onClick={() =>
              change.mutate({ action: 'deposit', fingerprint: tx.fingerprint, body: {} }, done)
            }
          >
            {t('links.cashBox.deposit')}
          </Action>
        )}
        {tx.can_deposit && !choosing && (
          <Action onClick={() => setChoosing(true)}>
            {t('links.cashBox.depositIn', { currency: symbol(other) })}
          </Action>
        )}
        {choosing && (
          <>
            <Action primary disabled={change.isPending} onClick={deposit}>
              {t('links.cashBox.deposit')}
            </Action>
            <Action onClick={() => setChoosing(false)}>{t('links.cancel')}</Action>
          </>
        )}
        {tx.cash_box_role === 'stored' && (
          <Action
            disabled={change.isPending}
            onClick={() => change.mutate({ action: 'unstore', fingerprint: tx.fingerprint }, done)}
          >
            {t('links.cashBox.unstore')}
          </Action>
        )}
        {tx.cash_box_role === 'deposit' && (
          <Action
            disabled={change.isPending}
            onClick={() =>
              change.mutate({ action: 'undeposit', fingerprint: tx.fingerprint }, done)
            }
          >
            {t('links.cashBox.undeposit')}
          </Action>
        )}
      </div>
      {tx.cash_box_role !== '' && <NegativeNote />}
      <Failure error={change.error} />
    </section>
  )
}

/** After marking something, when the box went negative: the warning and the link to Accounts. */
function NegativeNote() {
  const box = useCashBox()
  const negative = box.data?.negative ?? []
  return (
    <div className="flex flex-col gap-1 text-[13px]">
      {negative.map((item) => (
        <p key={item.currency} data-testid="cash-box-negative" className="text-up-ink">
          {isNegative(item)}
        </p>
      ))}
      <Link to={CASH_BOX_HREF} className={BOX_LINK}>
        {t('links.cashBox.see')}
      </Link>
    </div>
  )
}

/** An entry written by hand in the box: amount, currency and date change here (category, note
 * and one-off above, as for any other row); delete removes it. */
function ManualSection({ tx, onClose }: { tx: Tx; onClose: () => void }) {
  const box = useCashBox()
  const remove = useChangeCashBox()
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const line = box.data?.lines.find((l) => l.fingerprint === tx.fingerprint) ?? null
  const kind = tx.amount_cents < 0 ? 'income' : 'expense'
  return (
    <section aria-label={t('links.cashBox.title')} className={SECTION}>
      <h3 className={SECTION_TITLE}>{t('links.cashBox.title')}</h3>
      <p className="text-[13px] text-ink-2">
        {kind === 'income' ? t('links.cashBox.manualIncome') : t('links.cashBox.manualExpense')}
      </p>
      {editing && line && box.data && (
        <CashEntryForm
          kind={kind}
          box={box.data}
          today={localToday()}
          editing={line}
          onDone={() => setEditing(false)}
        />
      )}
      <div className="flex flex-wrap gap-2">
        {!editing && (
          <Action disabled={line === null} onClick={() => setEditing(true)}>
            {t('links.cashBox.edit')}
          </Action>
        )}
        <Action onClick={() => setConfirming(true)}>{t('links.cashBox.delete')}</Action>
        <Link to={CASH_BOX_HREF} className={cn(BOX_LINK, 'px-2 text-[13px]')}>
          {t('links.cashBox.see')}
        </Link>
      </div>
      {confirming && tx.cash_entry_id !== null && (
        <ConfirmBox
          label={t('links.cashBox.deleteLabel')}
          confirmLabel={t('links.cashBox.deleteConfirm')}
          busy={remove.isPending}
          onConfirm={() =>
            remove.mutate(
              { action: 'delete', id: tx.cash_entry_id! },
              {
                onSuccess: () => {
                  setConfirming(false)
                  onClose()
                },
              },
            )
          }
          onCancel={() => setConfirming(false)}
        >
          {deleteWarning(tx.ledger?.group_name ?? null)}
        </ConfirmBox>
      )}
      <Failure error={remove.error} />
    </section>
  )
}
