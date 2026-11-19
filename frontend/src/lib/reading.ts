// The Summary's "Month reading" card (pure logic): which tabs it carries.
import { t } from '@/i18n'

export type ReadingTab = 'insight' | 'what-happened' | 'changes'

export const READING_LABELS: Record<ReadingTab, string> = {
  insight: t('summary.reading.tab.insight'),
  'what-happened': t('summary.reading.tab.whatHappened'),
  changes: t('summary.reading.tab.changes'),
}

export interface ReadingContent {
  /** There is a saved analysis of the month. */
  insight: boolean
  /** The month is atypical and there are merchants that explain it. */
  whatHappened: boolean
  /** Some category departed from the usual. */
  changes: boolean
}

/** The tabs with content, in a fixed order; empty when there is nothing to read. */
export function readingTabs(content: ReadingContent): ReadingTab[] {
  const tabs: [ReadingTab, boolean][] = [
    ['insight', content.insight],
    ['what-happened', content.whatHappened],
    ['changes', content.changes],
  ]
  return tabs.filter(([, has]) => has).map(([tab]) => tab)
}

/** The chosen tab if it is still available; otherwise the first (or null without tabs). */
export function activeTab(tabs: readonly ReadingTab[], chosen: ReadingTab | null): ReadingTab | null {
  if (chosen !== null && tabs.includes(chosen)) return chosen
  return tabs[0] ?? null
}

/** Neighbouring tab with the arrow keys (wraps around at the ends). */
export function neighborTab(tabs: readonly ReadingTab[], current: ReadingTab, step: 1 | -1): ReadingTab {
  const at = tabs.indexOf(current)
  if (at < 0) return tabs[0] ?? current
  return tabs[(at + step + tabs.length) % tabs.length]
}

/** Why "What changed" has nothing this month; null when there are changes. */
export function changesNote(changes: number, partial: boolean, comparable: boolean): string | null {
  if (changes > 0) return null
  if (partial) return t('summary.reading.changes.partial')
  if (!comparable) return t('summary.reading.changes.notComparable')
  return t('summary.reading.changes.withinUsual')
}
