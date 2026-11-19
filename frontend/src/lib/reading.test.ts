import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { activeTab, changesNote, neighborTab, readingTabs } from './reading'

describe('readingTabs', () => {
  it('only the tabs with content, in a fixed order', () => {
    expect(readingTabs({ insight: true, whatHappened: true, changes: true })).toEqual([
      'insight',
      'what-happened',
      'changes',
    ])
    expect(readingTabs({ insight: false, whatHappened: true, changes: true })).toEqual([
      'what-happened',
      'changes',
    ])
    expect(readingTabs({ insight: true, whatHappened: false, changes: false })).toEqual(['insight'])
  })

  it('with nothing to read there are no tabs', () => {
    expect(readingTabs({ insight: false, whatHappened: false, changes: false })).toEqual([])
  })
})

describe('activeTab', () => {
  it('keeps the chosen one if it remains; otherwise the first', () => {
    expect(activeTab(['insight', 'changes'], 'changes')).toBe('changes')
    expect(activeTab(['insight', 'changes'], 'what-happened')).toBe('insight')
    expect(activeTab(['changes'], null)).toBe('changes')
    expect(activeTab([], 'insight')).toBeNull()
  })
})

describe('neighborTab', () => {
  it('the arrows walk through the tabs and wrap around', () => {
    const tabs = ['insight', 'what-happened', 'changes'] as const
    expect(neighborTab(tabs, 'insight', 1)).toBe('what-happened')
    expect(neighborTab(tabs, 'changes', 1)).toBe('insight')
    expect(neighborTab(tabs, 'insight', -1)).toBe('changes')
  })
})

describe('changesNote', () => {
  it('without changes it says why; with changes, nothing', () => {
    expect(changesNote(2, false, true)).toBeNull()
    expect(changesNote(0, true, false)).toBe(t('summary.reading.changes.partial'))
    expect(changesNote(0, false, false)).toBe(t('summary.reading.changes.notComparable'))
    expect(changesNote(0, false, true)).toBe(t('summary.reading.changes.withinUsual'))
  })
})
