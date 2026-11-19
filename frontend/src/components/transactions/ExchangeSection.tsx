import { useId, useState } from 'react'
import type { ExchangeInfo, Tx } from '@/lib/api'
import { exchangeLine, linkedLabel, rateLabel, toggled } from '@/lib/links'
import { useChangeExchange, useExchangeCandidates } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { CandidatePicker } from './CandidatePicker'
import { Action, Failure, FIELD, LinkedRow, SECTION, SECTION_TITLE } from './linkParts'

/** "Cambio de divisas": el cambio con sus patas, la tasa, lo pendiente; o vincular uno. */
export function ExchangeSection({ tx }: { tx: Tx }) {
  const ids = useId()
  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        Cambio de divisas
      </h2>
      {tx.exchange ? (
        <Linked tx={tx} exchange={tx.exchange} />
      ) : tx.link === 'exchange' && tx.link_id !== null ? (
        <Dormant tx={tx} id={tx.link_id} />
      ) : (
        <Unlinked tx={tx} />
      )}
    </section>
  )
}

/** Un cambio al que le falta una pata (o ya no cuadra): se puede quitar esta pata o deshacerlo. */
function Dormant({ tx, id }: { tx: Tx; id: number }) {
  const change = useChangeExchange()
  return (
    <>
      <p className="text-[13px] text-ink-2">
        Este cambio está incompleto: le falta una pata o ya no cuadra. Esta transacción sigue
        como «Cambio de divisas» hasta que la quites.
      </p>
      <div className="flex flex-wrap gap-2">
        <Action
          disabled={change.isPending}
          onClick={() => change.mutate({ action: 'remove', id, fingerprint: tx.fingerprint })}
        >
          Quitar del cambio
        </Action>
        <Action disabled={change.isPending} onClick={() => change.mutate({ action: 'delete', id })}>
          Deshacer el cambio
        </Action>
      </div>
      <Failure error={change.error} />
    </>
  )
}

function Unlinked({ tx }: { tx: Tx }) {
  const change = useChangeExchange()
  const suggested = tx.suggested_exchange_with
  return (
    <>
      {suggested && (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-primary/40 px-3 py-2.5">
          <p className="text-[13px] text-ink-2">
            ¿Es un cambio de divisas con <span className="font-semibold">{linkedLabel(suggested)}</span>?
          </p>
          <div className="flex flex-wrap gap-2">
            <Action
              primary
              disabled={change.isPending}
              onClick={() =>
                change.mutate({ action: 'create', fingerprints: [tx.fingerprint, suggested.fingerprint] })
              }
            >
              Sí, vincular
            </Action>
          </div>
        </div>
      )}
      <h3 className="text-[13px] font-semibold text-ink-2">Es un cambio de divisas con…</h3>
      <LegPicker
        tx={tx}
        withRate
        saving={change.isPending}
        onPick={(fingerprints, rate) =>
          change.mutate({
            action: 'create',
            fingerprints: [tx.fingerprint, ...fingerprints],
            agreedRate: rate,
          })
        }
      />
      <Failure error={change.error} />
    </>
  )
}

interface LegPickerProps {
  tx: Tx
  withRate?: boolean
  saving: boolean
  onPick: (fingerprints: string[], rate: string | null) => void
}

/** Patas posibles, como las ordena el servidor: al empezar, la otra moneda en dirección
 * contraria (±30 días), las más cerca de la tasa del mes primero; en un cambio con pendiente,
 * solo lo que cabe en el lado que falta. Al crear, la tasa acordada opcional. */
function LegPicker({ tx, withRate = false, saving, onPick }: LegPickerProps) {
  const candidates = useExchangeCandidates(tx.fingerprint, true)
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set())
  const [rate, setRate] = useState('')
  if (candidates.isPending) return <p className="text-[13px] text-muted-foreground">Buscando…</p>
  const items = candidates.data ?? []
  if (items.length === 0) {
    return (
      <p className="text-[13px] text-muted-foreground">
        Nada encaja: otra moneda, dirección contraria, en ±30 días, sin otro vínculo y (con
        pendiente) que quepa en lo que falta.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <CandidatePicker
        items={items}
        chosen={chosen}
        onToggle={(fp) => setChosen((current) => toggled(current, fp))}
        label="Patas posibles"
      />
      {withRate && (
        <label className="flex flex-col gap-1 text-[13px] font-semibold text-ink-2">
          Tasa acordada (RD$ por US$, opcional)
          <input
            inputMode="decimal"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            className={`${FIELD} max-w-40`}
          />
        </label>
      )}
      <div>
        <Action
          primary
          disabled={chosen.size === 0 || saving}
          onClick={() => {
            onPick([...chosen], rate.trim() || null)
            setChosen(new Set())
          }}
        >
          Vincular
        </Action>
      </div>
    </div>
  )
}

function Linked({ tx, exchange }: { tx: Tx; exchange: ExchangeInfo }) {
  const change = useChangeExchange()
  const [rate, setRate] = useState(exchange.agreed_rate ? rateLabel(exchange.agreed_rate) : '')
  const id = exchange.id
  return (
    <>
      <p className="text-[13px] font-medium text-foreground" data-testid="exchange-line">
        {exchangeLine(exchange)}
      </p>
      {exchange.needs_agreed_rate && (
        <p className="rounded-lg bg-[#EEF3FB] px-3 py-2 text-[13px] text-[#2F4F7F]">
          Pon la tasa acordada para ver lo pendiente.
        </p>
      )}
      <ul aria-label="Patas del cambio" className="flex flex-col gap-2">
        {exchange.legs.map((leg) => (
          <LinkedRow
            key={leg.fingerprint}
            item={leg}
            action={
              <Action
                label={`Quitar la pata de ${leg.merchant}`}
                disabled={change.isPending}
                onClick={() => change.mutate({ action: 'remove', id, fingerprint: leg.fingerprint })}
              >
                Quitar
              </Action>
            }
          />
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[13px] font-semibold text-ink-2">
          Tasa acordada
          <input
            inputMode="decimal"
            placeholder={rateLabel(exchange.implied_rate)}
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            className={cn(FIELD, 'w-32')}
          />
        </label>
        <Action
          disabled={change.isPending}
          onClick={() => change.mutate({ action: 'update', id, agreedRate: rate.trim() || null })}
        >
          {rate.trim() ? 'Guardar tasa' : 'Usar la implícita'}
        </Action>
      </div>
      <p className="text-[13px] text-muted-foreground">
        Sin tasa acordada se usa la del primer par: {rateLabel(exchange.implied_rate)}.
      </p>
      <div className="flex flex-wrap gap-2">
        <Action
          disabled={change.isPending}
          onClick={() => change.mutate({ action: 'update', id, closed: !exchange.closed })}
        >
          {exchange.closed ? 'Reabrir el cambio' : 'Cambio completo'}
        </Action>
      </div>
      <div className="flex flex-col gap-2 border-t border-border pt-3">
        <h3 className="text-[13px] font-semibold text-ink-2">Agregar patas</h3>
        <LegPicker
          tx={tx}
          saving={change.isPending}
          onPick={(fingerprints) => change.mutate({ action: 'add', id, fingerprints })}
        />
      </div>
      <Failure error={change.error} />
    </>
  )
}
