import { useId, useState, type PointerEvent } from 'react'
import { t } from '@/i18n'
import { shortDay } from '@/lib/months'
import { cn } from '@/lib/utils'

export interface ChartPoint {
  day: string // ISO
  value: number // cents
}

interface BalanceChartProps {
  points: readonly ChartPoint[]
  format: (cents: number) => string
  /** Index of the first projected point: from there on the line is dashed (a loan's future). */
  projectedFrom?: number
  /** How many first points are estimated: up to there the line is dashed (net worth before an
   * account's first statement). */
  estimatedUntil?: number
  /** Line colour (a CSS colour); the app's primary by default. */
  tone?: string
  className?: string
  /** ISO day shown as «Hoy» in the reading (and read by default when there is a projection). */
  today?: string
}

const WIDTH = 600
const HEIGHT = 150
const PAD = 6

function scale(points: readonly ChartPoint[]): (p: ChartPoint, i: number) => [number, number] {
  const values = points.map((p) => p.value)
  const low = Math.min(...values)
  const high = Math.max(...values)
  const span = high - low || 1
  const step = points.length > 1 ? (WIDTH - PAD * 2) / (points.length - 1) : 0
  return (p, i) => [PAD + i * step, PAD + (1 - (p.value - low) / span) * (HEIGHT - PAD * 2)]
}

function path(xy: readonly [number, number][]): string {
  return xy.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
}

/** A balance over time: an area under a line, the projection dashed; pointing at it reads the
 * nearest point above the chart. Needs two points at least. */
export function BalanceChart({
  points,
  format,
  projectedFrom,
  estimatedUntil = 0,
  tone = 'var(--primary)',
  className,
  today,
}: BalanceChartProps) {
  const gradient = useId()
  const [active, setActive] = useState<number | null>(null)
  if (points.length < 2) return null
  const place = scale(points)
  const xy = points.map(place)
  const split = projectedFrom === undefined ? xy.length : Math.max(1, projectedFrom)
  const start = Math.min(Math.max(0, estimatedUntil), split - 1) // first solid point
  const early = start > 0 ? xy.slice(0, start + 1) : []
  const solid = xy.slice(start, split)
  const dashed = split < xy.length ? xy.slice(split - 1) : []
  const known = xy.slice(0, split)
  const area = `${path(known)} L${known[known.length - 1][0]},${HEIGHT} L${known[0][0]},${HEIGHT} Z`
  const shown = active ?? (projectedFrom === undefined ? points.length - 1 : split - 1)
  const first = points[0]
  const last = points[points.length - 1]

  function point(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = (event.clientX - box.left) / box.width
    setActive(Math.round(Math.min(1, Math.max(0, ratio)) * (points.length - 1)))
  }

  return (
    <figure className={cn('flex flex-col gap-1.5', className)}>
      <figcaption className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground tabular-nums">
        <span>
          {points[shown].day === today ? t('accounts.chart.today') : shortDay(points[shown].day)}
          {projectedFrom !== undefined && shown >= split && ` · ${t('accounts.chart.projection')}`}
          {shown < estimatedUntil && ` · ${t('accounts.chart.estimated')}`}
        </span>
        <span className="font-semibold text-foreground">{format(points[shown].value)}</span>
      </figcaption>
      <svg
        role="img"
        aria-label={t('accounts.chart.label', {
          first: `${format(first.value)} (${shortDay(first.day)})`,
          last: `${format(last.value)} (${shortDay(last.day)})`,
        })}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="h-[120px] w-full touch-pan-y sm:h-[150px]"
        onPointerMove={point}
        onPointerDown={point}
        onPointerLeave={() => setActive(null)}
      >
        <defs>
          <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={tone} stopOpacity="0.18" />
            <stop offset="100%" stopColor={tone} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradient})`} />
        <path d={path(solid)} fill="none" stroke={tone} strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
        {early.length > 1 && <Dashed xy={early} tone={tone} />}
        {dashed.length > 1 && <Dashed xy={dashed} tone={tone} />}
        <line
          x1={xy[shown][0]}
          x2={xy[shown][0]}
          y1={0}
          y2={HEIGHT}
          stroke="currentColor"
          className="text-border"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </figure>
  )
}

function Dashed({ xy, tone }: { xy: readonly [number, number][]; tone: string }) {
  return (
    <path
      d={path(xy)}
      fill="none"
      stroke={tone}
      strokeOpacity="0.55"
      strokeWidth="2"
      strokeDasharray="6 6"
      vectorEffect="non-scaling-stroke"
    />
  )
}
