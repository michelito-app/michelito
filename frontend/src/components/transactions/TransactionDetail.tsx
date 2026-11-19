import { Check, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { CategoryOptions } from './Filters'
import { NewCategoryDialog } from '@/components/categories/NewCategoryDialog'
import type { Category, Tx } from '@/lib/api'
import { choosable, isNewCategoryOption } from '@/lib/categories'
import { useDismissOneOff, useEditTransaction } from '@/lib/queries'
import {
  AMOUNT_TONE_CLASS,
  amountLines,
  amountTone,
  dayLabel,
  type Draft,
  editBody,
  merchantScopeNote,
  NOTE_MAX,
  oneOffAction,
  originText,
  type Scope,
} from '@/lib/transactions'
import { categoryLocked } from '@/lib/links'
import { cn } from '@/lib/utils'
import { HistorySection } from '@/components/log/HistorySection'
import { CashBoxSection } from './CashBoxSection'
import { LinkSummaries } from './LinkSummaries'
import { RecurringSection } from './RecurringSection'
import { ReserveSection } from './ReserveSection'

/** Below this width the detail is a bottom sheet (see TransactionsPage). */
const SHEET_QUERY = '(max-width: 1279.98px)'

/** Id of the title, for the panel's `aria-labelledby`. */
export const DETAIL_TITLE_ID = 'tx-detail-title'

interface TransactionDetailProps {
  tx: Tx
  categories: Category[]
  /** Is the row still in the list with the current filters? */
  inList: boolean
  onSaved: (tx: Tx) => void
  onClose: () => void
  onShowMerchant: (merchant: string) => void
}

function draftOf(tx: Tx): Draft {
  return { category: tx.category, oneOff: tx.one_off, scope: 'transaction', note: tx.note }
}

/** Detail of the chosen transaction and its correction (category, scope, one-off). */
export function TransactionDetail({
  tx,
  categories,
  inList,
  onSaved,
  onClose,
  onShowMerchant,
}: TransactionDetailProps) {
  const ids = useId()
  const heading = useRef<HTMLHeadingElement>(null)
  const [draft, setDraft] = useState<Draft>(() => draftOf(tx))
  // A new link (the cash box, for example) changes the category from outside the form.
  const [seenCategory, setSeenCategory] = useState(tx.category)
  if (seenCategory !== tx.category) {
    setSeenCategory(tx.category)
    setDraft((current) => ({ ...current, category: tx.category }))
  }
  const [savedNote, setSavedNote] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  // The one just created, while the category list is fetched again.
  const [created, setCreated] = useState<Category | null>(null)
  // Without the ones only a link sets: the row's own, if it is one of them, still shows (locked).
  const listed = choosable(categories)
  const options =
    created && !listed.some((c) => c.id === created.id) ? [...listed, created] : listed
  const edit = useEditTransaction()
  const body = editBody(tx, draft)
  const amount = amountLines(tx)
  const locked = categoryLocked(tx)

  // In the bottom sheet (phone) the focus goes to the detail when it opens.
  useEffect(() => {
    if (window.matchMedia(SHEET_QUERY).matches) heading.current?.focus({ preventScroll: true })
  }, [])

  function change(patch: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...patch }))
    setSavedNote(null)
    edit.reset()
  }

  function save() {
    if (body === null) return
    const scope = draft.scope
    edit.mutate(
      { fingerprint: tx.fingerprint, body },
      {
        onSuccess: (saved) => {
          setDraft(draftOf(saved))
          setSavedNote(
            scope === 'merchant'
              ? t('transactions.detail.savedMerchant', {
                  merchant: saved.merchant,
                  category: saved.category,
                })
              : t('transactions.saved'),
          )
          onSaved(saved)
        },
      },
    )
  }

  return (
    <div
      className="flex flex-col gap-5"
      onKeyDown={(event) => {
        if (event.key === 'Escape') onClose()
      }}
    >
      <div className="flex items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="text-[13px] text-muted-foreground">
            {dayLabel(tx.day)} · {tx.account_label}
          </span>
          <h2
            id={DETAIL_TITLE_ID}
            ref={heading}
            tabIndex={-1}
            className="text-[22px] leading-tight font-bold tracking-[-0.01em] break-words outline-none"
          >
            {tx.merchant}
          </h2>
          <span
            className={cn(
              'text-[28px] leading-tight font-bold tabular-nums',
              AMOUNT_TONE_CLASS[amountTone(tx)],
            )}
          >
            {amount.main}
          </span>
          <span className="text-[13px] text-muted-foreground">{originText(tx)}</span>
        </div>
        <button
          type="button"
          aria-label={t('transactions.detail.close')}
          onClick={onClose}
          className={cn(
            '-mt-1 -mr-2 flex size-11 shrink-0 items-center justify-center rounded-[10px] text-muted-foreground hover:bg-muted hover:text-foreground xl:hidden',
            FOCUS,
          )}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>

      <div className="flex flex-col gap-1 rounded-xl border border-[#EFEFEA] bg-[#FAFAF8] px-3.5 py-3">
        <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase">
          {t('transactions.detail.statement')}
        </span>
        <span className="font-mono text-[13px] break-all text-ink-2">{tx.description}</span>
      </div>

      <label className="flex flex-col gap-2 text-[13px] font-semibold text-ink-2">
        {t('transactions.filters.category')}
        <select
          aria-label={t('transactions.filters.category')}
          value={draft.category}
          disabled={locked}
          aria-describedby={locked ? `${ids}-locked` : undefined}
          onChange={(event) => {
            if (isNewCategoryOption(event.target.selectedOptions[0])) setCreating(true)
            else change({ category: event.target.value })
          }}
          className="h-11 w-full cursor-pointer rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm font-medium text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <CategoryOptions categories={options} current={tx.category} allowNew />
        </select>
        {locked && (
          <span id={`${ids}-locked`} className="text-xs font-normal text-muted-foreground">
            {t('transactions.detail.locked')}
          </span>
        )}
      </label>
      {creating && (
        <NewCategoryDialog
          kind={tx.kind}
          onClose={() => setCreating(false)}
          onCreated={(category) => {
            setCreated(category)
            setCreating(false)
            change({ category: category.name })
          }}
        />
      )}

      <fieldset className="flex flex-col gap-2" disabled={locked}>
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">
          {t('transactions.detail.applyTo')}
        </legend>
        <ScopeOption
          name={`${ids}-scope`}
          value="transaction"
          checked={draft.scope === 'transaction'}
          onPick={(scope) => change({ scope })}
        >
          {t('transactions.detail.onlyThis')}
        </ScopeOption>
        <ScopeOption
          name={`${ids}-scope`}
          value="merchant"
          checked={draft.scope === 'merchant'}
          onPick={(scope) => change({ scope })}
        >
          <span>
            {t('transactions.detail.wholeMerchant', { merchant: tx.merchant })}{' '}
            <span className="text-muted-foreground">
              · {merchantScopeNote(tx)}
            </span>
          </span>
        </ScopeOption>
      </fieldset>

      <label className="flex min-h-11 cursor-pointer items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={draft.oneOff}
          onChange={(event) => change({ oneOff: event.target.checked })}
          className="mt-0.5 size-[18px] shrink-0 cursor-pointer accent-up"
        />
        <span className="flex flex-col gap-0.5">
          <span className="font-semibold">{t('transactions.detail.oneOff')}</span>
          <span className="text-[13px] text-muted-foreground">
            {t('transactions.detail.oneOffHint')}
          </span>
        </span>
      </label>

      <OneOffHint tx={tx} />

      <label className="flex flex-col gap-2 text-[13px] font-semibold text-ink-2">
        {t('transactions.detail.note')}
        <textarea
          value={draft.note}
          maxLength={NOTE_MAX}
          rows={2}
          placeholder={t('transactions.detail.notePlaceholder')}
          onChange={(event) => change({ note: event.target.value })}
          className="min-h-11 w-full resize-y rounded-xl border border-[#D6D6D0] bg-card px-3 py-2.5 text-sm font-normal text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
        />
        <span className="text-xs font-normal text-muted-foreground">
          {t('transactions.detail.noteHint', { length: draft.note.length, max: NOTE_MAX })}
        </span>
      </label>

      {tx.corrected && (
        <p className="rounded-[10px] bg-secondary px-3 py-2.5 text-[13px] text-secondary-foreground">
          {t('transactions.detail.corrected', { category: tx.original_category })}
        </p>
      )}

      {!inList && (
        <p className="text-[13px] text-muted-foreground">{t('transactions.detail.notInList')}</p>
      )}

      {edit.isError && (
        <p
          role="alert"
          className="rounded-[10px] border border-up/30 bg-up-soft px-3 py-2.5 text-[13px] text-up-ink"
        >
          {t('transactions.saveError', { message: edit.error.message })}
        </p>
      )}

      <div className="flex flex-col gap-2.5">
        <div className="flex flex-wrap gap-2.5">
          <Button
            className="h-11 flex-[1_1_140px] rounded-xl text-sm font-semibold"
            disabled={body === null || edit.isPending}
            onClick={save}
          >
            {edit.isPending ? t('transactions.saving') : t('transactions.save')}
          </Button>
          <Button
            variant="outline"
            className="h-11 flex-[1_1_140px] rounded-xl border-[#D6D6D0] bg-card text-sm font-semibold text-ink-2"
            onClick={() => onShowMerchant(tx.merchant)}
          >
            {t('transactions.detail.showMerchant')}
          </Button>
        </div>
        <p role="status" className="min-h-5 text-[13px] font-medium text-primary">
          {savedNote && (
            <span className="inline-flex items-center gap-1.5">
              <Check size={14} aria-hidden="true" />
              {savedNote}
            </span>
          )}
        </p>
      </div>

      <LinkSummaries tx={tx} />
      <RecurringSection tx={tx} />
      <ReserveSection tx={tx} />
      <CashBoxSection tx={tx} onSaved={onSaved} onClose={onClose} />
      <HistorySection fingerprint={tx.fingerprint} />
    </div>
  )
}

/** Why the row looks like a one-off expense, with a button to dismiss it; once dismissed, a
 * button to suggest it again undoes that. */
function OneOffHint({ tx }: { tx: Tx }) {
  const dismiss = useDismissOneOff()
  const action = oneOffAction(tx)
  if (action === null) return null
  const restoring = action === 'restore'
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-dashed border-up/40 px-3.5 py-3">
      <p className="text-[13px] text-ink-2">
        {restoring ? (
          t('transactions.oneOff.dismissed')
        ) : (
          <>
            <span className="font-semibold">{t('transactions.oneOff.question')}</span>{' '}
            {tx.one_off_reasons.join(' · ')}
          </>
        )}
      </p>
      <Button
        variant="outline"
        className="h-11 self-start rounded-xl border-[#D6D6D0] bg-card px-4 text-sm font-semibold text-ink-2"
        disabled={dismiss.isPending}
        onClick={() => dismiss.mutate({ fingerprint: tx.fingerprint, dismissed: !restoring })}
      >
        {restoring ? t('transactions.oneOff.restore') : t('transactions.oneOff.dismiss')}
      </Button>
      {dismiss.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('transactions.saveError', { message: dismiss.error.message })}
        </p>
      )}
    </div>
  )
}

interface ScopeOptionProps {
  name: string
  value: Scope
  checked: boolean
  onPick: (scope: Scope) => void
  children: ReactNode
}

function ScopeOption({ name, value, checked, onPick, children }: ScopeOptionProps) {
  return (
    <label
      className={cn(
        'flex min-h-11 cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2 text-sm transition-colors',
        checked ? 'border-primary bg-[#F6FAF8]' : 'border-border hover:bg-[#FAFAF8]',
      )}
    >
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        onChange={() => onPick(value)}
        className="size-[18px] shrink-0 cursor-pointer accent-primary"
      />
      {children}
    </label>
  )
}
