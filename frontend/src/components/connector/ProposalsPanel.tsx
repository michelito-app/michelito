import { useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import {
  type Proposal,
  applyProposal,
  dismissProposal,
  initialTicks,
  kindLine,
  openProposals,
  outcomeLine,
  selectableIds,
  useProposals,
  withChosenFirst,
} from '@/lib/proposals'
import { cn } from '@/lib/utils'
import { ImportRowView, ItemRow, StatementView } from './ProposalRows'

/** Review → the AI's proposals: each open batch with its changes or imported rows (ticked,
 * except possible duplicates) or its statement, to apply or dismiss. Nothing shows when there is none. `chosen`: the one the AI's link
 * named (`/review?proposal=12`): first and scrolled to. */
export function ProposalsPanel({ chosen }: { chosen: number | null }) {
  const found = useProposals()
  const [answered, setAnswered] = useState<Proposal[]>([])
  if (found.error) {
    return <LoadError what={t('connector.proposals.what')} error={found.error} onRetry={() => void found.refetch()} />
  }
  if (!found.data) return null
  const open = withChosenFirst(openProposals(found.data), chosen)
  if (open.length === 0 && answered.length === 0) return null
  return (
    <section aria-labelledby="proposals-title" className="flex flex-col gap-3" data-testid="proposals">
      <h2 id="proposals-title" className="flex items-center gap-2 text-lg font-semibold">
        <Sparkles size={18} aria-hidden="true" className="text-primary" />
        {t('connector.proposals.title')}
      </h2>
      {answered.map((p) => (
        <p key={p.id} role="status" className="rounded-xl bg-muted px-4 py-3 text-sm text-ink-2">
          <span className="font-semibold">{p.title}</span>: {outcomeLine(p)}.{' '}
          {p.status === 'applied' && t('connector.proposals.undoHint')}
        </p>
      ))}
      {open.map((p) => (
        <ProposalCard
          key={p.id}
          proposal={p}
          focused={p.id === chosen}
          onAnswered={(done) => setAnswered((list) => [done, ...list.filter((x) => x.id !== done.id)])}
        />
      ))}
    </section>
  )
}

interface CardProps {
  proposal: Proposal
  focused: boolean
  onAnswered: (done: Proposal) => void
}

function ProposalCard({ proposal, focused, onAnswered }: CardProps) {
  const client = useQueryClient()
  const ref = useRef<HTMLElement>(null)
  const [ticked, setTicked] = useState<ReadonlySet<number>>(() => new Set(initialTicks(proposal)))
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: 'start' })
  }, [focused])

  function toggle(id: number, on: boolean) {
    setTicked((current) => {
      const next = new Set(current)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })
  }

  async function act(run: () => Promise<Proposal>) {
    setBusy(true)
    setFailure(null)
    try {
      const done = await run()
      onAnswered(done)
      await client.invalidateQueries()
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const count = ticked.size
  const whole = proposal.kind === 'statement' // stored whole: nothing to tick
  return (
    <article
      ref={ref}
      aria-labelledby={`proposal-${proposal.id}`}
      data-testid="proposal"
      className={cn(PANEL, 'flex scroll-mt-20 flex-col gap-3 px-5 py-4', focused && 'ring-2 ring-primary/40')}
    >
      <header className="flex flex-col gap-1">
        <h3 id={`proposal-${proposal.id}`} className={PANEL_TITLE}>
          {proposal.title}
        </h3>
        <p className="text-xs text-muted-foreground">
          {t('connector.proposals.from', { source: proposal.source, count: kindLine(proposal) })}
        </p>
        {proposal.explanation && (
          <>
            <p className="text-sm whitespace-pre-line text-ink-2">{proposal.explanation}</p>
            <p className="text-xs text-muted-foreground">{t('connector.proposals.dataNote', { source: proposal.source })}</p>
          </>
        )}
      </header>
      {whole ? (
        proposal.statement && <StatementView statement={proposal.statement} />
      ) : (
        <>
          <div className="flex gap-1 text-[13px]">
            <Button variant="ghost" size="sm" className="h-9 px-2" onClick={() => setTicked(new Set(selectableIds(proposal)))}>
              {t('connector.proposals.selectAll')}
            </Button>
            <Button variant="ghost" size="sm" className="h-9 px-2" onClick={() => setTicked(new Set())}>
              {t('connector.proposals.selectNone')}
            </Button>
          </div>
          <ul className="flex flex-col">
            {proposal.items.map((item) => (
              <ItemRow key={item.id} item={item} on={ticked.has(item.id)} onChange={(on) => toggle(item.id, on)} />
            ))}
            {proposal.rows.map((row) => (
              <ImportRowView key={row.id} row={row} on={ticked.has(row.id)} onChange={(on) => toggle(row.id, on)} />
            ))}
          </ul>
        </>
      )}
      {failure && (
        <p role="alert" className="rounded-xl bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {failure}
        </p>
      )}
      <div className="flex flex-col gap-2 sm:flex-row">
        <Button
          className="h-11 px-5"
          disabled={busy || (!whole && count === 0)}
          onClick={() => void act(() => applyProposal(proposal.id, whole ? [] : [...ticked]))}
        >
          {whole
            ? t('connector.proposals.saveStatement')
            : count === 0
              ? t('connector.proposals.applyNone')
              : proposal.kind === 'category'
                ? t('connector.proposals.apply', { count })
                : t('connector.proposals.importRows', { count })}
        </Button>
        <Button variant="ghost" className="h-11 px-4" disabled={busy} onClick={() => void act(() => dismissProposal(proposal.id))}>
          {t('connector.proposals.dismiss')}
        </Button>
      </div>
    </article>
  )
}
