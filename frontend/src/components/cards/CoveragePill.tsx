import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { t } from '@/i18n'
import type { Coverage } from '@/lib/api'
import { coveragePill } from '@/lib/home'
import { coverageText } from '@/lib/summary'
import { cn } from '@/lib/utils'

interface CoveragePillProps {
  coverage: readonly Coverage[]
  /** Which days and accounts the month covers (the line the other month screens show). */
  scope: string
}

/** One pill for the month's coverage ("in progress · 2 of 4 accounts closed"); tapping it opens
 * a sheet with the month's scope and each account. */
export function CoveragePill({ coverage, scope }: CoveragePillProps) {
  const [open, setOpen] = useState(false)
  const text = coveragePill(coverage)
  if (text === null) return null
  const complete = coverage.every((c) => c.complete)
  return (
    <>
      <button
        type="button"
        data-testid="coverage-pill"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        className="inline-flex min-h-11 items-center gap-2 self-start rounded-full bg-card px-4 text-[13px] font-medium text-ink-2 shadow-[0_1px_2px_rgba(27,29,33,0.05),0_4px_12px_rgba(27,29,33,0.05)] outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span
          aria-hidden="true"
          className={cn('size-2 rounded-full', complete ? 'bg-primary' : 'bg-[#C9A227]')}
        />
        {text}
        <ChevronRight size={14} aria-hidden="true" className="text-muted-foreground" />
      </button>
      {open && (
        <BottomSheet title={t('home.coverage.sheetTitle')} onClose={() => setOpen(false)}>
          <p data-testid="coverage-scope" className="text-[13px] text-ink-2">
            {scope}
          </p>
          <ul aria-label={t('summary.coverage.label')} className="flex flex-col">
            {coverage.map((c) => (
              <li
                key={c.key}
                className="flex min-h-11 items-center justify-between gap-3 border-b border-[#F2F2EE] text-[14px] last:border-b-0"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={cn('size-2 shrink-0 rounded-full', c.complete ? 'bg-primary' : 'bg-[#C9A227]')}
                  />
                  <span className="truncate">{c.label}</span>
                </span>
                <span className="shrink-0 text-ink-2">{coverageText(c)}</span>
              </li>
            ))}
          </ul>
          {!complete && (
            <p className="text-[13px] text-muted-foreground">{t('home.coverage.sheetNote')}</p>
          )}
        </BottomSheet>
      )}
    </>
  )
}
