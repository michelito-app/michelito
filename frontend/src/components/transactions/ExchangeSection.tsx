import { useId, useState } from 'react'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import type { ExchangeInfo, Tx } from '@/lib/api'
import { exchangeLine, linkedLabel, rateLabel, toggled } from '@/lib/links'
import { useChangeExchange, useExchangeCandidates } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { CandidatePicker } from './CandidatePicker'
import { Action, Failure, FIELD, LinkedRow, SECTION, SECTION_TITLE } from './linkParts'

/** The Currency exchange section: the exchange with its legs, the rate and what is pending; or
 * linking one. */
export function ExchangeSection({ tx }: { tx: Tx }) {
  const ids = useId()
  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        {t('links.summary.exchangeTitle')}
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

/** An exchange missing a leg (or no longer balanced): this leg can be removed or the exchange
 * undone. */
function Dormant({ tx, id }: { tx: Tx; id: number }) {
  const change = useChangeExchange()
  return (
    <>
      <p className="text-[13px] text-ink-2">
        {t('links.exchange.dormant')}
      </p>
      <div className="flex flex-wrap gap-2">
        <Action
          disabled={change.isPending}
          onClick={() => change.mutate({ action: 'remove', id, fingerprint: tx.fingerprint })}
        >
          {t('links.exchange.removeLeg')}
        </Action>
        <Action disabled={change.isPending} onClick={() => change.mutate({ action: 'delete', id })}>
          {t('links.exchange.undo')}
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
            {tn('links.shortcut.exchange', {
              what: <span className="font-semibold">{linkedLabel(suggested)}</span>,
            })}
          </p>
          <div className="flex flex-wrap gap-2">
            <Action
              primary
              disabled={change.isPending}
              onClick={() =>
                change.mutate({ action: 'create', fingerprints: [tx.fingerprint, suggested.fingerprint] })
              }
            >
              {t('links.shortcut.pair')}
            </Action>
          </div>
        </div>
      )}
      <h3 className="text-[13px] font-semibold text-ink-2">{t('links.exchange.pick')}</h3>
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

/** Possible legs, in the server's order: when starting, the other currency in the opposite
 * direction (±30 days), closest to the month's rate first; in an exchange with something
 * pending, only what fits the missing side. When creating, an optional agreed rate. */
function LegPicker({ tx, withRate = false, saving, onPick }: LegPickerProps) {
  const candidates = useExchangeCandidates(tx.fingerprint, true)
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set())
  const [rate, setRate] = useState('')
  if (candidates.isPending) {
    return <p className="text-[13px] text-muted-foreground">{t('links.searching')}</p>
  }
  const items = candidates.data ?? []
  if (items.length === 0) {
    return (
      <p className="text-[13px] text-muted-foreground">
        {t('links.exchange.noCandidates')}
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <CandidatePicker
        items={items}
        chosen={chosen}
        onToggle={(fp) => setChosen((current) => toggled(current, fp))}
        label={t('links.exchange.candidates')}
      />
      {withRate && (
        <label className="flex flex-col gap-1 text-[13px] font-semibold text-ink-2">
          {t('links.exchange.agreedRateOptional')}
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
          {t('links.exchange.pair')}
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
          {t('links.exchange.needsRate')}
        </p>
      )}
      <ul aria-label={t('links.exchange.legs')} className="flex flex-col gap-2">
        {exchange.legs.map((leg) => (
          <LinkedRow
            key={leg.fingerprint}
            item={leg}
            action={
              <Action
                label={t('links.exchange.removeLegOf', { merchant: leg.merchant })}
                disabled={change.isPending}
                onClick={() => change.mutate({ action: 'remove', id, fingerprint: leg.fingerprint })}
              >
                {t('links.remove')}
              </Action>
            }
          />
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[13px] font-semibold text-ink-2">
          {t('links.exchange.agreedRate')}
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
          {rate.trim() ? t('links.exchange.saveRate') : t('links.exchange.useImplied')}
        </Action>
      </div>
      <p className="text-[13px] text-muted-foreground">
        {t('links.exchange.impliedHint', { rate: rateLabel(exchange.implied_rate) })}
      </p>
      <div className="flex flex-wrap gap-2">
        <Action
          disabled={change.isPending}
          onClick={() => change.mutate({ action: 'update', id, closed: !exchange.closed })}
        >
          {exchange.closed ? t('links.exchange.reopen') : t('links.exchange.close')}
        </Action>
      </div>
      <div className="flex flex-col gap-2 border-t border-border pt-3">
        <h3 className="text-[13px] font-semibold text-ink-2">{t('links.exchange.addLegs')}</h3>
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
