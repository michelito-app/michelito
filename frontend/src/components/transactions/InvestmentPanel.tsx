import { useId, useState } from 'react'
import type { Candidate, CreditRole, Investment, InvestmentEntry } from '@/lib/api'
import {
  entryRole,
  excessWarning,
  investmentStats,
  STATUS_LABELS,
  unconvertedWarning,
} from '@/lib/investments'
import { formatMoney } from '@/lib/links'
import { shortDay } from '@/lib/months'
import { useChangeInvestment, useInvestmentCandidates } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { CandidatePicker } from './CandidatePicker'
import {
  Action,
  ConfirmBox,
  CURRENT_ROW,
  Failure,
  FIELD,
  LoadFailure,
  SECTION,
  SECTION_TITLE,
} from './linkParts'
import { RoleForm } from './RoleForm'

const SUBTITLE = 'text-[13px] font-semibold text-ink-2'
const WARNING = 'rounded-lg bg-up-soft px-3 py-2 text-[13px] text-up-ink'

interface InvestmentPanelProps {
  investment: Investment
  /** La transacción abierta: se resalta en su lista. */
  current: string
}

/** Pantalla de gestión de una inversión: cifras en su moneda, nombre y «Con quién», sus
 * movimientos (cambiar el tipo de un crédito, quitar), añadir aportes o cobros y «Dar por
 * perdida» (o deshacerlo). */
export function InvestmentPanel({ investment, current }: InvestmentPanelProps) {
  const ids = useId()
  const change = useChangeInvestment()
  const warning = unconvertedWarning(investment)
  const excess = excessWarning(investment)
  const contributions = investment.entries.filter((e) => e.role === 'contribution')
  const credits = investment.entries.filter((e) => e.role !== 'contribution')

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION} data-testid="investment-panel">
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        Inversión · {STATUS_LABELS[investment.status]}
      </h2>
      <p className="text-base font-semibold break-words">{investment.title}</p>
      <dl
        data-testid="investment-line"
        className="grid grid-cols-[repeat(auto-fit,minmax(104px,1fr))] gap-2 rounded-lg bg-muted px-3 py-2.5"
      >
        {investmentStats(investment).map(({ key, label, value }) => (
          <div key={key} className="flex min-w-0 flex-col gap-0.5">
            <dt className="text-[11.5px] text-muted-foreground">{label}</dt>
            <dd className="text-[13px] font-semibold break-words tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      {excess && <p className={WARNING}>{excess}</p>}
      {warning && <p className={WARNING}>{warning}</p>}
      <Identity investment={investment} />

      <h3 className={SUBTITLE}>Aportes</h3>
      <ul aria-label="Aportes de la inversión" className="flex flex-col gap-3">
        {contributions.map((entry) => (
          <EntryRow
            key={entry.fingerprint}
            investment={investment}
            entry={entry}
            current={entry.fingerprint === current}
            last={contributions.length === 1}
          />
        ))}
      </ul>

      <h3 className={SUBTITLE}>Rendimientos y devoluciones</h3>
      {credits.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">Aún no ha vuelto nada.</p>
      ) : (
        <ul aria-label="Cobros de la inversión" className="flex flex-col gap-3">
          {credits.map((entry) => (
            <EntryRow
              key={entry.fingerprint}
              investment={investment}
              entry={entry}
              current={entry.fingerprint === current}
              last={false}
            />
          ))}
        </ul>
      )}

      {investment.status !== 'closed' && (
        <label className="flex min-h-11 cursor-pointer items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            checked={investment.written_off}
            disabled={change.isPending}
            onChange={(event) =>
              change.mutate({
                action: 'patch',
                id: investment.id,
                body: { written_off: event.target.checked },
              })
            }
            className="mt-0.5 size-[18px] shrink-0 cursor-pointer accent-up"
          />
          <span className="flex flex-col gap-0.5">
            <span className="font-semibold">Dar por perdida</span>
            <span className="text-[13px] text-muted-foreground">
              Ya no esperas que vuelva el capital: sale de «Capital por volver»
            </span>
          </span>
        </label>
      )}
      <Failure error={change.error} />

      <AddMovement investment={investment} kind="contribution" />
      <AddMovement investment={investment} kind="credit" />
    </section>
  )
}

/** Nombre (opcional) y «Con quién», editables. */
function Identity({ investment }: { investment: Investment }) {
  const change = useChangeInvestment()
  const [name, setName] = useState(investment.name)
  const [withWhom, setWithWhom] = useState(investment.with_whom)
  const dirty = name.trim() !== investment.name || withWhom.trim() !== investment.with_whom
  const label = 'flex min-w-0 flex-col gap-1 text-[13px] font-semibold text-ink-2'
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2">
        <label className={label}>
          Con quién
          <input
            maxLength={80}
            value={withWhom}
            onChange={(e) => setWithWhom(e.target.value)}
            className={FIELD}
          />
        </label>
        <label className={label}>
          Nombre (opcional)
          <input
            maxLength={80}
            placeholder="Negocio, préstamo…"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={FIELD}
          />
        </label>
      </div>
      {dirty && (
        <div>
          <Action
            disabled={change.isPending}
            onClick={() =>
              change.mutate({
                action: 'patch',
                id: investment.id,
                body: { name: name.trim() || null, with_whom: withWhom.trim() || null },
              })
            }
          >
            Guardar nombre
          </Action>
        </div>
      )}
      <Failure error={change.error} />
    </div>
  )
}

interface EntryRowProps {
  investment: Investment
  entry: InvestmentEntry
  current: boolean
  /** Es el último aporte: quitarlo borra la inversión (pide confirmar). */
  last: boolean
}

function EntryRow({ investment, entry, current, last }: EntryRowProps) {
  const change = useChangeInvestment()
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const credit = entry.role !== 'contribution'

  function remove() {
    change.mutate({ action: 'remove', id: investment.id, fingerprint: entry.fingerprint })
  }

  return (
    <li
      aria-current={current ? 'true' : undefined}
      className={cn('flex flex-col gap-2 text-[13px]', current && CURRENT_ROW)}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="flex min-w-0 flex-col">
          <span className="font-semibold break-words text-foreground">
            {entry.merchant} ({shortDay(entry.day)})
          </span>
          <span className="text-muted-foreground">
            {entry.account_label} ·{' '}
            <span className="tabular-nums">{formatMoney(entry.amount_cents, entry.currency)}</span>
          </span>
          <span data-testid="entry-role" className="font-semibold break-words text-ink-2">
            {entryRole(entry)}
            {!entry.counted && ' · sin tasa: no suma'}
          </span>
        </span>
        <div className="flex flex-wrap gap-2">
          {credit && (
            <Action
              label={`Cambiar el tipo de ${entry.merchant}`}
              onClick={() => setEditing((v) => !v)}
            >
              Cambiar tipo
            </Action>
          )}
          <Action
            label={`Quitar ${entry.merchant} de la inversión`}
            disabled={change.isPending}
            onClick={() => (last ? setConfirming(true) : remove())}
          >
            Quitar
          </Action>
        </div>
      </div>
      {confirming && (
        <ConfirmBox
          label="Quitar el último aporte"
          confirmLabel="Sí, quitar y borrar la inversión"
          busy={change.isPending}
          onConfirm={remove}
          onCancel={() => setConfirming(false)}
        >
          Es el último aporte: se borra la inversión y sus cobros vuelven a su categoría.
        </ConfirmBox>
      )}
      {editing && credit && (
        <RoleForm
          amountCents={entry.amount_cents}
          currency={entry.currency}
          initial={entry.role as CreditRole}
          initialCapital={entry.role === 'mixed' ? entry.capital_cents : null}
          saving={change.isPending}
          submitLabel="Guardar tipo"
          onCancel={() => setEditing(false)}
          onSave={(body) =>
            change.mutate(
              { action: 'role', id: investment.id, fingerprint: entry.fingerprint, body },
              { onSuccess: () => setEditing(false) },
            )
          }
        />
      )}
      <Failure error={change.error} />
    </li>
  )
}

interface AddMovementProps {
  investment: Investment
  kind: 'contribution' | 'credit'
}

/** «Añadir un aporte» (débitos) o «Añadir un cobro» (créditos, con su tipo). */
function AddMovement({ investment, kind }: AddMovementProps) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<Candidate | null>(null)
  const candidates = useInvestmentCandidates(investment.id, kind, open)
  const change = useChangeInvestment()
  const contribution = kind === 'contribution'
  const label = contribution ? 'Añadir un aporte' : 'Añadir un cobro'

  function add(item: Candidate, role: 'contribution' | CreditRole, capitalCents?: number) {
    change.mutate(
      { action: 'add', id: investment.id, fingerprint: item.fingerprint, role, capitalCents },
      {
        onSuccess: () => {
          setPicked(null)
          setOpen(false)
        },
      },
    )
  }

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-3">
      <div>
        <Action onClick={() => setOpen((v) => !v)}>{open ? 'Cerrar' : label}</Action>
      </div>
      {open && picked === null && (
        <>
          {candidates.isError ? (
            <LoadFailure what="los movimientos" error={candidates.error} />
          ) : candidates.isPending ? (
            <p className="text-[13px] text-muted-foreground">Buscando…</p>
          ) : (candidates.data ?? []).length === 0 ? (
            <p className="text-[13px] text-muted-foreground">
              {contribution
                ? 'Ningún débito bancario sin vincular cerca de los aportes.'
                : 'Ningún crédito bancario sin vincular desde el primer aporte.'}
            </p>
          ) : (
            <CandidatePicker
              items={candidates.data ?? []}
              label={
                contribution ? 'Débitos que pueden ser un aporte' : 'Créditos que pueden ser un cobro'
              }
              action={(item) => (
                <Action
                  label={`Añadir ${item.merchant}`}
                  disabled={change.isPending}
                  onClick={() => (contribution ? add(item, 'contribution') : setPicked(item))}
                >
                  Añadir
                </Action>
              )}
            />
          )}
        </>
      )}
      {picked && (
        <RoleForm
          amountCents={Math.abs(picked.amount_cents)}
          currency={picked.currency}
          saving={change.isPending}
          submitLabel="Añadir a la inversión"
          onCancel={() => setPicked(null)}
          onSave={(body) => add(picked, body.role, body.capital_cents)}
        />
      )}
      <Failure error={change.error} />
    </div>
  )
}
