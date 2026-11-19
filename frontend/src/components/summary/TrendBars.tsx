import { type RefObject, useLayoutEffect, useRef, useState } from 'react'
import { t } from '@/i18n'
import type { MonthTotal } from '@/lib/api'
import { formatDop } from '@/lib/money'
import {
  ATYPICAL_LEGEND,
  atypicalNote,
  type FlagMark,
  flagDeviation,
  flagMarks,
  hasAtypical,
} from '@/lib/anomalies'
import { barStyle, FLOW_COLORS, type SeriesColor, TONE_COLORS } from '@/lib/colors'
import { monthPhrase } from '@/lib/months'
import { barWidth, trendIncomeNote, trendSummary } from '@/lib/summary'
import { cn } from '@/lib/utils'
import { FOCUS, PANEL, PANEL_TITLE } from './styles'

/** Colours per series (see lib/colors): the chosen month goes in the strong colour; the others
 * and the months in progress, in the light one. Income always goes left of spending. */
const SERIES = {
  income: { label: t('summary.kpi.income'), ...FLOW_COLORS.income },
  spent: { label: t('summary.kpi.spending'), ...FLOW_COLORS.expense },
} as const

interface TrendBarsProps {
  trend: MonthTotal[]
  month: string
  /** Opens that month in the Summary when its column is tapped. */
  onSelect?: (month: string) => void
}

function Swatch({ color }: { color: string }) {
  return (
    <span aria-hidden="true" className="size-2 shrink-0 rounded-[3px]" style={{ background: color }} />
  )
}

/** Accessible name of a month's column: the same as the tooltip says. */
function columnLabel(point: MonthTotal, selected: boolean): string {
  const parts = [
    point.partial
      ? t('summary.trendBars.monthInProgress', { month: monthPhrase(point.month) })
      : monthPhrase(point.month),
    t('summary.trendBars.incomeAmount', { amount: formatDop(point.income_cents) }),
    t('summary.trendBars.spendingAmount', { amount: formatDop(point.total_cents) }),
    ...flagMarks(point).map((mark) => `${mark.words}: ${flagDeviation(point, mark)}`),
  ]
  const label = parts.join(', ')
  return selected
    ? t('summary.trendBars.chosenMonth', { label })
    : t('summary.trendBars.openMonth', { label })
}

/** Year under the label of the first month and of each January, so years are not confused. */
function showsYear(trend: MonthTotal[], index: number): boolean {
  return index === 0 || trend[index].month.endsWith('-01')
}

function Bar({ series, point, month, cents, max }: BarProps) {
  const style = barStyle(series, point, month)
  const height = barWidth(cents, max)
  return (
    <span
      aria-hidden="true"
      className="block max-w-[22px] min-w-0 flex-1 rounded-t-[5px] rounded-b-[2px]"
      style={{
        // A month without spending still shows its column (like the previous chart's minimum).
        height: cents > 0 ? `max(${height}%, 3px)` : series === SERIES.spent ? '3px' : 0,
        background: style.fill,
        boxShadow: style.stroke ? `inset 0 0 0 ${style.strokeWidth}px ${style.stroke}` : undefined,
      }}
    />
  )
}

interface BarProps {
  series: SeriesColor
  point: MonthTotal
  month: string
  cents: number
  max: number
}

const MARK_FONT = '600 11px Inter, ui-sans-serif, system-ui, sans-serif'
let measurer: CanvasRenderingContext2D | null | undefined

/** Width in pixels of `text` in the flags' font (Infinity when it cannot be measured). */
function markWidth(text: string): number {
  measurer ??= document.createElement('canvas').getContext('2d')
  if (!measurer) return Infinity
  measurer.font = MARK_FONT
  return measurer.measureText(text).width
}

/** Width of each chart column, measured (0 until the first measurement). */
function useColumnWidth(list: RefObject<HTMLOListElement | null>, count: number): number {
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = list.current
    if (!el) return
    const measure = () => setWidth(el.clientWidth / Math.max(count, 1))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [list, count])
  return width
}

type MarkLayout = 'line' | 'wrap' | 'glyph'

/** How a flag goes in a `column` px column: on one line if it fits; on two (arrow and first word,
 * then the rest) if it is the month's only flag and fits that way; otherwise only the arrow.
 * Centred in its column and no wider than it, it does not touch the neighbouring month's. */
function markLayout(mark: FlagMark, column: number, alone: boolean): MarkLayout {
  const room = column - 2
  if (room <= 0) return 'glyph'
  if (markWidth(`${mark.glyph} ${mark.words}`) <= room) return 'line'
  const [first, ...rest] = mark.words.split(' ')
  const wraps = Math.max(markWidth(`${mark.glyph} ${first}`), markWidth(rest.join(' '))) <= room
  return alone && wraps ? 'wrap' : 'glyph'
}

/** Atypical-month flags over the bars, one under the other. */
function Marks({ marks, bottom, column }: { marks: FlagMark[]; bottom: number; column: number }) {
  if (marks.length === 0) return null
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute -inset-x-[16%] flex flex-col items-center gap-px text-[11px] leading-tight font-semibold"
      style={{ bottom: `calc(${bottom}% + 4px)` }}
    >
      {marks.map((mark) => {
        const layout = markLayout(mark, column, marks.length === 1)
        return (
          <span
            key={mark.side}
            data-testid="trend-mark"
            className={layout === 'wrap' ? 'text-center' : 'whitespace-nowrap'}
            style={{
              color: mark.worse ? TONE_COLORS.up : TONE_COLORS.down,
              maxWidth: layout === 'wrap' ? column - 2 : undefined,
            }}
          >
            {layout === 'glyph' ? mark.glyph : `${mark.glyph} ${mark.words}`}
          </span>
        )
      })}
    </span>
  )
}

interface TipProps {
  point: MonthTotal
  index: number
  count: number
  /** The chart's container: the detail never leaves it. */
  frame: RefObject<HTMLDivElement | null>
}

const TIP_GAP = 6

function Tip({ point, index, count, frame }: TipProps) {
  const box = useRef<HTMLDivElement>(null)
  // Next to the column, towards the centre of the chart, so it does not cover its bars; if it
  // does not fit, it shifts until it is inside the chart.
  useLayoutEffect(() => {
    const tip = box.current
    const area = frame.current
    if (!tip || !area) return
    const width = area.clientWidth
    const own = tip.offsetWidth
    const toLeft = index >= count / 2
    const wanted = toLeft
      ? (index / count) * width - TIP_GAP - own
      : ((index + 1) / count) * width + TIP_GAP
    tip.style.left = `${Math.max(0, Math.min(wanted, width - own))}px`
    tip.style.visibility = 'visible'
  }, [frame, index, count, point])
  return (
    <div
      ref={box}
      aria-hidden="true"
      data-testid="trend-tip"
      className="pointer-events-none invisible absolute top-0 left-0 z-10 w-max max-w-[min(280px,100%)] rounded-lg border border-border bg-card px-3 py-2 text-[13px] shadow-sm"
    >
      <div className="text-muted-foreground">
        <span className="capitalize">{monthPhrase(point.month)}</span>
        {point.partial && t('summary.trendBars.inProgressSuffix')}
      </div>
      <TipLine color={SERIES.income.strong} label={SERIES.income.label} cents={point.income_cents} />
      <TipLine color={SERIES.spent.strong} label={SERIES.spent.label} cents={point.total_cents} />
      {flagMarks(point).map((mark) => (
        <div
          key={mark.side}
          className="mt-1 font-semibold"
          style={{ color: mark.worse ? TONE_COLORS.up : TONE_COLORS.down }}
        >
          {mark.glyph} {flagDeviation(point, mark)}
        </div>
      ))}
    </div>
  )
}

function TipLine({ color, label, cents }: { color: string; label: string; cents: number }) {
  return (
    <div className="flex items-center gap-2">
      <Swatch color={color} />
      <span className="text-ink-2">{label}</span>
      <span className="ml-auto pl-3 font-semibold tabular-nums">{formatDop(cents)}</span>
    </div>
  )
}

/** Income and spending of the last 12 months, side by side, with the chosen month highlighted.
 * Each month is a button: hovering or focusing it shows the detail; tapping it opens that month. */
export function TrendBars({ trend, month, onSelect }: TrendBarsProps) {
  const [active, setActive] = useState<number | null>(null)
  const frame = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLOListElement>(null)
  const column = useColumnWidth(list, trend.length)
  // A tap focuses and clicks at once: that first click must not close what the focus opened.
  const justFocused = useRef(false)

  function toggle(index: number) {
    if (justFocused.current) {
      justFocused.current = false
      setActive(index)
      return
    }
    setActive((at) => (at === index ? null : index))
  }
  const max = Math.max(0, ...trend.flatMap((p) => [p.total_cents, p.income_cents]))
  const summary = [trendSummary(trend, month), trendIncomeNote(trend, month), atypicalNote(trend)]
    .filter(Boolean)
    .join('. ')
  const shown = active !== null ? trend[active] : undefined
  return (
    <section
      aria-labelledby="trend-title"
      className={cn(PANEL, '@container flex flex-col gap-3 px-4 py-5 sm:px-6')}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="trend-title" className={PANEL_TITLE}>
          {t('summary.trendBars.title')}
        </h2>
        <div className="flex items-center gap-3 text-[13px] text-muted-foreground">
          {Object.values(SERIES).map((s) => (
            <span key={s.label} className="flex items-center gap-1.5">
              <Swatch color={s.strong} />
              {s.label}
            </span>
          ))}
          <span>{t('summary.trendBars.perMonth')}</span>
        </div>
      </div>
      <p className="sr-only">{summary}.</p>
      <div ref={frame} className="relative">
        <ol
          ref={list}
          aria-label={t('summary.trendBars.monthsLabel')}
          className="grid h-[184px] sm:h-[224px]"
          style={{ gridTemplateColumns: `repeat(${Math.max(trend.length, 1)}, minmax(0, 1fr))` }}
        >
          {trend.map((point, index) => {
            const selected = point.month === month
            const top = barWidth(Math.max(point.total_cents, point.income_cents), max)
            return (
              <li key={point.month} className="flex min-w-0">
                <button
                  type="button"
                  aria-label={columnLabel(point, selected)}
                  aria-current={selected ? 'true' : undefined}
                  // On the chosen month, tapping shows or hides the detail (a phone has no mouse
                  // to remove it); on the others, it opens that month.
                  onClick={() => (selected ? toggle(index) : onSelect?.(point.month))}
                  onMouseEnter={() => setActive(index)}
                  onMouseLeave={() => setActive((at) => (at === index ? null : at))}
                  onFocus={() => {
                    justFocused.current = true
                    setActive(index)
                  }}
                  onBlur={() => {
                    justFocused.current = false
                    setActive((at) => (at === index ? null : at))
                  }}
                  className={cn(
                    'flex min-w-0 flex-1 flex-col rounded-lg transition-colors',
                    selected ? 'cursor-default bg-[#F0F0EB]' : 'cursor-pointer hover:bg-muted/60',
                    FOCUS,
                  )}
                >
                  {/* Room is left above for the atypical months' flags. */}
                  <span className="relative mx-[12%] mt-10 flex-1 sm:mt-11">
                    <span className="absolute inset-0 flex items-end justify-center gap-[3px]">
                      <Bar
                        series={SERIES.income}
                        point={point}
                        month={month}
                        cents={point.income_cents}
                        max={max}
                      />
                      <Bar
                        series={SERIES.spent}
                        point={point}
                        month={month}
                        cents={point.total_cents}
                        max={max}
                      />
                    </span>
                    <Marks marks={flagMarks(point)} bottom={top} column={column} />
                  </span>
                  <span
                    className={cn(
                      'flex h-9 flex-col items-center justify-start pt-1.5 text-[11px] leading-tight sm:text-[12px]',
                      selected ? 'font-semibold text-foreground' : 'text-muted-foreground',
                    )}
                  >
                    <span>{point.label}</span>
                    {showsYear(trend, index) && (
                      <span className="text-[10px] text-muted-foreground">{point.month.slice(0, 4)}</span>
                    )}
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
        {shown && active !== null && (
          <Tip point={shown} index={active} count={trend.length} frame={frame} />
        )}
      </div>
      {hasAtypical(trend) && (
        <p className="text-[13px] text-muted-foreground">
          <span aria-hidden="true" className="font-bold text-up">
            ▲▼{' '}
          </span>
          {ATYPICAL_LEGEND}
        </p>
      )}
    </section>
  )
}
