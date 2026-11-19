import type { ReactNode, Ref } from 'react'
import { Link } from 'react-router'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { Account, DuePayment, StatementLine } from '@/lib/api'
import {
  amountText,
  cutText,
  dueNote,
  footnote,
  isCreditCard,
  movementLabels,
  periodText,
} from '@/lib/accounts'
import { isOverdue, minimumText, payText, verdictText } from '@/lib/interest'
import { shortDay } from '@/lib/months'
import { cn } from '@/lib/utils'

interface StatementsPanelProps {
  account: Account
  today: string
  ref?: Ref<HTMLElement>
}

const TITLE_ID = 'stm-title'
const HEAD = 'border-b border-[#EFEFEA] px-2 py-2.5 font-semibold'
const CELL = 'border-b border-[#F2F2EE] px-2 py-3'

/** Detail of the chosen account: balance, due date, minimum payment and statements by cut. */
export function StatementsPanel({ account, today, ref }: StatementsPanelProps) {
  const transactions = `/transactions?${new URLSearchParams({ account: account.key })}`
  return (
    <section
      ref={ref}
      aria-labelledby={TITLE_ID}
      className={cn(PANEL, 'flex min-w-0 flex-[3_1_560px] scroll-mt-6 flex-col gap-5 p-5 sm:p-6')}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id={TITLE_ID} className="text-xl font-bold">
            {account.label}
          </h2>
          <span className="text-[13px] text-muted-foreground">{t('accounts.panel.byCut')}</span>
          {account.statements.length > 0 && (
            <span className="mt-1 inline-flex w-fit items-center rounded-full bg-secondary px-2.5 py-[3px] text-xs font-semibold text-secondary-foreground">
              {t('accounts.panel.allBalanced')}
            </span>
          )}
        </div>
        <Link
          to={transactions}
          className={cn(
            'inline-flex h-11 items-center rounded-[10px] border border-[#D6D6D0] px-3.5 text-sm font-semibold text-primary no-underline hover:bg-muted hover:text-secondary-foreground',
            FOCUS,
          )}
        >
          {t('accounts.panel.viewTransactions')}
        </Link>
      </div>
      {isCreditCard(account) && account.to_pay !== null && (
        <PayStrip payment={account.to_pay} today={today} />
      )}
      <Stats account={account} today={today} />
      {account.statements.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('accounts.panel.noStatements')}</p>
      ) : (
        <>
          <StatementsTable account={account} />
          <p className="text-[13px] text-muted-foreground">{footnote(account)}</p>
        </>
      )}
    </section>
  )
}

/** How much to pay and by when to avoid interest, with the minimum next to it. */
function PayStrip({ payment, today }: { payment: DuePayment; today: string }) {
  const overdue = isOverdue(payment.due_date, today)
  const minimum = minimumText(payment)
  return (
    <div
      className={cn(
        'flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-xl px-4 py-3',
        overdue ? 'bg-muted text-ink-2' : 'bg-down-soft text-down',
      )}
    >
      <span className="text-sm font-semibold tabular-nums">{payText(payment, today)}</span>
      {minimum && <span className="text-[13px] text-ink-2 tabular-nums">{minimum}</span>}
    </div>
  )
}

interface StatProps {
  label: string
  values: string[]
  note?: string
}

function Stat({ label, values, note }: StatProps) {
  const [main, ...rest] = values.length ? values : ['—']
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-xl border border-[#EFEFEA] bg-[#FAFAF8] px-4 py-3.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xl font-bold tabular-nums">{main}</span>
      {rest.map((value) => (
        <span key={value} className="text-xs text-muted-foreground tabular-nums">
          {value}
        </span>
      ))}
      {note && <span className="text-xs text-muted-foreground">{note}</span>}
    </div>
  )
}

function Stats({ account, today }: Omit<StatementsPanelProps, 'ref'>) {
  const latest = account.latest
  const cut = latest[0]?.period_end
  const due = latest.find((line) => line.due_date !== null)?.due_date ?? null
  const cutNote = cut ? t('accounts.panel.cutOf', { day: shortDay(cut) }) : undefined
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3">
      <Stat
        label={t('accounts.stat.lastBalance')}
        values={latest.map((line) => amountText(line.balance_cents, line.currency))}
        note={cutNote}
      />
      {/* Savings and debit accounts have no due date or minimum payment. */}
      {isCreditCard(account) && (
        <>
          <Stat
            label={t('accounts.stat.payBefore')}
            values={due ? [shortDay(due)] : []}
            note={due ? dueNote(due, today, cut) || undefined : undefined}
          />
          <Stat
            label={t('accounts.stat.minimum')}
            values={latest.map((line) => amountText(line.minimum_payment_cents, line.currency))}
          />
        </>
      )}
    </div>
  )
}

function StatementsTable({ account }: { account: Account }) {
  const labels = movementLabels(account)
  return (
    // Horizontal scrolling stays inside the box, not on the page.
    <div className="-mx-1 overflow-x-auto px-1" tabIndex={0} role="region" aria-label={t('accounts.table.label')}>
      <table className="w-full min-w-[480px] border-collapse text-sm tabular-nums">
        <thead>
          <tr className="text-left text-xs tracking-[0.04em] text-muted-foreground uppercase">
            <Th>{t('accounts.table.cut')}</Th>
            <Th>{t('accounts.table.period')}</Th>
            <Th right>{labels.charges}</Th>
            <Th right>{labels.payments}</Th>
            <Th right>{t('accounts.table.balance')}</Th>
          </tr>
        </thead>
        <tbody>
          {account.statements.map((line, index) => (
            <tr key={`${line.period_end}-${line.currency}-${index}`}>
              <td className={cn(CELL, 'font-semibold whitespace-nowrap')}>
                {cutText(line)}
              </td>
              <td className={cn(CELL, 'whitespace-nowrap text-muted-foreground')}>
                {periodText(line)}
              </td>
              <td className={cn(CELL, 'text-right whitespace-nowrap')}>
                {amountText(line.charges_cents, line.currency)}
              </td>
              <td className={cn(CELL, 'text-right whitespace-nowrap text-down')}>
                {amountText(line.payments_cents, line.currency)}
              </td>
              <td className={cn(CELL, 'text-right whitespace-nowrap')}>
                <span className="font-semibold">
                  {amountText(line.balance_cents, line.currency)}
                </span>
                {isCreditCard(account) && <VerdictLines line={line} />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Under the balance: whether it was paid in full with the next statement, or what was left
 * and what it cost. */
function VerdictLines({ line }: { line: StatementLine }) {
  const verdict = verdictText(line)
  if (verdict === null) return null
  return (
    <>
      {verdict.text && (
        <span
          className={cn(
            'block text-xs',
            verdict.tone === 'paid' ? 'text-secondary-foreground' : 'text-up',
          )}
        >
          {verdict.text}
        </span>
      )}
      {verdict.interest && <span className="block text-xs text-up">{verdict.interest}</span>}
    </>
  )
}

function Th({ children, right = false }: { children: ReactNode; right?: boolean }) {
  return (
    <th scope="col" className={cn(HEAD, right && 'text-right')}>
      {children}
    </th>
  )
}
