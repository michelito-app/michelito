import { useState } from 'react'
import { Link } from 'react-router'
import { shortAccountLabel } from '@/lib/accounts'
import type { AccountTotal, Rate } from '@/lib/api'
import { formatDop } from '@/lib/money'
import { ACCOUNT_LIMIT, accountNote, byMovement, splitTop } from '@/lib/summary'
import { cn } from '@/lib/utils'
import { FOCUS, PANEL_TITLE, ROW_DIVIDER, WIDGET, WIDGET_ACTION } from './styles'

interface ByAccountProps {
  accounts: AccountTotal[]
  rate: Rate | null
}

/** Widget «Por cuenta»: el gasto del mes de las cuentas con más movimiento y «Ver las N» para el
 * resto; cada cuenta abre su detalle en Cuentas. */
export function ByAccount({ accounts, rate }: ByAccountProps) {
  const [all, setAll] = useState(false)
  const sorted = byMovement(accounts)
  const { shown, rest } = splitTop(sorted, ACCOUNT_LIMIT, all)
  return (
    <section aria-labelledby="acc-title" className={WIDGET}>
      <div className="-my-2 flex items-center justify-between gap-3">
        <h2 id="acc-title" className={PANEL_TITLE}>
          Por cuenta
        </h2>
        {(all || rest.length > 0) && (
          <button
            type="button"
            aria-expanded={all}
            onClick={() => setAll((value) => !value)}
            className={WIDGET_ACTION}
          >
            {all ? 'Ver menos' : `Ver las ${sorted.length}`}
          </button>
        )}
      </div>
      {accounts.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">Sin compras este mes.</p>
      ) : (
        <ul>
          {shown.map((account) => (
            <li key={account.key} className={ROW_DIVIDER}>
              <Link
                to={`/cuentas?${new URLSearchParams({ cuenta: account.key })}`}
                title={account.label}
                className={cn(
                  '-mx-2 flex min-h-11 items-center justify-between gap-3 rounded-md px-2 py-1 text-foreground no-underline transition-colors hover:bg-muted/60',
                  FOCUS,
                )}
              >
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-sm font-medium">
                    {shortAccountLabel(account.label)}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {accountNote(account, rate)}
                  </span>
                </span>
                <span className="text-sm font-semibold whitespace-nowrap tabular-nums">
                  {formatDop(account.total_cents)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
