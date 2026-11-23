import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { Account, CashBox, Loan, NetWorth, NetWorthGroup } from '@/lib/api'
import { amountText, isCreditCard, statusText } from '@/lib/accounts'
import { balanceText as cashBalance, CASH_BOX_KEY } from '@/lib/cashBox'
import { payNote } from '@/lib/interest'
import { formatMoney } from '@/lib/links'
import { balanceText as loanBalance, loanAccountKey, remainingLine } from '@/lib/loans'
import { formatDop } from '@/lib/money'
import { changeLine, holdingChange, isGood, loanNotice, type Side } from '@/lib/netWorth'
import { cn } from '@/lib/utils'

interface AccountGroupsProps {
  accounts: readonly Account[]
  loans: readonly Loan[]
  cash: CashBox | null
  worth: NetWorth | undefined
  today: string
}

/** Every account in compact rows, grouped by kind with each group's total; a group folds. */
export function AccountGroups({ accounts, loans, cash, worth, today }: AccountGroupsProps) {
  const holdings = worth?.holdings ?? []
  const total = (...groups: NetWorthGroup[]) =>
    worth === undefined
      ? null
      : worth.groups.filter((g) => groups.includes(g.group)).reduce((s, g) => s + g.total_cents, 0)
  const change = (key: string) => holdingChange(holdings, key)
  const cards = accounts.filter(isCreditCard)
  const banks = accounts.filter((a) => !isCreditCard(a))
  // A closed investment (nothing left to recover) has no row.
  const extras = holdings.filter(
    (h) =>
      (h.group === 'investments' && (h.value_cents ?? 0) > 0) ||
      h.group === 'owed' ||
      h.group === 'owing',
  )
  return (
    <div data-testid="account-groups" className="flex min-w-0 flex-col gap-4">
      {cards.length > 0 && (
        <Group title={t('accounts.group.cards')} total={total('cards')}>
          {cards.map((a) => (
            <Row
              key={a.key}
              to={`?account=${encodeURIComponent(a.key)}`}
              name={a.label}
              note={a.to_pay !== null ? payNote(a.to_pay, today) : null}
              status={statusText(a)}
              balance={<StatementBalances account={a} />}
              change={change(a.key)}
              side="debt"
            />
          ))}
        </Group>
      )}
      {loans.length > 0 && (
        <Group title={t('accounts.group.loans')} total={total('loans')}>
          {loans.map((loan) => (
            <Row
              key={loan.id}
              testId="loan-account"
              to={`?account=${loanAccountKey(loan.id)}`}
              name={loan.name}
              note={loanNotice(loan, today)}
              status={{ text: remainingLine(loan), missing: false }}
              balance={loanBalance(loan)}
              change={change(loanAccountKey(loan.id))}
              side="debt"
            />
          ))}
        </Group>
      )}
      {(banks.length > 0 || cash !== null) && (
        <Group title={t('accounts.list.others')} total={total('banks', 'cash')}>
          {banks.map((a) => (
            <Row
              key={a.key}
              to={`?account=${encodeURIComponent(a.key)}`}
              name={a.label}
              status={statusText(a)}
              balance={<StatementBalances account={a} />}
              change={change(a.key)}
              side="asset"
            />
          ))}
          {cash !== null && (
            <Row
              testId="cash-account"
              to={`?account=${encodeURIComponent(CASH_BOX_KEY)}`}
              name={t('cashBox.title')}
              status={{ text: t('accounts.list.cashHint'), missing: false }}
              balance={cashBalance(cash.balances)}
              change={change(CASH_BOX_KEY)}
              side="asset"
            />
          )}
        </Group>
      )}
      {extras.some((h) => h.group === 'investments') && (
        <Group title={t('accounts.group.investments')} total={total('investments')}>
          {extras
            .filter((h) => h.group === 'investments')
            .map((h) => (
              <Row
                key={h.key}
                to="/investments"
                name={h.label}
                status={{ text: t('accounts.row.investmentHint'), missing: false }}
                balance={h.value_cents === null ? '—' : formatMoney(h.value_cents, h.currency)}
                change={h.change_dop_cents}
                side="asset"
              />
            ))}
        </Group>
      )}
      {extras.some((h) => h.group === 'owed' || h.group === 'owing') && (
        <Group title={t('accounts.group.owed')} total={(total('owed') ?? 0) - (total('owing') ?? 0)}>
          {extras
            .filter((h) => h.group === 'owed' || h.group === 'owing')
            .map((h) => (
              <Row
                key={`${h.key}-${h.currency}`}
                to="/shared"
                name={h.group === 'owed' ? t('accounts.group.owed') : t('accounts.group.owing')}
                status={{ text: t('accounts.row.owedHint'), missing: false }}
                balance={h.value_cents === null ? '—' : formatMoney(h.value_cents, h.currency)}
                change={null}
                side={h.group === 'owing' ? 'debt' : 'asset'}
              />
            ))}
        </Group>
      )}
    </div>
  )
}

interface GroupProps {
  title: string
  total: number | null
  children: ReactNode
}

function Group({ title, total, children }: GroupProps) {
  const [open, setOpen] = useState(true)
  const shown = total === null ? '' : formatDop(total)
  return (
    <section className={cn(PANEL, 'overflow-hidden')}>
      <h2>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className={cn(
            'flex min-h-12 w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-left hover:bg-muted/50 sm:px-5',
            FOCUS,
          )}
        >
          <span className="flex items-center gap-1.5 text-[13px] font-semibold tracking-[0.04em] text-muted-foreground uppercase">
            {open ? (
              <ChevronDown size={16} aria-hidden="true" />
            ) : (
              <ChevronRight size={16} aria-hidden="true" />
            )}
            {title}
          </span>
          <span className="text-[15px] font-bold tabular-nums">{shown}</span>
        </button>
      </h2>
      {open && <ul className="flex flex-col border-t border-border">{children}</ul>}
    </section>
  )
}

interface RowProps {
  to: string
  name: string
  note?: string | null
  status: { text: string; missing: boolean }
  balance: ReactNode
  change: number | null
  side: Side
  testId?: string
}

/** One account: its name and one line under it (a payment notice, otherwise how current the
 * data is); its balance and the month's change. */
function Row({ to, name, note = null, status, balance, change, side, testId }: RowProps) {
  const moved = changeLine(change)
  return (
    <li className="border-b border-[#F2F2EE] last:border-b-0">
      <Link
        to={to}
        data-testid={testId}
        className={cn(
          'flex min-h-14 items-center justify-between gap-3 px-4 py-2.5 text-foreground no-underline hover:bg-muted/50 sm:px-5',
          FOCUS,
        )}
      >
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-[15px] font-semibold">{name}</span>
          {note !== null ? (
            <span className="truncate text-xs font-medium text-up-ink">{note}</span>
          ) : (
            <span className={cn('truncate text-xs', status.missing ? 'text-up' : 'text-muted-foreground')}>
              {status.text}
            </span>
          )}
        </span>
        <span className="flex flex-none flex-col items-end tabular-nums">
          <span className="text-[15px] font-bold whitespace-nowrap">{balance}</span>
          {moved !== null && change !== null && (
            <span className={cn('text-xs whitespace-nowrap', isGood(change, side) ? 'text-down' : 'text-up')}>
              {moved}
            </span>
          )}
        </span>
      </Link>
    </li>
  )
}

/** A statement account's latest balance per currency (a card's is what it owes): the first bold,
 * the rest under it. */
function StatementBalances({ account }: { account: Account }) {
  const [first, ...rest] = account.latest
  if (first === undefined) return <>—</>
  return (
    <span className="flex flex-col items-end">
      <span>{amountText(first.balance_cents, first.currency)}</span>
      {rest.map((line) => (
        <span key={line.currency} className="text-xs font-normal text-muted-foreground">
          {amountText(line.balance_cents, line.currency)}
        </span>
      ))}
    </span>
  )
}
