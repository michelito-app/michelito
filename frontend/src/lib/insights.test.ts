import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { longDay } from './months'
import type { Insight, MonthOption } from './api'
import {
  analyzeCommand,
  canSave,
  insightPath,
  markdownBlocks,
  monthsWithout,
  remaining,
  savedText,
  TEXT_MAX,
} from './insights'

const INSIGHT: Insight = {
  month: '2026-02',
  label: 'February 2026',
  text: 'Big trip.',
  accounts: null,
  created_at: '2026-03-02T10:00:00+00:00',
  updated_at: '2026-03-02T10:00:00+00:00',
  stale: false,
}

const MONTHS: MonthOption[] = [
  { month: '2026-02', label: 'February 2026', partial: true },
  { month: '2026-01', label: 'January 2026', partial: false },
]

describe('saved analyses', () => {
  it('the command to analyse a month', () => {
    expect(analyzeCommand('2026-01')).toBe('michelito analysis 2026-01')
  })

  it('the months without an analysis, in the API order', () => {
    expect(monthsWithout([INSIGHT], MONTHS).map((m) => m.month)).toEqual(['2026-01'])
    expect(monthsWithout([], MONTHS)).toHaveLength(2)
  })

  it('when it was saved or edited', () => {
    expect(savedText(INSIGHT)).toBe(
      t('reports.insight.saved', { day: longDay('2026-03-02'), year: '2026' }),
    )
    expect(savedText({ ...INSIGHT, updated_at: '2026-03-05T09:00:00+00:00' })).toBe(
      t('reports.insight.edited', { day: longDay('2026-03-05'), year: '2026' }),
    )
  })

  it('4000-character limit, not counting the spaces at the edges', () => {
    expect(remaining('  word  ')).toBe(TEXT_MAX - 4)
    expect(canSave('   ')).toBe(false)
    expect(canSave('x'.repeat(TEXT_MAX))).toBe(true)
    expect(canSave('x'.repeat(TEXT_MAX + 1))).toBe(false)
  })

  it('simple Markdown into text blocks (no HTML)', () => {
    const text = '## February\n\nI spent **more** than\nusual.\n\n- Trip `big`\n- Streaming\n1. One\n<b>x</b>'
    expect(markdownBlocks(text)).toEqual([
      { kind: 'heading', text: 'February' },
      { kind: 'paragraph', text: 'I spent more than usual.' },
      { kind: 'list', items: ['Trip big', 'Streaming', 'One'] },
      { kind: 'paragraph', text: '<b>x</b>' },
    ])
    expect(markdownBlocks('   ')).toEqual([])
  })

  it('API path', () => {
    expect(insightPath('2026-02')).toBe('/api/insights/2026-02')
  })
})
