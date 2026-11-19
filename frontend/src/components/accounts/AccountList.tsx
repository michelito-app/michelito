import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { Account } from '@/lib/api'
import { amountText, cutLine, groupAccounts, isCreditCard, statusText } from '@/lib/accounts'
import { categoryColor } from '@/lib/categories'
import { payNote } from '@/lib/interest'
import { cn } from '@/lib/utils'

interface AccountListProps {
  accounts: Account[]
  selected: string
  today: string
  onSelect: (key: string) => void
}

const GROUP_TITLE = 'text-[13px] font-semibold tracking-[0.04em] text-muted-foreground uppercase'

/** Accounts grouped by kind; each one is a button that picks the panel's account. */
export function AccountList({ accounts, selected, today, onSelect }: AccountListProps) {
  const { cards, others } = groupAccounts(accounts)
  // The chip colour follows the order of the whole list, not the group's.
  const color = (account: Account) => categoryColor(accounts.indexOf(account))
  return (
    <div className="flex min-w-0 flex-[2_1_320px] flex-col gap-3">
      <h2 className={cn(GROUP_TITLE, 'mt-1')}>{t('accounts.list.cards')}</h2>
      {cards.length === 0 ? (
        <EmptyGroup title={t('accounts.list.noCards')} />
      ) : (
        cards.map((account) => (
          <AccountButton
            key={account.key}
            account={account}
            chip={color(account)}
            pressed={account.key === selected}
            today={today}
            onSelect={onSelect}
          />
        ))
      )}
      <h2 className={cn(GROUP_TITLE, 'mt-3')}>{t('accounts.list.others')}</h2>
      {others.length === 0 ? (
        <EmptyGroup title={t('accounts.list.noOthers')} />
      ) : (
        others.map((account) => (
          <AccountButton
            key={account.key}
            account={account}
            chip={color(account)}
            pressed={account.key === selected}
            today={today}
            onSelect={onSelect}
          />
        ))
      )}
    </div>
  )
}

interface AccountButtonProps {
  account: Account
  chip: string
  pressed: boolean
  today: string
  onSelect: (key: string) => void
}

function AccountButton({ account, chip, pressed, today, onSelect }: AccountButtonProps) {
  const status = statusText(account)
  const [first, ...rest] = account.latest
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={() => onSelect(account.key)}
      className={cn(
        'flex w-full cursor-pointer flex-col gap-2.5 rounded-2xl bg-card px-5 py-[18px] text-left text-foreground transition-colors',
        pressed
          ? 'border-2 border-primary px-[19px] py-[17px]'
          : 'border border-border hover:border-[#D6D6D0]',
        FOCUS,
      )}
    >
      <span className="flex w-full items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden="true"
            className="h-7 w-10 flex-none rounded-md"
            style={{ background: chip }}
          />
          <span className="flex min-w-0 flex-col">
            <span className="text-[15px] font-semibold [overflow-wrap:anywhere]">{account.label}</span>
            <span className="text-xs text-muted-foreground">{cutLine(account)}</span>
          </span>
        </span>
        <span className="flex flex-none flex-col items-end tabular-nums">
          <span className="text-base font-bold whitespace-nowrap">
            {first ? amountText(first.balance_cents, first.currency) : '—'}
          </span>
          {rest.map((line) => (
            <span key={line.currency} className="text-xs whitespace-nowrap text-muted-foreground">
              {amountText(line.balance_cents, line.currency)}
            </span>
          ))}
        </span>
      </span>
      <span
        className={cn(
          'flex items-center gap-1.5 text-xs',
          status.missing ? 'text-up' : 'text-secondary-foreground',
        )}
      >
        <span aria-hidden="true" className="size-2 flex-none rounded-full bg-current" />
        {status.text}
      </span>
      {isCreditCard(account) && account.to_pay !== null && (
        <span className="text-xs text-muted-foreground tabular-nums">
          {payNote(account.to_pay, today)}
        </span>
      )}
    </button>
  )
}

function EmptyGroup({ title }: { title: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-2xl border-[1.5px] border-dashed border-[#D6D6D0] px-5 py-[18px]">
      <span className="text-sm font-semibold">{title}</span>
      <span className="text-[13px] text-muted-foreground">
        {t('accounts.list.emptyHint')}
      </span>
    </div>
  )
}
