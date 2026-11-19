import { MessageSquare, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { FeedbackDialog } from '@/components/demo/FeedbackDialog'
import { RestartDialog } from '@/components/demo/RestartDialog'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { useMode } from '@/lib/demo'
import { cn } from '@/lib/utils'

/** The demo's sticky header: the notice, the repo link, "Start over" and "Feedback" (44 px). It
 * sits in the page flow (stuck to the top when scrolling), so it does not cover content on a
 * phone. */
export function DemoBanner() {
  const mode = useMode()
  const [open, setOpen] = useState<'feedback' | 'restart' | null>(null)
  return (
    <header
      aria-label={t('demo.banner.label')}
      className="sticky top-0 z-20 flex w-full flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-secondary px-4 py-1 text-[13px] text-secondary-foreground"
    >
      <p className="min-w-0 flex-[1_1_220px] py-2">
        {mode.notice ?? t('demo.banner.notice')}
        {mode.repo && (
          <>
            {' · '}
            <a href={mode.repo} className="font-semibold underline" rel="noreferrer">
              {t('demo.banner.openSource')}
            </a>
          </>
        )}
      </p>
      <button
        type="button"
        onClick={() => setOpen('restart')}
        className={cn(
          'inline-flex min-h-11 shrink-0 items-center gap-2 rounded-[10px] px-3 text-sm font-semibold hover:bg-muted/70',
          FOCUS,
        )}
      >
        <RotateCcw size={16} aria-hidden="true" />
        {t('demo.banner.restart')}
      </button>
      <button
        type="button"
        onClick={() => setOpen('feedback')}
        className={cn(
          'inline-flex min-h-11 shrink-0 items-center gap-2 rounded-[10px] bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/85',
          FOCUS,
        )}
      >
        <MessageSquare size={16} aria-hidden="true" />
        {t('demo.banner.feedback')}
      </button>
      {open === 'feedback' && <FeedbackDialog onClose={() => setOpen(null)} />}
      {open === 'restart' && <RestartDialog onClose={() => setOpen(null)} />}
    </header>
  )
}
