import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { AddExpenseSheet } from '@/components/shared/AddExpenseSheet'
import { DebitPaymentSheet } from '@/components/shared/DebitPaymentSheet'
import { CreditPaymentSheet, SharedTxPanel } from '@/components/shared/TxShared'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import type { Tx } from '@/lib/api'
import { linkedLabel, linkPagePath, linkSummaries, type LinkSummary } from '@/lib/links'
import { useChangeExchange } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { Action, Failure, SECTION, SECTION_TITLE } from './linkParts'

/** In the detail panel: one line per link and its button: "Open group" for a row in a shared
 * group, "Share…" (straight to "I paid it" with it), "It is a payment…" for a credit, or manage,
 * which opens the link's screen. Suggestions stay as a one-click shortcut. */
export function LinkSummaries({ tx }: { tx: Tx }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [open, setOpen] = useState<'share' | 'credit' | 'debit' | null>(null)
  const summaries = linkSummaries(tx)
  if (summaries.length === 0) return null

  function act(summary: LinkSummary) {
    if (summary.kind === 'shared') return setOpen('share')
    if (summary.kind === 'reimbursement') return setOpen('credit')
    if (summary.kind === 'debitPayment') return setOpen('debit')
    navigate(linkPagePath(tx.fingerprint), {
      state: { from: `${location.pathname}${location.search}` },
    })
  }

  return (
    <>
      {summaries.map((summary) =>
        summary.kind === 'shared' && tx.ledger ? (
          <section key={summary.kind} aria-label={summary.title} className={SECTION}>
            <h3 className={SECTION_TITLE}>{summary.title}</h3>
            <SharedTxPanel tx={tx} />
          </section>
        ) : (
        <section key={summary.kind} aria-label={summary.title} className={SECTION}>
          <h3 className={SECTION_TITLE}>{summary.title}</h3>
          <p data-testid={`link-summary-${summary.kind}`} className="text-[13px] text-ink-2">
            {summary.text}
          </p>
          <Shortcut tx={tx} summary={summary} />
          <div>
            {summary.href ? (
              <Link
                to={summary.href}
                state={{ from: `${location.pathname}${location.search}` }}
                className={cn(
                  'inline-flex h-11 items-center rounded-xl border border-[#D6D6D0] bg-card px-4 text-sm font-semibold text-ink-2 no-underline hover:bg-muted',
                  FOCUS,
                )}
              >
                {summary.action}
              </Link>
            ) : (
              <Action onClick={() => act(summary)}>{summary.action}</Action>
            )}
          </div>
        </section>
        ),
      )}
      {open === 'share' && (
        <AddExpenseSheet tx={tx} onClose={() => setOpen(null)} onSaved={() => setOpen(null)} />
      )}
      {open === 'credit' && <CreditPaymentSheet tx={tx} onClose={() => setOpen(null)} />}
      {open === 'debit' && <DebitPaymentSheet tx={tx} onClose={() => setOpen(null)} />}
    </>
  )
}

/** Accept a suggested exchange without leaving the panel. */
function Shortcut({ tx, summary }: { tx: Tx; summary: LinkSummary }) {
  const change = useChangeExchange()
  const exchange = summary.kind === 'exchange' ? tx.suggested_exchange_with : null
  if (exchange === null) return null
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-dashed border-primary/40 px-3 py-2.5">
      <p className="text-[13px] text-ink-2">
        {tn('links.shortcut.exchange', {
          what: <span className="font-semibold">{linkedLabel(exchange)}</span>,
        })}
      </p>
      <div>
        <Action
          primary
          disabled={change.isPending}
          onClick={() =>
            change.mutate({ action: 'create', fingerprints: [tx.fingerprint, exchange.fingerprint] })
          }
        >
          {t('links.shortcut.pair')}
        </Action>
      </div>
      <Failure error={change.error} />
    </div>
  )
}
