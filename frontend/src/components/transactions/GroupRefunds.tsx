import { useId, useState } from 'react'
import type { SharedInfo } from '@/lib/api'
import { formatMoney, parseCents, shortDay, toggled } from '@/lib/links'
import { useChangeGroup, useGroupCreditCandidates } from '@/lib/queries'
import { CandidatePicker } from './CandidatePicker'
import { Action, Failure, FIELD, LinkedRow, LoadFailure } from './linkParts'

interface GroupRefundsProps {
  group: SharedInfo
  /** La transacción abierta: se resalta si es uno de los reembolsos. */
  current: string
}

/** Los reembolsos del grupo (créditos y a mano) con «Quitar». */
export function GroupRefundList({ group, current }: GroupRefundsProps) {
  const change = useChangeGroup()
  if (group.reimbursements.length === 0 && group.manual.length === 0) {
    return <p className="text-[13px] text-muted-foreground">Todavía no hay reembolsos.</p>
  }
  return (
    <>
      <ul aria-label="Reembolsos" className="flex flex-col gap-2">
        {group.reimbursements.map((item) => (
          <LinkedRow
            key={item.fingerprint}
            item={item}
            current={item.fingerprint === current}
            action={
              <Action
                label={`Quitar el reembolso de ${item.merchant}`}
                disabled={change.isPending}
                onClick={() =>
                  change.mutate({ action: 'remove-credit', id: group.id, credit: item.fingerprint })
                }
              >
                Quitar
              </Action>
            }
          />
        ))}
        {group.manual.map((entry) => (
          <li
            key={entry.id}
            className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[13px]"
          >
            <span className="flex min-w-0 flex-col">
              <span className="font-semibold break-words">
                {entry.place || 'Efectivo'}
                {entry.person && ` · ${entry.person}`} ({shortDay(entry.day)})
              </span>
              <span className="text-muted-foreground tabular-nums">
                +{formatMoney(entry.amount_cents, entry.currency)} · anotado a mano
              </span>
            </span>
            <Action
              label={`Quitar el reembolso a mano de ${formatMoney(
                entry.amount_cents,
                entry.currency,
              )}`}
              disabled={change.isPending}
              onClick={() =>
                change.mutate({ action: 'remove-manual', id: group.id, manualId: entry.id })
              }
            >
              Quitar
            </Action>
          </li>
        ))}
      </ul>
      <Failure error={change.error} />
    </>
  )
}

/** «Agregar reembolso»: un crédito importado (selector) o uno en efectivo u otra cuenta. */
export function AddRefund({ group }: { group: SharedInfo }) {
  const [manual, setManual] = useState(false)
  return (
    <div className="flex flex-col gap-2.5">
      <CreditPicker group={group} />
      <Action wide onClick={() => setManual((v) => !v)}>
        Me pagaron en efectivo o en otra cuenta
      </Action>
      {manual && <ManualForm group={group} onDone={() => setManual(false)} />}
    </div>
  )
}

/** Créditos de cualquier cuenta, desde el gasto más viejo hasta 4 meses después del más nuevo:
 * primero los que caben en lo pendiente, el resto tras «Ver más». */
function CreditPicker({ group }: { group: SharedInfo }) {
  const candidates = useGroupCreditCandidates(group.id, true)
  const change = useChangeGroup()
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set())

  /** Uno tras otro: si uno falla, se para ahí, el error queda a la vista (`change.error`) y
   * siguen elegidos los que faltan. */
  async function link() {
    for (const credit of chosen) {
      try {
        await change.mutateAsync({ action: 'add-credit', id: group.id, credit })
      } catch {
        return
      }
      setChosen((current) => toggled(current, credit))
    }
  }

  if (candidates.isError) return <LoadFailure what="los créditos" error={candidates.error} />
  if (candidates.isPending) return <p className="text-[13px] text-muted-foreground">Buscando…</p>
  const credits = candidates.data?.credits ?? []
  if (credits.length === 0) {
    return (
      <p className="text-[13px] text-muted-foreground">
        Ningún crédito sin enlazar desde el primer gasto hasta 4 meses después del último, que
        no pase lo gastado (uno en la otra moneda necesita la tasa de su mes).
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <CandidatePicker
        items={credits}
        chosen={chosen}
        onToggle={(fp) => setChosen((current) => toggled(current, fp))}
        label="Créditos que pueden ser el reembolso"
      />
      <div>
        <Action
          primary
          disabled={chosen.size === 0 || change.isPending}
          onClick={() => void link()}
        >
          Enlazar {chosen.size > 1 ? `${chosen.size} créditos` : 'crédito'}
        </Action>
      </div>
      <Failure error={change.error} />
    </div>
  )
}

/** Reembolso en efectivo o en una cuenta que no se importa: monto (y moneda si el grupo tiene
 * las dos), fecha, de quién y dónde. */
function ManualForm({ group, onDone }: { group: SharedInfo; onDone: () => void }) {
  const ids = useId()
  const candidates = useGroupCreditCandidates(group.id, true)
  const change = useChangeGroup()
  const currencies = [...new Set(group.expenses.map((e) => e.currency))]
  const [currency, setCurrency] = useState(group.expenses[0]?.currency ?? 'DOP')
  const [amount, setAmount] = useState('')
  const [day, setDay] = useState(group.expenses.at(-1)?.day ?? '')
  const [person, setPerson] = useState(group.with_whom)
  const [place, setPlace] = useState('Efectivo')
  const [error, setError] = useState<string | null>(null)

  function save() {
    const cents = parseCents(amount)
    if (cents === null) {
      setError('Pon el monto: mayor que 0')
      return
    }
    change.mutate(
      {
        action: 'add-manual',
        id: group.id,
        manual: {
          amount_cents: cents,
          day,
          person: person.trim() || null,
          place: place.trim() || null,
          currency: currency === 'USD' ? 'USD' : 'DOP',
        },
      },
      { onSuccess: onDone },
    )
  }

  const label = 'flex flex-col gap-1 text-[13px] font-semibold text-ink-2'
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2">
        <label className={label}>
          Monto ({currency === 'USD' ? 'US$' : 'RD$'})
          <input
            inputMode="decimal"
            value={amount}
            onChange={(event) => {
              setAmount(event.target.value)
              setError(null)
            }}
            className={FIELD}
          />
        </label>
        {currencies.length > 1 && (
          <label className={label}>
            Moneda
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className={FIELD}
            >
              <option value="DOP">RD$</option>
              <option value="USD">US$</option>
            </select>
          </label>
        )}
        <label className={label}>
          Fecha
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className={FIELD}
          />
        </label>
        <label className={label}>
          De quién
          <input
            maxLength={80}
            value={person}
            onChange={(e) => setPerson(e.target.value)}
            className={FIELD}
          />
        </label>
        <label className={label}>
          Dónde
          <input
            list={`${ids}-places`}
            maxLength={80}
            value={place}
            onChange={(e) => setPlace(e.target.value)}
            className={FIELD}
          />
          <datalist id={`${ids}-places`}>
            <option value="Efectivo" />
            {(candidates.data?.places ?? []).map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>
        </label>
      </div>
      <p className="text-[13px] text-muted-foreground">
        No cuenta como ingreso. Si luego importas el mismo dinero, enlázalo y quita este.
      </p>
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
          {error}
        </p>
      )}
      <div>
        <Action primary disabled={change.isPending} onClick={save}>
          Anotar reembolso
        </Action>
      </div>
      <Failure error={change.error} />
    </div>
  )
}
