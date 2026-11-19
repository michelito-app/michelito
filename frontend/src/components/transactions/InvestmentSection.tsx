import { useId, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { ApiError, type CreditRole, type InvestmentRef, type Tx } from '@/lib/api'
import { STATUS_LABELS } from '@/lib/investments'
import { formatMoney, grossCents } from '@/lib/links'
import { useChangeInvestment, useInvestment, useOpenInvestments } from '@/lib/queries'
import { InvestmentPanel } from './InvestmentPanel'
import { Action, Failure, FIELD, LoadFailure, SECTION, SECTION_TITLE } from './linkParts'
import { RoleForm } from './RoleForm'

/** "Inversión" de una transacción: si ya es de una, la gestión de la inversión; si no, un
 * débito ofrece «Es una inversión…» (nueva o una existente) y un crédito «Es de una
 * inversión…» (cuál y de qué tipo). */
export function InvestmentSection({ tx }: { tx: Tx }) {
  if (tx.link === 'investment') return <Linked tx={tx} />
  if (tx.can_invest) return <ContributionStart tx={tx} />
  if (tx.can_invest_credit) return <CreditStart tx={tx} />
  return null
}

function Linked({ tx }: { tx: Tx }) {
  const ids = useId()
  const id = tx.investment?.id ?? null
  const query = useInvestment(id)
  const change = useChangeInvestment()
  const missing = query.error instanceof ApiError && query.error.status === 404
  if (query.isError && !missing) {
    return <LoadError what="la inversión" error={query.error} onRetry={() => query.refetch()} />
  }
  if (id === null || missing) {
    // Dormida: la inversión ya no tiene aportes a la vista (un estado cambió).
    return (
      <section aria-labelledby={`${ids}-title`} className={SECTION}>
        <h2 id={`${ids}-title`} className={SECTION_TITLE}>
          Inversión
        </h2>
        <p className="text-[13px] text-ink-2">
          Está en una inversión, pero sus aportes ya no aparecen en los estados.
        </p>
        {tx.link_id !== null && (
          <div>
            <Action
              disabled={change.isPending}
              onClick={() =>
                change.mutate({ action: 'remove', id: tx.link_id!, fingerprint: tx.fingerprint })
              }
            >
              Quitar de la inversión
            </Action>
          </div>
        )}
        <Failure error={change.error} />
      </section>
    )
  }
  if (query.data === undefined) {
    return <p className="text-[13px] text-muted-foreground">Cargando…</p>
  }
  return <InvestmentPanel investment={query.data} current={tx.fingerprint} />
}

/** Un débito: inversión nueva (nombre opcional y «Con quién») o añadirlo a una existente. */
function ContributionStart({ tx }: { tx: Tx }) {
  const ids = useId()
  const change = useChangeInvestment()
  const [mode, setMode] = useState<'new' | 'join'>('new')
  const [name, setName] = useState('')
  const [withWhom, setWithWhom] = useState('')
  const open = useOpenInvestments(true)
  const existing = open.data ?? []
  const hint = tx.suggested_investment?.kind === 'aporte_posible' ? tx.suggested_investment : null
  const label = 'flex min-w-0 flex-col gap-1 text-[13px] font-semibold text-ink-2'

  const join = (investment: InvestmentRef) =>
    change.mutate({
      action: 'add',
      id: investment.id,
      fingerprint: tx.fingerprint,
      role: 'contribution',
    })

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        Es una inversión
      </h2>
      <p className="text-[13px] text-muted-foreground">
        Dinero que mandaste para que lo inviertan: no es gasto ni resta de lo que te quedó.
        Envío de {formatMoney(grossCents(tx), tx.currency)}.
      </p>
      {hint && (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-primary/40 px-3 py-2.5">
          <p className="text-[13px] text-ink-2">
            ¿Es otro aporte a <span className="font-semibold">{hint.title}</span>?
          </p>
          <div>
            <Action primary disabled={change.isPending} onClick={() => join(hint)}>
              Sí, es otro aporte
            </Action>
          </div>
        </div>
      )}
      {open.isError && <LoadFailure what="las inversiones" error={open.error} />}
      {existing.length > 0 && (
        <div role="tablist" aria-label="Cómo marcarla" className="flex flex-wrap gap-2">
          <Action
            primary={mode === 'new'}
            tab={{ selected: mode === 'new' }}
            onClick={() => setMode('new')}
          >
            Inversión nueva
          </Action>
          <Action
            primary={mode === 'join'}
            tab={{ selected: mode === 'join' }}
            onClick={() => setMode('join')}
          >
            Añadir a una existente
          </Action>
        </div>
      )}
      {mode === 'new' && (
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2">
            <label className={label}>
              Con quién
              <input
                maxLength={80}
                placeholder="Pedro"
                value={withWhom}
                onChange={(event) => setWithWhom(event.target.value)}
                className={FIELD}
              />
            </label>
            <label className={label}>
              Nombre (opcional)
              <input
                maxLength={80}
                placeholder="Negocio, préstamo…"
                value={name}
                onChange={(event) => setName(event.target.value)}
                className={FIELD}
              />
            </label>
          </div>
          <div>
            <Action
              primary
              disabled={change.isPending}
              onClick={() =>
                change.mutate({
                  action: 'create',
                  fingerprint: tx.fingerprint,
                  withWhom: withWhom.trim() || null,
                  name: name.trim() || null,
                })
              }
            >
              Marcar como inversión
            </Action>
          </div>
        </div>
      )}
      {mode === 'join' && (
        <ul aria-label="Inversiones" className="flex flex-col gap-2">
          {existing.map((investment) => (
            <li
              key={investment.id}
              className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[13px]"
            >
              <span className="min-w-0 font-semibold break-words">
                {investment.title} · {STATUS_LABELS[investment.status]}
              </span>
              <Action
                label={`Añadir a ${investment.title}`}
                disabled={change.isPending}
                onClick={() => join(investment)}
              >
                Añadir
              </Action>
            </li>
          ))}
        </ul>
      )}
      <Failure error={change.error} />
    </section>
  )
}

/** Un crédito: de qué inversión es y de qué tipo (rendimiento, capital o mixto). */
function CreditStart({ tx }: { tx: Tx }) {
  const ids = useId()
  const change = useChangeInvestment()
  const open = useOpenInvestments(true, true) // también las dadas por perdidas
  const existing = open.data ?? []
  const hinted = tx.suggested_investment?.kind === 'cobro_posible' ? tx.suggested_investment : null
  const [chosen, setChosen] = useState<number | null>(hinted?.id ?? null)
  const picked = chosen ?? existing[0]?.id ?? null
  const amount = Math.abs(grossCents(tx))

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        Es de una inversión
      </h2>
      {open.isError && <LoadFailure what="las inversiones" error={open.error} />}
      {hinted && (
        <p className="rounded-lg border border-dashed border-primary/40 px-3 py-2.5 text-[13px] text-ink-2">
          ¿Es un cobro de <span className="font-semibold">{hinted.title}</span>?
        </p>
      )}
      {open.isSuccess && existing.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          Aún no tienes inversiones: márcala primero desde el débito con que mandaste el dinero.
        </p>
      ) : (
        <>
          <label className="flex flex-col gap-1 text-[13px] font-semibold text-ink-2">
            Inversión
            <select
              aria-label="Inversión"
              value={picked ?? ''}
              onChange={(event) => setChosen(Number(event.target.value))}
              className={FIELD}
            >
              {existing.map((investment) => (
                <option key={investment.id} value={investment.id}>
                  {investment.title} · {STATUS_LABELS[investment.status]}
                </option>
              ))}
            </select>
          </label>
          <RoleForm
            amountCents={amount}
            currency={tx.currency}
            saving={change.isPending || picked === null}
            submitLabel="Enlazar a la inversión"
            onSave={(body) => {
              if (picked === null) return
              const role: CreditRole = body.role
              change.mutate({
                action: 'add',
                id: picked,
                fingerprint: tx.fingerprint,
                role,
                capitalCents: body.capital_cents,
              })
            }}
          />
        </>
      )}
      <Failure error={change.error} />
    </section>
  )
}
