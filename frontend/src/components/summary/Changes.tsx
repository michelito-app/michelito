import type { Change } from '@/lib/api'
import { changeDetail, changeTitle } from '@/lib/summary'
import { cn } from '@/lib/utils'

/** «Qué cambió» (pestaña de «Lectura del mes»): las diferencias mayores contra lo habitual, cada
 * una con una frase. Sin cambios, la pestaña no aparece. */
export function Changes({ changes }: { changes: Change[] }) {
  return (
    <ul className="grid gap-x-8 gap-y-3.5 md:grid-cols-2">
      {changes.map((change) => {
        const up = change.diff_cents > 0
        return (
          <li key={change.category} className="flex items-start gap-3">
            <span
              aria-hidden="true"
              className={cn(
                'mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg text-[15px] font-bold',
                up ? 'bg-up-soft text-up' : 'bg-down-soft text-down',
              )}
            >
              {up ? '↑' : '↓'}
            </span>
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-sm font-semibold">{changeTitle(change)}</span>
              <span className="text-[13px] text-muted-foreground">{changeDetail(change)}</span>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
