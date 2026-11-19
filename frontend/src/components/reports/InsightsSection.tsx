import { useState } from 'react'
import { ClaudeButton } from '@/components/claude/ClaudeButton'
import { LoadError } from '@/components/LoadError'
import { InsightText } from './InsightText'
import { FOCUS, PANEL, PANEL_TITLE, ROW_DIVIDER } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import type { Selection } from '@/lib/accountFilter'
import type { Insight, MonthOption } from '@/lib/api'
import { analyzeCommand, canSave, monthsWithout, remaining, STALE_NOTE, savedText } from '@/lib/insights'
import { useDeleteInsight, useInsights, useSaveInsight } from '@/lib/queries'
import { cn } from '@/lib/utils'

const SMALL = 'h-10 rounded-xl px-4 text-sm font-semibold'
const SECONDARY = cn(SMALL, 'border-[#D6D6D0] bg-card text-ink-2')

/** Saved analyses (newest first): read, edit and delete. For the months without an analysis, the
 * command to ask Claude Code for one. On each month, "Copy for Claude" with the screen's
 * accounts. */
export function InsightsSection({ months, selection }: { months: MonthOption[]; selection: Selection }) {
  const insights = useInsights()
  return (
    <section aria-labelledby="insights-title" className={cn(PANEL, 'flex min-w-0 flex-col gap-3 px-6 py-5')}>
      <div className="flex flex-col gap-1">
        <h2 id="insights-title" className={PANEL_TITLE}>
          {t('reports.insights.title')}
        </h2>
        <p className="text-[13px] text-muted-foreground">
          {tn('reports.insights.hint', {
            analysis: <code className="font-mono">michelito analysis</code>,
            save: <code className="font-mono">michelito insight save</code>,
          })}
        </p>
      </div>
      {insights.isError ? (
        <LoadError what={t('reports.insights.loadWhat')} error={insights.error} onRetry={() => insights.refetch()} />
      ) : insights.isPending ? (
        <Skeleton className="h-24 rounded-xl" />
      ) : (
        <>
          {insights.data.length > 0 && (
            <ul aria-label={t('reports.insights.savedLabel')} className="flex flex-col">
              {insights.data.map((insight) => (
                <InsightRow key={insight.month} insight={insight} selection={selection} />
              ))}
            </ul>
          )}
          <Missing months={monthsWithout(insights.data, months)} selection={selection} />
        </>
      )}
    </section>
  )
}

function InsightRow({ insight, selection }: { insight: Insight; selection: Selection }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const save = useSaveInsight()
  const remove = useDeleteInsight()
  const error = save.error ?? remove.error
  const editing = draft !== null

  function submit() {
    if (draft === null || !canSave(draft)) return
    save.mutate({ month: insight.month, text: draft }, { onSuccess: () => setDraft(null) })
  }

  return (
    <li className={cn(ROW_DIVIDER, 'flex flex-col gap-2 py-3')}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="text-[15px] font-semibold">{insight.label}</h3>
        <span className="text-[13px] text-muted-foreground">
          {savedText(insight)}
          {insight.accounts && t('reports.insights.accounts', { count: insight.accounts.length })}
        </span>
      </div>
      {insight.stale && <p className="text-[13px] font-semibold text-up">{STALE_NOTE}</p>}
      {editing ? (
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1 text-[13px] text-muted-foreground">
            {t('reports.insights.editLabel', { label: insight.label })}
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={8}
              className={cn('min-h-40 w-full rounded-lg border border-border bg-card p-3 text-sm text-foreground', FOCUS)}
            />
          </label>
          <p className={cn('text-[12px]', remaining(draft) < 0 ? 'font-semibold text-up' : 'text-muted-foreground')}>
            {remaining(draft) < 0
              ? t('reports.insights.over', { count: -remaining(draft) })
              : t('reports.insights.left', { count: remaining(draft) })}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button className={SMALL} disabled={!canSave(draft) || save.isPending} onClick={submit}>
              {t('common.save')}
            </Button>
            <Button variant="outline" className={SECONDARY} onClick={() => setDraft(null)}>
              {t('common.cancel')}
            </Button>
          </div>
        </div>
      ) : (
        <InsightText text={insight.text} />
      )}
      {!editing && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            className={SECONDARY}
            aria-label={t('reports.insights.editAction', { label: insight.label })}
            onClick={() => setDraft(insight.text)}
          >
            {t('reports.insights.edit')}
          </Button>
          <ClaudeButton month={insight.month} label={insight.label} selection={selection} />
          {confirming ? (
            <>
              <span className="text-[13px] text-ink-2">{t('reports.insights.confirmDelete')}</span>
              <Button
                variant="outline"
                className={SECONDARY}
                disabled={remove.isPending}
                onClick={() => remove.mutate(insight.month)}
              >
                {t('reports.insights.yesDelete')}
              </Button>
              <Button variant="outline" className={SECONDARY} onClick={() => setConfirming(false)}>
                {t('summary.review.no')}
              </Button>
            </>
          ) : (
            <Button
              variant="outline"
              className={SECONDARY}
              aria-label={t('reports.insights.deleteAction', { label: insight.label })}
              onClick={() => setConfirming(true)}
            >
              {t('reports.insights.delete')}
            </Button>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('summary.review.saveError', { message: error.message })}
        </p>
      )}
    </li>
  )
}

function Missing({ months, selection }: { months: MonthOption[]; selection: Selection }) {
  const [copied, setCopied] = useState<string | null>(null)
  if (months.length === 0) return null

  async function copy(month: string) {
    try {
      await navigator.clipboard.writeText(analyzeCommand(month))
      setCopied(month)
    } catch {
      setCopied(null) // no clipboard: the command stays in view to be copied by hand
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-[13px] font-semibold text-ink-2">{t('reports.insights.missingTitle')}</h3>
      <ul className="flex flex-col">
        {months.map((m) => (
          <li key={m.month} className={cn(ROW_DIVIDER, 'flex flex-wrap items-center justify-between gap-2 py-2')}>
            <span className="text-sm">
              {m.label}
              {m.partial && <span className="text-muted-foreground">{t('summary.trendBars.inProgressSuffix')}</span>}
            </span>
            <span className="flex flex-wrap items-center gap-2">
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12px]">{analyzeCommand(m.month)}</code>
              <Button
                variant="outline"
                className={SECONDARY}
                aria-label={t('reports.insights.copyCommandLabel', { label: m.label })}
                onClick={() => copy(m.month)}
              >
                {copied === m.month ? t('summary.insight.copied') : t('reports.insights.copyCommand')}
              </Button>
              <ClaudeButton month={m.month} label={m.label} selection={selection} />
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
