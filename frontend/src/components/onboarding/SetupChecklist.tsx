import { useQueryClient } from '@tanstack/react-query'
import { CircleCheck, Circle } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { type Checklist, missingLine, onboardingKey, setFlag } from '@/lib/onboarding'
import { cn } from '@/lib/utils'

const UPLOAD = cn(
  'inline-flex min-h-11 shrink-0 items-center rounded-lg px-3 text-[13px] font-semibold text-primary no-underline hover:bg-muted',
  FOCUS,
)

interface ItemProps {
  done: boolean
  label: string
  detail?: string
  action: 'upload' | 'automate'
}

function Item({ done, label, detail, action }: ItemProps) {
  return (
    <li className="flex items-center gap-3 border-b border-border py-2 last:border-b-0">
      {done ? (
        <CircleCheck size={18} className="shrink-0 text-down" aria-hidden="true" />
      ) : (
        <Circle size={18} className="shrink-0 text-muted-foreground" aria-hidden="true" />
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <span className={cn('text-sm', done ? 'text-muted-foreground line-through' : 'font-medium')}>
          {label}
        </span>
        {detail && <span className="text-[13px] text-muted-foreground">{detail}</span>}
      </div>
      {done ? (
        <span className="text-[13px] text-muted-foreground">{t('onboarding.checklist.done')}</span>
      ) : action === 'automate' ? (
        <Link to="/settings#automate" className={UPLOAD}>
          {t('onboarding.checklist.setUp')}
        </Link>
      ) : (
        <Link to="/import" className={UPLOAD}>
          {t('onboarding.checklist.upload')}
        </Link>
      )}
    </li>
  )
}

/** The Summary's setup checklist (hosted): more months, another account, automate the next
 * ones (email forwarding, in Settings) and each month missing per account. Visible until completed or
 * hidden. */
export function SetupChecklist({ checklist }: { checklist: Checklist }) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const id = useId()

  async function dismiss() {
    try {
      await setFlag('checklist_dismissed')
      await queryClient.invalidateQueries({ queryKey: onboardingKey })
    } catch (failure) {
      setError((failure as Error).message)
    }
  }

  return (
    <section aria-labelledby={id} className={cn(PANEL, 'flex flex-col gap-2 px-5 py-4')}>
      <div className="flex items-center justify-between gap-2">
        <h2 id={id} className="text-[17px] font-[650] tracking-tight">
          {t('onboarding.checklist.title')}
        </h2>
        <Button variant="ghost" className="h-11 px-3" onClick={() => void dismiss()}>
          {t('onboarding.checklist.dismiss')}
        </Button>
      </div>
      <ul className="flex flex-col">
        <Item
          done={checklist.more_months_done}
          label={t('onboarding.checklist.months')}
          detail={t('onboarding.checklist.monthsProgress', { count: Math.min(checklist.months, 3) })}
          action="upload"
        />
        {checklist.missing.map((missing) => (
          <Item key={`${missing.bank}-${missing.identifier}-${missing.month}`} done={false} label={missingLine(missing)} action="upload" />
        ))}
        <Item done={checklist.other_account_done} label={t('onboarding.checklist.account')} action="upload" />
        <Item
          done={checklist.automate_done}
          label={t('onboarding.checklist.automate')}
          action="automate"
        />
      </ul>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </section>
  )
}
