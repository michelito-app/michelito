import { type KeyboardEvent, type ReactNode, useId, useLayoutEffect, useRef, useState } from 'react'
import { ClaudeButton } from '@/components/claude/ClaudeButton'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import { hasWhatHappened } from '@/lib/anomalies'
import type { Change, Contribution, MonthTotal } from '@/lib/api'
import { useInsight } from '@/lib/queries'
import {
  activeTab,
  changesNote,
  neighborTab,
  READING_LABELS,
  type ReadingTab,
  readingTabs,
} from '@/lib/reading'
import { cn } from '@/lib/utils'
import { Changes } from './Changes'
import { InsightBody, NoReading } from './InsightCard'
import { FOCUS, PANEL, PANEL_TITLE } from './styles'
import { WhatHappened } from './WhatHappened'

interface MonthReadingProps {
  month: string
  /** The month chosen in the trend (with its atypical-month flags). */
  point: MonthTotal | undefined
  whatHappened: Contribution[]
  changes: Change[]
  /** Month in progress: not compared yet. */
  partial: boolean
  /** There is a usual to compare with (some earlier complete month). */
  comparable: boolean
  selection: Selection
}

const ONE_LINE = cn(PANEL, 'flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3.5 sm:px-6')
const SMALL_TITLE = 'text-[15px] font-[650] tracking-tight'

/** "Month reading": the saved analysis, "What happened" and "What changed" as tabs (only those
 * with something), folded to about three lines with "Read more". With nothing, one line with the
 * command to ask for the analysis. When "What changed" has nothing, a note says why. */
export function MonthReading(props: MonthReadingProps) {
  const { month, point, whatHappened, changes, partial, comparable, selection } = props
  const insight = useInsight(month)
  const tabs = readingTabs({
    insight: Boolean(insight.data),
    whatHappened: hasWhatHappened(point, whatHappened),
    changes: changes.length > 0,
  })
  const [chosen, setChosen] = useState<ReadingTab | null>(null)
  const current = activeTab(tabs, chosen)
  const ids = useId()
  const note = changesNote(changes.length, partial, comparable)
  const failed = insight.isError && (
    <p role="alert" className="text-[13px] text-muted-foreground">
      {t('summary.reading.loadError')}{' '}
      <button
        type="button"
        onClick={() => insight.refetch()}
        className={cn(
          'relative rounded-sm font-semibold text-primary hover:text-secondary-foreground',
          'before:absolute before:-inset-x-1 before:-inset-y-3 before:content-[""]',
          FOCUS,
        )}
      >
        {t('summary.reading.retry')}
      </button>
    </p>
  )

  if (current === null) {
    return (
      <section aria-labelledby={`${ids}-title`} aria-busy={insight.isPending} className={ONE_LINE}>
        <h2 id={`${ids}-title`} className={SMALL_TITLE}>
          {t('summary.reading.title')}
        </h2>
        {/* While the analysis loads, asking for it is not offered, but the line keeps its place. */}
        {insight.isPending ? (
          <Skeleton className="h-5 w-72 max-w-full" />
        ) : (
          (failed || <NoReading month={month} selection={selection} />)
        )}
        {note && <p className="w-full text-[13px] text-muted-foreground">{note}</p>}
      </section>
    )
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (current === null) return
    const next =
      event.key === 'ArrowRight'
        ? neighborTab(tabs, current, 1)
        : event.key === 'ArrowLeft'
          ? neighborTab(tabs, current, -1)
          : event.key === 'Home'
            ? tabs[0]
            : event.key === 'End'
              ? tabs[tabs.length - 1]
              : null
    if (next === null) return
    event.preventDefault()
    setChosen(next)
    document.getElementById(`${ids}-tab-${next}`)?.focus()
  }

  return (
    <section aria-labelledby={`${ids}-title`} className={cn(PANEL, 'flex flex-col gap-3 px-4 py-4 sm:px-6')}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 id={`${ids}-title`} className={PANEL_TITLE}>
          {t('summary.reading.title')}
        </h2>
        <div role="tablist" aria-label={t('summary.reading.title')} onKeyDown={onKeyDown} className="-my-1 flex flex-wrap gap-1">
          {tabs.map((tab) => {
            const selected = tab === current
            return (
              <button
                key={tab}
                id={`${ids}-tab-${tab}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`${ids}-panel`}
                tabIndex={selected ? 0 : -1}
                onClick={() => setChosen(tab)}
                className={cn(
                  'min-h-11 rounded-lg px-3 text-[13px] font-semibold transition-colors sm:min-h-9',
                  selected ? 'bg-secondary text-secondary-foreground' : 'text-muted-foreground hover:bg-muted',
                  FOCUS,
                )}
              >
                {READING_LABELS[tab]}
              </button>
            )
          })}
        </div>
      </div>
      {/* "What changed" has no links: the panel itself takes the focus to be read. */}
      <div
        id={`${ids}-panel`}
        role="tabpanel"
        aria-labelledby={`${ids}-tab-${current}`}
        tabIndex={current === 'changes' ? 0 : undefined}
        className={cn('rounded-md', FOCUS)}
      >
        <Foldable key={current}>
          {current === 'insight' && insight.data && <InsightBody insight={insight.data} />}
          {current === 'what-happened' && point && (
            <WhatHappened point={point} items={whatHappened} selection={selection} />
          )}
          {current === 'changes' && <Changes changes={changes} />}
        </Foldable>
      </div>
      {current === 'insight' && insight.data && (
        <ClaudeButton month={month} label={insight.data.label} selection={selection} className="self-start" />
      )}
      {failed}
      {note && <p className="text-[13px] text-muted-foreground">{note}</p>}
    </section>
  )
}

/** Folded height: about three lines of text. */
const FOLDED = 'max-h-[4.75rem]'

/** Folded content with "Read more" only when it really does not fit. */
function Foldable({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [overflows, setOverflows] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const body = useId()

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const measure = () => setOverflows(el.scrollHeight > el.clientHeight + 1)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [open])

  const folded = !open && overflows
  return (
    <div className="flex flex-col gap-1.5">
      <div
        id={body}
        ref={box}
        // Folded content is not skipped by the keyboard: when the focus enters, it opens.
        onFocus={() => {
          if (!open && overflows) setOpen(true)
        }}
        className={cn(
          'relative',
          !open && [FOLDED, 'overflow-hidden'],
          // It fades out downwards so it shows that it continues.
          folded &&
            'after:pointer-events-none after:absolute after:inset-x-0 after:bottom-0 after:h-8 after:bg-gradient-to-b after:from-transparent after:to-card after:content-[""]',
        )}
      >
        {children}
      </div>
      {(open || overflows) && (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={body}
          onClick={() => setOpen((value) => !value)}
          className={cn(
            'relative self-start rounded-sm text-sm font-semibold text-primary hover:text-secondary-foreground',
            'before:absolute before:-inset-x-2 before:-inset-y-3 before:content-[""]',
            FOCUS,
          )}
        >
          {open ? t('summary.reading.readLess') : t('summary.reading.readMore')}
        </button>
      )}
    </div>
  )
}
