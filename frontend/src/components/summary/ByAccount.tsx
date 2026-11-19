import { useState } from 'react'
import { Link } from 'react-router'
import { t } from '@/i18n'
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

/** "By account" widget: the month's spending of the accounts with the most movement and "See all
 * N" for the rest; each account opens its detail in Accounts. */
export function ByAccount({ accounts, rate }: ByAccountProps) {
  const [all, setAll] = useState(false)
  const sorted = byMovement(accounts)
  const { shown, rest } = splitTop(sorted, ACCOUNT_LIMIT, all)
  return (
    <section aria-labelledby="acc-title" className={WIDGET}>
      <div className="-my-2 flex items-center justify-between gap-3">
        <h2 id="acc-title" className={PANEL_TITLE}>
          {t('summary.byAccount.title')}
        </h2>
        {(all || rest.length > 0) && (
          <button
            type="button"
            aria-expanded={all}
            onClick={() => setAll((value) => !value)}
            className={WIDGET_ACTION}
          >
            {all ? t('summary.review.seeLess') : t('summary.categories.seeAll', { count: sorted.length })}
          </button>
        )}
      </div>
      {accounts.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('summary.categories.empty')}</p>
      ) : (
        <ul>
          {shown.map((account) => (
            <li key={account.key} className={ROW_DIVIDER}>
              <Link
                to={`/accounts?${new URLSearchParams({ account: account.key })}`}
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
