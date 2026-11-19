// Saved month analyses (pure logic). Claude Code writes them from
// `michelito analysis YYYY-MM` and they are saved with `michelito insight save` (see README).
import { t } from '@/i18n'
import type { Insight, MonthOption } from './api'
import { longDay } from './months'

export const TEXT_MAX = 4000

/** The command that prints the month's dossier to analyse it. */
export function analyzeCommand(month: string): string {
  return `michelito analysis ${month}`
}

/** Months with data that have no analysis yet, newest first. */
export function monthsWithout(insights: readonly Insight[], months: readonly MonthOption[]): MonthOption[] {
  const done = new Set(insights.map((i) => i.month))
  return months.filter((m) => !done.has(m.month))
}

/** "Saved on 5 March 2026" (or "Edited on …" when it changed later). */
export function savedText(insight: Insight): string {
  const edited = insight.updated_at.slice(0, 10) !== insight.created_at.slice(0, 10)
  const day = insight.updated_at.slice(0, 10)
  const params = { day: longDay(day), year: day.slice(0, 4) }
  return edited ? t('reports.insight.edited', params) : t('reports.insight.saved', params)
}

export const STALE_NOTE = t('reports.insight.stale')

/** Characters left; negative when over the limit. */
export function remaining(text: string): number {
  return TEXT_MAX - text.trim().length
}

/** Can this text be saved? (not empty and at most TEXT_MAX). */
export function canSave(text: string): boolean {
  const left = remaining(text)
  return text.trim().length > 0 && left >= 0
}

export type Block =
  | { kind: 'heading'; text: string }
  | { kind: 'list'; items: string[] }
  | { kind: 'paragraph'; text: string }

const HEADING = /^#{1,6}\s+(.*)$/
const ITEM = /^\s*(?:[-*+]|\d+[.)])\s+(.*)$/

/** Removes the inline markup that is not shown (**bold**, `code`, _emphasis_). */
function plain(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1').replace(/\b_(.+?)_\b/g, '$1').trim()
}

/** Simple Markdown (headings, lists and paragraphs) into plain-text blocks: it is shown without
 * inserting HTML. Anything else stays as text. */
export function markdownBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: 'paragraph', text: plain(paragraph.join(' ')) })
    paragraph = []
  }
  for (const line of text.split('\n')) {
    const heading = HEADING.exec(line)
    const item = ITEM.exec(line)
    if (line.trim() === '') {
      flush()
    } else if (heading) {
      flush()
      blocks.push({ kind: 'heading', text: plain(heading[1]) })
    } else if (item) {
      flush()
      const last = blocks[blocks.length - 1]
      if (last?.kind === 'list') last.items.push(plain(item[1]))
      else blocks.push({ kind: 'list', items: [plain(item[1])] })
    } else {
      paragraph.push(line.trim())
    }
  }
  flush()
  return blocks
}

/** API path of a month's analysis. */
export function insightPath(month: string): string {
  return `/api/insights/${encodeURIComponent(month)}`
}
