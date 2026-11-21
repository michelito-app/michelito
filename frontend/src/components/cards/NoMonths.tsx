import { HostedEmpty } from '@/components/onboarding/HostedEmpty'
import { PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import { isHosted, useMode } from '@/lib/demo'
import { cn } from '@/lib/utils'

/** No month with data yet (no statement): what fills it, in place of the whole screen. */
export function NoMonths() {
  if (isHosted(useMode())) return <HostedEmpty view="summary" />
  return (
    <div className={cn(PANEL, 'flex flex-col gap-2 px-6 py-10 text-center')}>
      <h1 className="text-xl font-bold tracking-tight">{t('summary.page.title')}</h1>
      <p className="text-sm text-muted-foreground">
        {tn('summary.page.empty', {
          command: (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[13px] text-foreground">
              uv run michelito sync
            </code>
          ),
        })}
      </p>
    </div>
  )
}
