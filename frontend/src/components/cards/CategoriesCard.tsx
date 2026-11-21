import { Link, useNavigate } from 'react-router'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import type { CategoryLine } from '@/lib/api'
import { monthSpendingHref, type Slice, sliceHref, slices } from '@/lib/home'
import { formatDop } from '@/lib/money'
import { Card, ROW_LINK } from './Card'

interface CategoriesCardProps {
  month: string
  categories: readonly CategoryLine[]
  selection: Selection
}

const RADIUS = 40
const STROKE = 16
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

/** «Categories»: a donut with the top five and «Others»; each slice and each legend row opens
 * the month's expenses of that category. */
export function CategoriesCard({ month, categories, selection }: CategoriesCardProps) {
  const navigate = useNavigate()
  const parts = slices(categories)
  return (
    <Card
      id="categories"
      title={t('home.categories.title')}
      titleHref={monthSpendingHref(month, selection)}
    >
      {parts.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('home.categories.none')}</p>
      ) : (
        <div className="@container"><div className="flex flex-col items-center gap-3 @xl:flex-row @xl:gap-10 @xl:px-6">
          <svg
            viewBox="0 0 100 100"
            aria-hidden="true"
            className="relative z-[2] size-[132px] shrink-0 -rotate-90"
          >
            {arcs(parts).map(({ slice, offset, length }) => (
              <circle
                key={slice.key}
                data-slice={slice.label}
                cx="50"
                cy="50"
                r={RADIUS}
                fill="none"
                stroke={slice.color}
                strokeWidth={STROKE}
                strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
                strokeDashoffset={-offset}
                className="cursor-pointer transition-opacity hover:opacity-80"
                onClick={() => navigate(sliceHref(slice, month, selection))}
              />
            ))}
          </svg>
          <ul className="flex w-full min-w-0 flex-col">
            {parts.map((slice) => (
              <li key={slice.key}>
                <Link
                  to={sliceHref(slice, month, selection)}
                  aria-label={t('home.categories.slice', {
                    category: slice.label,
                    amount: formatDop(slice.cents),
                  })}
                  className={ROW_LINK}
                >
                  <span
                    aria-hidden="true"
                    className="size-2.5 shrink-0 rounded-full"
                    style={{ background: slice.color }}
                  />
                  <span className="min-w-0 flex-1 truncate text-[13.5px]">{slice.label}</span>
                  <span className="shrink-0 text-[13.5px] font-semibold whitespace-nowrap tabular-nums">
                    {formatDop(slice.cents).replace('RD$ ', 'RD$ ')}
                  </span>
                  <span className="w-9 shrink-0 text-right text-[12px] text-muted-foreground tabular-nums">
                    {t('home.categories.percent', { percent: Math.round(slice.share * 100) })}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div></div>
      )}
    </Card>
  )
}

interface Arc {
  slice: Slice
  offset: number
  length: number
}

/** Where each slice starts and how long it is along the circle (a hairline gap between them). */
function arcs(parts: readonly Slice[]): Arc[] {
  const gap = parts.length > 1 ? 0.8 : 0
  let start = 0
  return parts.map((slice) => {
    const full = slice.share * CIRCUMFERENCE
    const arc = { slice, offset: start, length: Math.max(full - gap, 0.5) }
    start += full
    return arc
  })
}
