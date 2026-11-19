import { useState } from 'react'
import { Link } from 'react-router'
import { t } from '@/i18n'
import { type Selection, transactionsHref } from '@/lib/accountFilter'
import type { CategoryLine } from '@/lib/api'
import { categoryColor, customColors } from '@/lib/categories'
import { useCategories } from '@/lib/queries'
import { formatDop } from '@/lib/money'
import { barWidth, CATEGORY_LIMIT, categoryDiff, splitTop } from '@/lib/summary'
import { cn } from '@/lib/utils'
import { FOCUS, PANEL, PANEL_TITLE, ROW_DIVIDER, TONE_TEXT } from './styles'

// Narrow: name | amount | difference, with the bar below. From @xl, four columns.
const GRID =
  'grid grid-cols-[minmax(0,1fr)_minmax(11rem,auto)] gap-x-4 @xl:grid-cols-[minmax(160px,2.2fr)_minmax(60px,1.8fr)_112px_176px]'

interface CategoryTableProps {
  month: string
  categories: CategoryLine[]
  selection?: Selection
}

/** The month's categories with bar, amount and difference against the usual: those with the most
 * spending and "See all N" for the rest. */
export function CategoryTable({ month, categories, selection = null }: CategoryTableProps) {
  const [all, setAll] = useState(false)
  const max = Math.max(0, ...categories.map((c) => c.amount_cents))
  const custom = customColors(useCategories().data ?? [])
  // They already come from most to least spending; the colour comes from that position.
  const { shown, rest } = splitTop(categories, CATEGORY_LIMIT, all)
  return (
    <section
      aria-labelledby="cat-title"
      className={cn(PANEL, '@container flex h-full min-w-0 flex-col pt-2 pb-3')}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-4 pt-4 pb-3 sm:px-6">
        <h2 id="cat-title" className={PANEL_TITLE}>
          {t('summary.categories.title')}
        </h2>
        <span className="text-[13px] text-muted-foreground">
          {t('summary.categories.habitualHint')}
        </span>
      </div>
      {categories.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground sm:px-6">{t('summary.categories.empty')}</p>
      ) : (
        <>
          <div
            aria-hidden="true"
            className={cn(
              GRID,
              'hidden border-b border-[#EFEFEA] px-6 py-2 text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase @xl:grid',
            )}
          >
            <span>{t('summary.categories.column.category')}</span>
            <span>{t('summary.categories.column.share')}</span>
            <span className="text-right">{t('summary.categories.column.spent')}</span>
            <span className="text-right">{t('summary.categories.column.versus')}</span>
          </div>
          <ul>
            {shown.map((c, index) => (
              <CategoryRow
                key={c.category}
                line={c}
                color={custom[c.category] ?? categoryColor(index)}
                width={barWidth(c.amount_cents, max)}
                href={transactionsHref({ month, category: c.category }, selection)}
              />
            ))}
          </ul>
          {(all || rest.length > 0) && (
            <button
              type="button"
              aria-expanded={all}
              onClick={() => setAll((value) => !value)}
              className={cn(
                'mx-2 mt-1 flex min-h-11 items-center self-start rounded-md px-2 text-[13px] font-semibold text-primary hover:bg-muted/60 sm:mx-4',
                FOCUS,
              )}
            >
              {all ? t('summary.review.seeLess') : t('summary.categories.seeAll', { count: categories.length })}
            </button>
          )}
        </>
      )}
    </section>
  )
}

interface CategoryRowProps {
  line: CategoryLine
  color: string
  width: number
  href: string
}

function CategoryRow({ line, color, width, href }: CategoryRowProps) {
  const diff = categoryDiff(line)
  return (
    <li className={ROW_DIVIDER}>
      <Link
        to={href}
        className={cn(
          GRID,
          'items-center gap-y-2 px-4 py-3 text-foreground no-underline transition-colors hover:bg-muted/60 sm:px-6 @xl:min-h-12 @xl:py-0',
          FOCUS,
        )}
      >
        <span className="col-start-1 row-start-1 flex min-w-0 items-center gap-2.5 text-sm font-medium">
          <span
            aria-hidden="true"
            className="size-2.5 shrink-0 rounded-[3px]"
            style={{ background: color }}
          />
          <span className="leading-snug break-words">{line.category}</span>
        </span>
        <span
          aria-hidden="true"
          className="col-start-1 row-start-2 h-2 overflow-hidden rounded-full bg-[#F0F0EB] @xl:col-start-2 @xl:row-start-1"
        >
          <span
            className="block h-2 rounded-full"
            style={{ width: `${width}%`, background: color }}
          />
        </span>
        <span className="col-start-2 row-start-1 text-right text-sm font-semibold whitespace-nowrap tabular-nums @xl:col-start-3">
          {formatDop(line.amount_cents)}
        </span>
        <span
          className={cn(
            'col-start-2 row-start-2 text-right text-[13px] font-semibold whitespace-nowrap tabular-nums @xl:col-start-4 @xl:row-start-1',
            TONE_TEXT[diff.tone],
          )}
        >
          {diff.text}
        </span>
      </Link>
    </li>
  )
}
