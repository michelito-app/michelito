import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { cn } from '@/lib/utils'

/** The one primary action: an in-app path (`to`, a router link) or a handler (`onClick`). */
export type EmptyAction = { label: string; to: string } | { label: string; onClick: () => void }

interface EmptyStateProps {
  /** A simple illustration drawn with the theme's colors (`currentColor` and the tokens). */
  icon: ReactNode
  title: string
  /** One sentence: what this view will do for the user. */
  text: string
  /** The one primary action that fills the view. */
  action: EmptyAction
  /** "See how it looks": this view in the demo (an absolute address), when there is one. */
  preview?: string | null
  className?: string
}

const ACTION = 'mt-1 h-11 rounded-xl px-5 text-sm font-semibold'

/** A designed empty view (never a bare "No data"): an icon, one sentence on what the view does
 * and one primary action, plus an optional look at the same view with sample data. */
export function EmptyState({ icon, title, text, action, preview, className }: EmptyStateProps) {
  return (
    <section
      data-empty-state=""
      aria-label={title}
      className={cn(PANEL, 'flex flex-col items-center gap-3 px-6 py-10 text-center', className)}
    >
      <div aria-hidden="true" className="text-primary">
        {icon}
      </div>
      <h2 className="text-[17px] font-[650] tracking-tight">{title}</h2>
      <p className="max-w-sm text-sm text-muted-foreground">{text}</p>
      <div className="flex flex-wrap items-center justify-center gap-2">
        {'to' in action ? (
          <Link
            to={action.to}
            className={cn(
              ACTION,
              'inline-flex items-center bg-primary text-primary-foreground no-underline hover:bg-primary/85',
              FOCUS,
            )}
          >
            {action.label}
          </Link>
        ) : (
          <Button className={ACTION} onClick={action.onClick}>
            {action.label}
          </Button>
        )}
        {preview && (
          <a
            href={preview}
            className={cn(
              'mt-1 inline-flex min-h-11 items-center rounded-xl px-4 text-sm font-semibold text-primary no-underline hover:bg-muted',
              FOCUS,
            )}
          >
            {t('onboarding.empty.preview')}
          </a>
        )}
      </div>
    </section>
  )
}

/** The Shared illustration: two people and a split coin. */
export function SharedIllustration() {
  return (
    <svg width="96" height="72" viewBox="0 0 96 72" fill="none">
      <circle cx="30" cy="22" r="10" fill="var(--secondary)" stroke="currentColor" strokeWidth="2" />
      <circle cx="66" cy="22" r="10" fill="var(--secondary)" stroke="currentColor" strokeWidth="2" />
      <path
        d="M14 56c2-10 9-16 16-16s14 6 16 16M50 56c2-10 9-16 16-16s14 6 16 16"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx="48" cy="50" r="9" fill="var(--card)" stroke="currentColor" strokeWidth="2" />
      <path d="M48 41v18" stroke="currentColor" strokeWidth="2" strokeDasharray="2 2" />
    </svg>
  )
}
