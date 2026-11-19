import { useState } from 'react'
import { Link } from 'react-router'
import { ClaudeButton } from '@/components/claude/ClaudeButton'
import { InsightText } from '@/components/reports/InsightText'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import type { Insight } from '@/lib/api'
import { analyzeCommand, STALE_NOTE, savedText } from '@/lib/insights'
import { monthTitle } from '@/lib/months'
import { cn } from '@/lib/utils'
import { FOCUS } from './styles'

/** "Analysis" (a tab of "Month reading"): the month's saved analysis (Claude Code). It is edited in
 * Reports. */
export function InsightBody({ insight }: { insight: Insight }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13px] text-muted-foreground">
        {savedText(insight)}
        {insight.stale && <span className="font-semibold text-up"> · {STALE_NOTE}</span>}
        {' · '}
        <Link to="/reports" className={cn('rounded-sm font-semibold text-primary', FOCUS)}>
          {t('summary.insight.editInReports')}
        </Link>
      </p>
      <InsightText text={insight.text} />
    </div>
  )
}

/** Nothing to read: the command to ask for the month's analysis, with a button to copy it, and
 * "Copy for Claude". */
export function NoReading({ month, selection }: { month: string; selection: Selection }) {
  const [copied, setCopied] = useState(false)
  const command = analyzeCommand(month)

  async function copy() {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
    } catch {
      setCopied(false) // no clipboard: the command stays in view to be copied by hand
    }
  }

  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
      <span>{t('summary.insight.noReading')}</span>
      <button
        type="button"
        onClick={copy}
        aria-label={t('summary.insight.copyCommandLabel', { command })}
        className={cn(
          'relative rounded-sm font-semibold text-primary hover:text-secondary-foreground',
          'before:absolute before:-inset-x-1 before:-inset-y-3 before:content-[""]',
          FOCUS,
        )}
      >
        {copied ? t('summary.insight.copied') : t('summary.insight.copy')}
      </button>
      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12px] text-foreground">
        {command}
      </code>
      <ClaudeButton month={month} label={monthTitle(month)} selection={selection} className="ml-auto" />
    </p>
  )
}
