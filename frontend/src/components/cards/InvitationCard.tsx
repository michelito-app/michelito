import { ArrowRight, X } from 'lucide-react'
import { Link } from 'react-router'
import { t } from '@/i18n'
import type { Invitation } from '@/lib/home'
import { cn } from '@/lib/utils'
import { CARD } from './Card'

const TEXT: Record<Invitation, { text: string; action: string }> = {
  budget: { text: t('home.invite.budget.text'), action: t('home.invite.budget.action') },
  recurring: { text: t('home.invite.recurring.text'), action: t('home.invite.recurring.action') },
  shared: { text: t('home.invite.shared.text'), action: t('home.invite.shared.action') },
}

interface InvitationCardProps {
  kind: Invitation
  href: string
  onDismiss: () => void
}

/** A card that does not apply yet, as a compact invitation: one line and its action (the whole
 * card is the link); «×» dismisses it for good in this browser. */
export function InvitationCard({ kind, href, onDismiss }: InvitationCardProps) {
  const { text, action } = TEXT[kind]
  return (
    <section
      data-card={`invite-${kind}`}
      data-invitation={kind}
      aria-label={text}
      className={cn(
        CARD,
        'flex-row items-center gap-2 py-3 pr-2 transition-transform has-[a:active]:scale-[0.98] has-[a:focus-visible]:ring-3 has-[a:focus-visible]:ring-ring/50',
      )}
    >
      <Link
        to={href}
        className="flex min-h-11 min-w-0 flex-1 flex-col justify-center gap-0.5 text-foreground no-underline outline-none after:absolute after:inset-0 after:z-[1] after:rounded-[20px] after:content-['']"
      >
        <span className="text-[13.5px] leading-snug">{text}</span>
        <span className="inline-flex items-center gap-1 text-[13px] font-semibold text-primary">
          {action}
          <ArrowRight size={14} aria-hidden="true" />
        </span>
      </Link>
      <button
        type="button"
        aria-label={t('home.invite.dismiss', { text })}
        onClick={onDismiss}
        className="relative z-[2] flex size-11 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <X size={18} aria-hidden="true" />
      </button>
    </section>
  )
}
