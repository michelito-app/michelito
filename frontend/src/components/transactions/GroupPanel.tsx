import { useId, useState, type ReactNode } from 'react'
import { t } from '@/i18n'
import type { GroupExpense, SharedInfo } from '@/lib/api'
import {
  expenseCount,
  expenseStatus,
  formatMoney,
  linkedLabel,
  overWarning,
  sharedStats,
  splitText,
  unconvertedWarning,
} from '@/lib/links'
import { useChangeGroup, useGroupExpenseCandidates } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { CandidatePicker } from './CandidatePicker'
import { AddRefund, GroupRefundList } from './GroupRefunds'
import {
  Action,
  ConfirmBox,
  CURRENT_ROW,
  Failure,
  FIELD,
  LoadFailure,
  SECTION,
  SECTION_TITLE,
} from './linkParts'
import { SplitForm } from './SplitForm'

interface GroupPanelProps {
  group: SharedInfo
  /** The open transaction (an expense or a reimbursement of the group): highlighted in its list. */
  current: string
}

const SUBTITLE = 'text-[13px] font-semibold text-ink-2'
const WARNING = 'rounded-lg bg-up-soft px-3 py-2 text-[13px] text-up-ink'

/** Management screen of a shared group: summary by currency, name and people, the expenses
 * (each with its split and status), the reimbursements and how to add more. */
export function GroupPanel({ group, current }: GroupPanelProps) {
  const ids = useId()
  const change = useChangeGroup()
  const over = overWarning(group)
  const unconverted = unconvertedWarning(group)
  const anyPending = group.pending.length > 0

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION} data-testid="shared-group">
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        {t('links.group.heading', { expenses: expenseCount(group.expense_count) })}
      </h2>
      <p className="text-base font-semibold break-words">{group.title}</p>
      <dl
        data-testid="shared-line"
        className="grid grid-cols-3 gap-2 rounded-lg bg-muted px-3 py-2.5"
      >
        {sharedStats(group).map(({ label, value }) => (
          <div key={label} className="flex min-w-0 flex-col gap-0.5">
            <dt className="text-[11.5px] text-muted-foreground">{label}</dt>
            <dd className="text-[13px] font-semibold break-words tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      {over && <p className={WARNING}>{over}</p>}
      {unconverted && <p className={WARNING}>{unconverted}</p>}
      <Identity group={group} />

      <h3 className={SUBTITLE}>{t('links.group.expenses')}</h3>
      <ul aria-label={t('links.group.expensesList')} className="flex flex-col gap-3">
        {group.expenses.map((expense) => (
          <ExpenseRow
            key={expense.fingerprint}
            group={group}
            expense={expense}
            current={expense.fingerprint === current}
          />
        ))}
      </ul>

      <h3 className={SUBTITLE}>{t('links.group.refunds')}</h3>
      <GroupRefundList group={group} current={current} />

      {(anyPending || group.written_off) && (
        <label className="flex min-h-11 cursor-pointer items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            checked={group.written_off}
            disabled={change.isPending}
            onChange={(event) =>
              change.mutate({
                action: 'patch',
                id: group.id,
                body: { written_off: event.target.checked },
              })
            }
            className="mt-0.5 size-[18px] shrink-0 cursor-pointer accent-up"
          />
          <span className="flex flex-col gap-0.5">
            <span className="font-semibold">{t('links.group.writeOff')}</span>
            <span className="text-[13px] text-muted-foreground">
              {t('links.group.writeOffHint')}
            </span>
          </span>
        </label>
      )}
      <Failure error={change.error} />

      <AddExpense group={group} />
      <Toggle label={t('links.group.addRefund')}>
        <AddRefund group={group} />
      </Toggle>
    </section>
  )
}

/** The group's name and its people, editable. */
function Identity({ group }: { group: SharedInfo }) {
  const change = useChangeGroup()
  const [name, setName] = useState(group.name)
  const [withWhom, setWithWhom] = useState(group.with_whom)
  const dirty = name.trim() !== group.name || withWhom.trim() !== group.with_whom
  const label = 'flex min-w-0 flex-col gap-1 text-[13px] font-semibold text-ink-2'
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2">
        <label className={label}>
          {t('links.group.people')}
          <input
            maxLength={80}
            value={withWhom}
            onChange={(e) => setWithWhom(e.target.value)}
            className={FIELD}
          />
        </label>
        <label className={label}>
          {t('links.group.name')}
          <input
            maxLength={80}
            placeholder={t('links.group.namePlaceholder')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={FIELD}
          />
        </label>
      </div>
      {dirty && (
        <div>
          <Action
            disabled={change.isPending}
            onClick={() =>
              change.mutate({
                action: 'patch',
                id: group.id,
                body: { name: name.trim() || null, with_whom: withWhom.trim() || null },
              })
            }
          >
            {t('links.group.saveName')}
          </Action>
        </div>
      )}
      <Failure error={change.error} />
    </div>
  )
}

interface ExpenseRowProps {
  group: SharedInfo
  expense: GroupExpense
  current: boolean
}

/** An expense of the group: split and status; change the split or remove it from the group
 * (the last expense asks for confirmation: it deletes the group and frees its reimbursements). */
function ExpenseRow({ group, expense, current }: ExpenseRowProps) {
  const change = useChangeGroup()
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const last = group.expenses.length === 1
  const refunds = group.reimbursements.length + group.manual.length

  function remove() {
    change.mutate({ action: 'remove-expense', id: group.id, fingerprint: expense.fingerprint })
  }

  return (
    <li
      aria-current={current ? 'true' : undefined}
      className={cn('flex flex-col gap-2 text-[13px]', current && CURRENT_ROW)}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="flex min-w-0 flex-col">
          <span className="font-semibold break-words text-foreground">{linkedLabel(expense)}</span>
          <span className="text-muted-foreground">
            {expense.account_label} ·{' '}
            <span className="tabular-nums">
              {formatMoney(expense.amount_cents, expense.currency)}
            </span>{' '}
            · {splitText(expense, expense.currency)}
          </span>
          <span data-testid="expense-status" className="font-semibold text-ink-2 tabular-nums">
            {expenseStatus(expense)}
          </span>
        </span>
        <div className="flex flex-wrap gap-2">
          <Action
            label={t('links.group.changeSplitOf', { merchant: expense.merchant })}
            onClick={() => setEditing((v) => !v)}
          >
            {t('links.group.changeSplit')}
          </Action>
          <Action
            label={t('links.group.removeExpenseOf', { merchant: expense.merchant })}
            disabled={change.isPending}
            onClick={() => (last ? setConfirming(true) : remove())}
          >
            {t('links.group.removeExpense')}
          </Action>
        </div>
      </div>
      {confirming && (
        <ConfirmBox
          label={t('links.group.removeLast')}
          confirmLabel={t('links.group.removeLastConfirm')}
          busy={change.isPending}
          onConfirm={remove}
          onCancel={() => setConfirming(false)}
        >
          {t('links.group.lastExpense')}{' '}
          {refunds > 0 && t('links.group.lastExpenseRefunds')}
        </ConfirmBox>
      )}
      {editing && (
        <SplitForm
          currency={expense.currency}
          amountCents={expense.amount_cents}
          initial={expense}
          saving={change.isPending}
          submitLabel={t('links.group.saveSplit')}
          onCancel={() => setEditing(false)}
          onSave={(split) =>
            change.mutate(
              { action: 'split', id: group.id, fingerprint: expense.fingerprint, split },
              { onSuccess: () => setEditing(false) },
            )
          }
        />
      )}
      <Failure error={change.error} />
    </li>
  )
}

interface Picked {
  fingerprint: string
  amount: number
  currency: string
}

/** Add another expense: unlinked debits near the group's; picking one offers the split of the
 * last one added. */
function AddExpense({ group }: { group: SharedInfo }) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<Picked | null>(null)
  const candidates = useGroupExpenseCandidates(group.id, open)
  const change = useChangeGroup()

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-3">
      <div>
        <Action onClick={() => setOpen((v) => !v)}>
          {open ? t('links.close') : t('links.group.addExpense')}
        </Action>
      </div>
      {open && picked === null && (
        <>
          {candidates.isError ? (
            <LoadFailure what={t('links.what.expenses')} error={candidates.error} />
          ) : candidates.isPending ? (
            <p className="text-[13px] text-muted-foreground">{t('links.searching')}</p>
          ) : (candidates.data ?? []).length === 0 ? (
            <p className="text-[13px] text-muted-foreground">
              {t('links.group.noCandidates')}
            </p>
          ) : (
            <CandidatePicker
              items={candidates.data ?? []}
              label={t('links.group.candidates')}
              action={(item) => (
                <Action
                  label={t('links.addMerchant', { merchant: item.merchant })}
                  onClick={() =>
                    setPicked({
                      fingerprint: item.fingerprint,
                      amount: item.amount_cents,
                      currency: item.currency,
                    })
                  }
                >
                  {t('links.add')}
                </Action>
              )}
            />
          )}
        </>
      )}
      {picked && (
        <SplitForm
          currency={picked.currency}
          amountCents={picked.amount}
          initial={group.last_split}
          saving={change.isPending}
          submitLabel={t('links.group.addToGroup')}
          onCancel={() => setPicked(null)}
          onSave={(split) =>
            change.mutate(
              { action: 'add-expense', id: group.id, fingerprint: picked.fingerprint, split },
              {
                onSuccess: () => {
                  setPicked(null)
                  setOpen(false)
                },
              },
            )
          }
        />
      )}
      <Failure error={change.error} />
    </div>
  )
}

function Toggle({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex flex-col gap-2 border-t border-border pt-3">
      <div>
        <Action onClick={() => setOpen((v) => !v)}>{open ? t('links.close') : label}</Action>
      </div>
      {open && children}
    </div>
  )
}
