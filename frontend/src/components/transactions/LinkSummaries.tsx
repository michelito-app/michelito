import { useLocation, useNavigate } from 'react-router'
import type { Tx } from '@/lib/api'
import { linkedLabel, linkPagePath, linkSummaries, type LinkSummary } from '@/lib/links'
import { useChangeExchange, useChangeGroup } from '@/lib/queries'
import { Action, Failure, SECTION, SECTION_TITLE } from './linkParts'

/** En el panel del detalle: una línea por vínculo y «Gestionar…» (o «Compartir…»), que abre la
 * pantalla del vínculo. Las sugerencias quedan como atajo de un clic. */
export function LinkSummaries({ tx }: { tx: Tx }) {
  const navigate = useNavigate()
  const location = useLocation()
  const summaries = linkSummaries(tx)
  if (summaries.length === 0) return null

  function manage() {
    navigate(linkPagePath(tx.fingerprint), {
      state: { from: `${location.pathname}${location.search}` },
    })
  }

  return (
    <>
      {summaries.map((summary) => (
        <section key={summary.kind} aria-label={summary.title} className={SECTION}>
          <h3 className={SECTION_TITLE}>{summary.title}</h3>
          <p data-testid={`link-summary-${summary.kind}`} className="text-[13px] text-ink-2">
            {summary.text}
          </p>
          <Shortcut tx={tx} summary={summary} />
          <div>
            <Action onClick={manage}>{summary.action}</Action>
          </div>
        </section>
      ))}
    </>
  )
}

/** «¿Reembolso de…? Sí, enlazar» o «¿Cambio con…? Sí, vincular» sin salir del panel. */
function Shortcut({ tx, summary }: { tx: Tx; summary: LinkSummary }) {
  const add = useChangeGroup()
  const change = useChangeExchange()
  const reimbursement = summary.kind === 'reimbursement' ? tx.suggested_group : null
  const exchange = summary.kind === 'exchange' ? tx.suggested_exchange_with : null
  if (reimbursement === null && exchange === null) return null
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-dashed border-primary/40 px-3 py-2.5">
      <p className="text-[13px] text-ink-2">
        {reimbursement ? '¿Reembolso de ' : '¿Es un cambio de divisas con '}
        <span className="font-semibold">
          {reimbursement ? reimbursement.title : linkedLabel(exchange!)}
        </span>
        ?
      </p>
      <div>
        {reimbursement ? (
          <Action
            primary
            disabled={add.isPending}
            onClick={() =>
              add.mutate({ action: 'add-credit', id: reimbursement.id, credit: tx.fingerprint })
            }
          >
            Sí, enlazar
          </Action>
        ) : (
          <Action
            primary
            disabled={change.isPending}
            onClick={() =>
              change.mutate({ action: 'create', fingerprints: [tx.fingerprint, exchange!.fingerprint] })
            }
          >
            Sí, vincular
          </Action>
        )}
      </div>
      <Failure error={add.error ?? change.error} />
    </div>
  )
}
