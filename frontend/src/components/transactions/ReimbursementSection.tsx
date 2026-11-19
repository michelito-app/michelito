import { useId, useState } from 'react'
import type { GroupCandidate, Tx } from '@/lib/api'
import { expenseCount, groupLabel, linkedLabel } from '@/lib/links'
import { useChangeGroup, useReimbursementCandidates, useUnlinkCredit } from '@/lib/queries'
import { Action, Failure, LoadFailure, SECTION, SECTION_TITLE } from './linkParts'

interface ReimbursementSectionProps {
  tx: Tx
}

/** Un crédito: de qué grupo compartido es reembolso, la sugerencia y "Es reembolso de…". */
export function ReimbursementSection({ tx }: ReimbursementSectionProps) {
  const ids = useId()
  const change = useChangeGroup()
  const unlink = useUnlinkCredit()
  const unlinked = tx.link !== 'reimbursement'
  const candidates = useReimbursementCandidates(tx.fingerprint, unlinked)
  const of = tx.reimbursement_of
  const suggested = tx.suggested_group

  function link(id: number) {
    change.mutate({ action: 'add-credit', id, credit: tx.fingerprint })
  }

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        Reembolso
      </h2>
      {tx.link === 'reimbursement' ? (
        <>
          <p className="text-[13px] text-ink-2">
            {tx.shared ? (
              <>
                Reembolso de <span className="font-semibold">{tx.shared.title}</span>: no cuenta
                como ingreso.
              </>
            ) : of ? (
              <>
                Reembolso de <span className="font-semibold">{linkedLabel(of)}</span>: no cuenta
                como ingreso.
              </>
            ) : (
              'Reembolso de un gasto compartido que ya no aparece: no cuenta como ingreso.'
            )}
          </p>
          <div>
            <Action disabled={unlink.isPending} onClick={() => unlink.mutate(tx.fingerprint)}>
              Quitar el enlace
            </Action>
          </div>
        </>
      ) : (
        <>
          {suggested && (
            <div className="flex flex-col gap-2 rounded-lg border border-dashed border-primary/40 px-3 py-2.5">
              <p className="text-[13px] text-ink-2">
                ¿Reembolso de <span className="font-semibold">{suggested.title}</span>?
              </p>
              <div className="flex flex-wrap gap-2">
                <Action primary disabled={change.isPending} onClick={() => link(suggested.id)}>
                  Sí, enlazar
                </Action>
              </div>
            </div>
          )}
          <div className="flex flex-col gap-2">
            <h3 className="text-[13px] font-semibold text-ink-2">Es reembolso de…</h3>
            {candidates.isError ? (
              <LoadFailure what="los grupos" error={candidates.error} />
            ) : candidates.isPending ? (
              <p className="text-[13px] text-muted-foreground">Buscando…</p>
            ) : (candidates.data?.groups ?? []).length === 0 ? (
              <p className="text-[13px] text-muted-foreground">
                Ningún grupo compartido con algo pendiente en los 4 meses antes.
              </p>
            ) : (
              <GroupPicker
                groups={candidates.data?.groups ?? []}
                disabled={change.isPending}
                onPick={link}
              />
            )}
          </div>
        </>
      )}
      <Failure error={change.error ?? unlink.error} />
    </section>
  )
}

interface GroupPickerProps {
  groups: GroupCandidate[]
  disabled: boolean
  onPick: (id: number) => void
}

/** Los grupos que el servidor marcó (su pendiente cubre el crédito) y el resto tras «Ver
 * más». */
function GroupPicker({ groups, disabled, onPick }: GroupPickerProps) {
  const [expanded, setExpanded] = useState(false)
  const primary = groups.filter((g) => g.primary)
  const more = groups.filter((g) => !g.primary)
  const shown = expanded ? groups : primary
  return (
    <div className="flex flex-col gap-2">
      {shown.length === 0 && (
        <p className="text-[13px] text-muted-foreground">
          Nada encaja de lleno: lo demás está en «Ver más».
        </p>
      )}
      <ul aria-label="Grupos compartidos" className="flex flex-col gap-2">
        {shown.map((group) => (
          <li
            key={group.id}
            className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[13px]"
          >
            <span className="flex min-w-0 flex-col">
              <span className="font-semibold break-words">{groupLabel(group)}</span>
              <span className="text-muted-foreground">{expenseCount(group.expense_count)}</span>
            </span>
            <Action
              label={`Enlazar a ${group.title}`}
              disabled={disabled}
              onClick={() => onPick(group.id)}
            >
              Enlazar
            </Action>
          </li>
        ))}
      </ul>
      {more.length > 0 && (
        <div>
          <Action onClick={() => setExpanded((v) => !v)}>
            {expanded ? 'Ver menos' : `Ver más (${more.length})`}
          </Action>
        </div>
      )}
    </div>
  )
}
