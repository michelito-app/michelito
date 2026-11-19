import { useState } from 'react'
import { Link } from 'react-router'
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

/** En el detalle: «Lo guardé en la caja fuerte» (un retiro), «Vino de la caja fuerte» (un
 * crédito bancario) o, si ya lo es, deshacerlo; y en lo anotado a mano en la caja, editarlo o
 * borrarlo. */
interface CashBoxSectionProps {
  tx: Tx
  onSaved: (tx: Tx) => void
  /** Cierra el detalle (quita `?tx=`): tras borrar lo anotado a mano ya no hay fila. */
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
  // Desmarcar algo que ya no está en el flujo responde sin cuerpo (204).
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
    <section aria-label="Caja fuerte" className={SECTION}>
      <h3 className={SECTION_TITLE}>Caja fuerte</h3>
      <p data-testid="cash-box-text" className="text-[13px] text-ink-2">
        {cashBoxText(tx)}
      </p>
      {choosing && (
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
            Salió de la caja en
            <select
              aria-label="Moneda de la caja"
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
              {`Cuánto salió en ${symbol(currency)} (vacío: a la tasa del mes)`}
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
            Lo guardé en la caja fuerte
          </Action>
        )}
        {tx.can_deposit && !choosing && (
          <Action
            disabled={change.isPending}
            onClick={() =>
              change.mutate({ action: 'deposit', fingerprint: tx.fingerprint, body: {} }, done)
            }
          >
            Vino de la caja fuerte
          </Action>
        )}
        {tx.can_deposit && !choosing && (
          <Action onClick={() => setChoosing(true)}>
            {`Vino de la caja en ${symbol(other)}…`}
          </Action>
        )}
        {choosing && (
          <>
            <Action primary disabled={change.isPending} onClick={deposit}>
              Vino de la caja fuerte
            </Action>
            <Action onClick={() => setChoosing(false)}>Cancelar</Action>
          </>
        )}
        {tx.cash_box_role === 'stored' && (
          <Action
            disabled={change.isPending}
            onClick={() => change.mutate({ action: 'unstore', fingerprint: tx.fingerprint }, done)}
          >
            No lo guardé (es gasto)
          </Action>
        )}
        {tx.cash_box_role === 'deposit' && (
          <Action
            disabled={change.isPending}
            onClick={() =>
              change.mutate({ action: 'undeposit', fingerprint: tx.fingerprint }, done)
            }
          >
            No vino de la caja
          </Action>
        )}
      </div>
      {tx.cash_box_role !== '' && <NegativeNote />}
      <Failure error={change.error} />
    </section>
  )
}

/** Tras marcar algo, si la caja quedó en negativo: el aviso y el enlace a Cuentas. */
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
        Ver la caja fuerte
      </Link>
    </div>
  )
}

/** Lo anotado a mano en la caja: monto, moneda y fecha se cambian aquí (categoría, nota y
 * «gasto único», arriba, como en cualquier otro); «Borrar» lo quita. */
function ManualSection({ tx, onClose }: { tx: Tx; onClose: () => void }) {
  const box = useCashBox()
  const remove = useChangeCashBox()
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const line = box.data?.lines.find((l) => l.fingerprint === tx.fingerprint) ?? null
  const kind = tx.amount_cents < 0 ? 'income' : 'expense'
  return (
    <section aria-label="Caja fuerte" className={SECTION}>
      <h3 className={SECTION_TITLE}>Caja fuerte</h3>
      <p className="text-[13px] text-ink-2">
        {kind === 'income'
          ? 'Entrada anotada a mano en la caja fuerte: cuenta como ingreso en su mes.'
          : 'Salida anotada a mano de la caja fuerte: cuenta como gasto en su categoría y mes.'}
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
            Cambiar monto o fecha…
          </Action>
        )}
        <Action onClick={() => setConfirming(true)}>Borrar</Action>
        <Link to={CASH_BOX_HREF} className={cn(BOX_LINK, 'px-2 text-[13px]')}>
          Ver la caja fuerte
        </Link>
      </div>
      {confirming && tx.cash_entry_id !== null && (
        <ConfirmBox
          label="Borrar el movimiento"
          confirmLabel="Sí, borrar"
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
          {deleteWarning(tx.shared?.title ?? null)}
        </ConfirmBox>
      )}
      <Failure error={remove.error} />
    </section>
  )
}
