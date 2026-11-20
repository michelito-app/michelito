// Small pieces shared by the Shared screens: avatar, back button, the "⋯" menu, chips and the
// balance colors.
import { ArrowLeft, Ellipsis } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { initials } from '@/lib/ledger'
import { cn } from '@/lib/utils'
import { CHIP, CHIP_OFF, CHIP_ON, LIST_CARD, ROW_BUTTON } from './styles'

export function Avatar({ name, me = false }: { name: string; me?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'flex size-10 shrink-0 items-center justify-center rounded-full text-[14px] font-bold',
        me ? 'bg-primary text-primary-foreground' : 'bg-secondary text-secondary-foreground',
      )}
    >
      {initials(name)}
    </span>
  )
}

/** "‹ Back": back to where the user came from inside the app, else to `fallback`. */
export function BackButton({ fallback }: { fallback: string }) {
  const navigate = useNavigate()
  const location = useLocation()
  const inApp = (location.state as { from?: unknown } | null)?.from !== undefined
  return (
    <button
      type="button"
      onClick={() => (inApp ? navigate(-1) : navigate(fallback))}
      className={cn(
        '-ml-2 inline-flex min-h-11 items-center gap-1.5 self-start rounded-xl px-2 text-[15px] font-semibold text-primary hover:bg-muted',
        FOCUS,
      )}
    >
      <ArrowLeft size={18} aria-hidden="true" />
      {t('shared.back')}
    </button>
  )
}

/** The "⋯" button that opens a screen's menu sheet. */
export function MenuButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-haspopup="dialog"
      onClick={onClick}
      className={cn(
        'flex size-11 shrink-0 items-center justify-center rounded-xl text-ink-2 hover:bg-muted',
        FOCUS,
      )}
    >
      <Ellipsis size={20} aria-hidden="true" />
    </button>
  )
}

/** A screen's h1: it takes focus on arrival, so a screen reader announces the route change. */
export function PageTitle({ children, className }: { children: ReactNode; className?: string }) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [])
  return (
    <h1
      ref={heading}
      tabIndex={-1}
      className={cn(
        'min-w-0 text-[26px] leading-tight font-bold tracking-[-0.02em] break-words outline-none',
        className,
      )}
    >
      {children}
    </h1>
  )
}

/** A list in a menu sheet: one 48 px row per action. */
export function MenuList({ children }: { children: ReactNode }) {
  return <ul className={LIST_CARD}>{children}</ul>
}

export function MenuItem({
  icon,
  onClick,
  children,
}: {
  icon: ReactNode
  onClick: () => void
  children: string
}) {
  return (
    <li>
      <button type="button" onClick={onClick} className={cn(ROW_BUTTON, 'min-h-12 text-sm font-medium')}>
        <span className="shrink-0 text-muted-foreground">{icon}</span>
        <span className="min-w-0 flex-1">{children}</span>
      </button>
    </li>
  )
}

/** The same row in the menu that the person, the group, the row… is about: a toggle chip. */
export function Chip({
  on,
  onClick,
  children,
  label,
}: {
  on: boolean
  onClick: () => void
  children: ReactNode
  label?: string
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={label}
      onClick={onClick}
      className={cn(CHIP, on ? CHIP_ON : CHIP_OFF)}
    >
      <span className="truncate">{children}</span>
    </button>
  )
}
