import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { cn } from '@/lib/utils'

/** White borderless card: 20 px corners and a soft shadow on the grey page. */
export const CARD =
  'relative flex min-w-0 flex-col gap-3 rounded-[20px] bg-card p-5 shadow-[0_1px_2px_rgba(27,29,33,0.05),0_6px_20px_rgba(27,29,33,0.06)]'
/** Big figures: tabular, tight. */
export const FIGURE = 'font-bold tracking-[-0.02em] tabular-nums whitespace-nowrap'
/** Something inside a pressable card that has its own destination: above the card's link. */
export const ABOVE = 'relative z-[2]'
/** A link inside a card (a row): 44 px tall, its own focus ring. */
export const ROW_LINK =
  'relative z-[2] -mx-2 flex min-h-11 items-center gap-3 rounded-xl px-2 text-foreground no-underline outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50'

const TITLE = 'inline-flex items-center gap-0.5 text-[13px] font-medium text-muted-foreground'

// The card's link covers the whole card (its ::after), so tapping anywhere on it navigates; the
// card shrinks a little while pressed and shows the focus ring of its link.
const PRESSABLE =
  'transition-transform duration-100 has-[a[data-card-link]:active]:scale-[0.98] has-[a[data-card-link]:focus-visible]:ring-3 has-[a[data-card-link]:focus-visible]:ring-ring/50'
const STRETCHED =
  'outline-none after:absolute after:inset-0 after:z-[1] after:rounded-[20px] after:content-[""]'

interface CardProps {
  /** Stable id: `data-card`, for the order list and the tests. */
  id: string
  title: string
  /** Where the whole card leads; without it only the rows inside navigate. */
  href?: string
  /** Where the title leads when the card is not pressable as a whole (rows inside are links). */
  titleHref?: string
  /** Accessible name of the card's link (by default, the title). */
  label?: string
  className?: string
  children: ReactNode
}

/** A Summary card: a small grey title with «›» and the content. With `href` the whole card is
 * one link; with `titleHref` only the title (its rows lead elsewhere). */
export function Card({ id, title, href, titleHref, label, className, children }: CardProps) {
  const headingId = `card-${id}-title`
  const chevron = <ChevronRight size={14} strokeWidth={2.4} aria-hidden="true" className="mt-px" />
  return (
    <section
      data-card={id}
      aria-labelledby={headingId}
      className={cn(CARD, href && PRESSABLE, className)}
    >
      <h2 id={headingId} className="-my-1 flex min-h-6 items-center">
        {href ? (
          <Link to={href} data-card-link="" aria-label={label} className={cn(TITLE, STRETCHED)}>
            {title}
            {chevron}
          </Link>
        ) : titleHref ? (
          <Link
            to={titleHref}
            aria-label={label}
            className={cn(
              TITLE,
              'relative z-[2] -mx-2 -my-2.5 min-h-11 rounded-lg px-2 outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50',
            )}
          >
            {title}
            {chevron}
          </Link>
        ) : (
          <span className={TITLE}>{title}</span>
        )}
      </h2>
      {children}
    </section>
  )
}
