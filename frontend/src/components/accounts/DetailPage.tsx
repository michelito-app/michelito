import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { cn } from '@/lib/utils'

/** An account's or loan's own page: a link back to the list, then its content. */
export function DetailPage({ children }: { children: ReactNode }) {
  return (
    <div data-testid="account-detail" className="flex flex-col gap-5">
      <Link
        to="/accounts"
        aria-label={t('accounts.backLabel')}
        className={cn(
          '-ml-2 inline-flex min-h-11 w-fit items-center gap-1.5 rounded-lg px-2 text-sm font-semibold text-primary no-underline hover:bg-muted',
          FOCUS,
        )}
      >
        <ArrowLeft size={16} aria-hidden="true" />
        {t('accounts.back')}
      </Link>
      {children}
    </div>
  )
}
