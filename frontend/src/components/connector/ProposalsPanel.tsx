import { useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { PANEL, PANEL_TITLE, ROW_DIVIDER } from '@/components/summary/styles'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { t } from '@/i18n'
import { formatMoney } from '@/lib/links'
import { shortDay } from '@/lib/months'
import {
  type Proposal,
  type ProposalItem,
  applyProposal,
  dismissProposal,
  openProposals,
  outcomeLine,
  useProposals,
  withChosenFirst,
} from '@/lib/proposals'
import { cn } from '@/lib/utils'

/** Review → the AI's proposals: each open batch with its changes (all ticked), to apply the
 * ticked ones or dismiss it. Nothing shows when there is none. `chosen`: the one the AI's link
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
  const [ticked, setTicked] = useState<ReadonlySet<number>>(() => new Set(proposal.items.map((i) => i.id)))
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
          {t('connector.proposals.from', {
            source: proposal.source,
            count: t('connector.proposals.changes', { count: proposal.items.length }),
          })}
        </p>
        {proposal.explanation && (
          <>
            <p className="text-sm whitespace-pre-line text-ink-2">{proposal.explanation}</p>
            <p className="text-xs text-muted-foreground">{t('connector.proposals.dataNote', { source: proposal.source })}</p>
          </>
        )}
      </header>
      <div className="flex gap-1 text-[13px]">
        <Button variant="ghost" size="sm" className="h-9 px-2" onClick={() => setTicked(new Set(proposal.items.map((i) => i.id)))}>
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
      </ul>
      {failure && (
        <p role="alert" className="rounded-xl bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {failure}
        </p>
      )}
      <div className="flex flex-col gap-2 sm:flex-row">
        <Button
          className="h-11 px-5"
          disabled={busy || count === 0}
          onClick={() => void act(() => applyProposal(proposal.id, [...ticked]))}
        >
          {count === 0 ? t('connector.proposals.applyNone') : t('connector.proposals.apply', { count })}
        </Button>
        <Button variant="ghost" className="h-11 px-4" disabled={busy} onClick={() => void act(() => dismissProposal(proposal.id))}>
          {t('connector.proposals.dismiss')}
        </Button>
      </div>
    </article>
  )
}

function ItemRow({ item, on, onChange }: { item: ProposalItem; on: boolean; onChange: (on: boolean) => void }) {
  const label = `proposal-item-${item.id}`
  return (
    <li className={cn(ROW_DIVIDER, 'flex items-start gap-3 py-3')} data-testid="proposal-item">
      <Checkbox aria-labelledby={label} checked={on} onCheckedChange={(value) => onChange(value === true)} className="mt-1" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-baseline justify-between gap-3">
          <span id={label} className="truncate text-sm font-semibold">
            {item.merchant || item.description}
          </span>
          <span className="shrink-0 text-sm tabular-nums">{formatMoney(item.amount_cents, item.currency)}</span>
        </div>
        <p className="text-xs text-muted-foreground">
          {shortDay(item.day)} ·{' '}
          {t('connector.proposals.move', { from: item.from_category, to: item.to_category || t('connector.proposals.missingCategory') })}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={item.scope === 'merchant' ? 'default' : 'secondary'}>
            {item.scope === 'merchant' ? t('connector.proposals.rule') : t('connector.proposals.onlyThis')}
          </Badge>
          {item.reason && <span className="text-xs text-ink-2">{item.reason}</span>}
        </div>
      </div>
    </li>
  )
}
