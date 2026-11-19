import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { categoryGroups } from '@/lib/categories'
import type { Category, Tx } from '@/lib/api'
import { REASON_MAX } from '@/lib/log'
import { useBatchCategory } from '@/lib/queries'
import { BATCH_MAX, batchOptions, counterText, linkedText, resultText } from '@/lib/selection'
import { BAR_ATTR, type BatchNote } from '@/lib/useTxSelection'
import { cn } from '@/lib/utils'
import { ReserveBatch } from './ReserveBatch'

const NONE = ''
const CONTROL = cn(
  'h-11 min-w-0 rounded-xl border border-border bg-card px-3 text-sm text-foreground',
  FOCUS,
)
const ACTION = cn('h-11 shrink-0 rounded-xl px-4 text-sm font-semibold', FOCUS)

interface SelectionBarProps {
  /** The chosen rows that are visible with the current filters. */
  chosen: Tx[]
  /** How many rows are visible (with groups, those of the open ones), for "select all visible". */
  visible: number
  /** Are all visible rows already chosen? (then the button is not needed). */
  allVisibleChosen: boolean
  categories: readonly Category[]
  onSelectAll: () => void
  onCancel: () => void
  /** Done: the result (the page shows it when leaving the mode). */
  onDone: (note: BatchNote) => void
}

/** Bar fixed at the bottom in selection mode: counter, "select all visible", the new category
 * (only those transactions) and a shared reason. It leaves a gap of its own height below the
 * list, so it never covers the last row. */
export function SelectionBar({
  chosen,
  visible,
  allVisibleChosen,
  categories,
  onSelectAll,
  onCancel,
  onDone,
}: SelectionBarProps) {
  const bar = useRef<HTMLDivElement>(null)
  const [height, setHeight] = useState(0)
  const left = useMainLeft()
  const [categoryId, setCategoryId] = useState(NONE)
  const [reason, setReason] = useState('')
  const batch = useBatchCategory()
  const options = batchOptions(categories, chosen)
  const target = options.categories.find((c) => String(c.id) === categoryId) ?? null
  const linked = linkedText(chosen)
  const tooMany = chosen.length > BATCH_MAX

  useEffect(() => {
    const node = bar.current
    if (!node) return
    const observer = new ResizeObserver(() => setHeight(node.offsetHeight))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  function apply() {
    if (!target || chosen.length === 0 || tooMany) return
    batch.mutate(
      {
        fingerprints: chosen.map((t) => t.fingerprint),
        category_id: target.id,
        reason: reason.trim(),
      },
      {
        onSuccess: (result) =>
          onDone({ text: resultText(result, target.name), entryId: result.entry_id }),
      },
    )
  }

  const groups = categoryGroups(options.categories)
  return (
    <>
      <div aria-hidden="true" style={{ height }} />
      <div
        ref={bar}
        role="region"
        aria-label={t('transactions.selection.region')}
        tabIndex={-1}
        {...{ [BAR_ATTR]: '' }}
        style={{ left }}
        className="fixed right-0 bottom-0 z-30 border-t border-border bg-card px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] shadow-[0_-8px_24px_rgba(27,29,33,0.12)] outline-none sm:px-10"
      >
        <div className="mx-auto flex max-w-[1400px] flex-col gap-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-sm font-semibold tabular-nums" aria-live="polite">
              {counterText(chosen)}
            </span>
            {visible > 0 && !allVisibleChosen && (
              <button
                type="button"
                onClick={onSelectAll}
                className={cn('min-h-11 rounded-md px-1 text-[13px] font-semibold text-primary', FOCUS)}
              >
                {t('transactions.selection.selectAll', { count: visible })}
              </button>
            )}
          </div>
          {(options.notice || linked || tooMany) && (
            <p className="text-[13px] text-ink-2">
              {[
                options.notice,
                linked,
                tooMany ? t('transactions.selection.tooMany', { max: BATCH_MAX }) : null,
              ]
                .filter(Boolean)
                .join(' ')}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label={t('transactions.selection.newCategory')}
              value={categoryId}
              onChange={(event) => setCategoryId(event.target.value)}
              className={cn(CONTROL, 'flex-[1_1_200px] font-semibold')}
            >
              <option value={NONE}>{t('transactions.selection.changeTo')}</option>
              {groups.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.names.map((name) => {
                    const found = options.categories.find((c) => c.name === name)
                    return found ? (
                      <option key={found.id} value={String(found.id)}>
                        {name}
                      </option>
                    ) : null
                  })}
                </optgroup>
              ))}
            </select>
            <input
              type="text"
              aria-label={t('transactions.selection.reason')}
              placeholder={t('transactions.selection.reason')}
              maxLength={REASON_MAX}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className={cn(CONTROL, 'flex-[2_1_220px]')}
            />
            <div className="flex flex-[1_0_auto] justify-end gap-2">
              <button
                type="button"
                onClick={onCancel}
                className={cn(ACTION, 'border border-border bg-card text-foreground hover:bg-muted')}
              >
                {t('transactions.cancel')}
              </button>
              <button
                type="button"
                onClick={apply}
                disabled={!target || chosen.length === 0 || tooMany || batch.isPending}
                className={cn(
                  ACTION,
                  'bg-primary text-primary-foreground hover:bg-primary/85 disabled:opacity-50',
                )}
              >
                {batch.isPending
                  ? t('transactions.selection.changing')
                  : t('transactions.selection.change')}
              </button>
            </div>
          </div>
          {batch.isError && (
            <p role="alert" className="text-[13px] font-semibold text-up">
              {t('transactions.selection.error', { message: batch.error.message })}
            </p>
          )}
          <ReserveBatch chosen={chosen} onDone={onDone} />
        </div>
      </div>
    </>
  )
}

/** Where `main` starts (right of the side menu; 0 when the menu is on top): the bar lines up
 * with the content and does not cover the menu. */
function useMainLeft(): number {
  const [left, setLeft] = useState(0)
  useEffect(() => {
    const main = document.querySelector('main')
    if (!main) return
    const measure = () => setLeft(Math.max(0, main.getBoundingClientRect().left))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(main)
    window.addEventListener('resize', measure)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [])
  return left
}

interface BatchNoticeProps {
  note: BatchNote
  onClose: () => void
}

/** The result of the last batch. It takes the focus when it appears; the link to the log only
 * shows when an entry was recorded. */
export function BatchNotice({ note, onClose }: BatchNoticeProps) {
  const box = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    box.current?.focus()
  }, [note])
  return (
    <p
      ref={box}
      role="status"
      tabIndex={-1}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-primary/30 bg-[#F6FAF8] px-4 py-2.5 text-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
    >
      <span>{note.text}</span>
      {note.entryId !== null && (
        <Link to="/log" className="font-semibold text-primary">
          {t('transactions.selection.seeLog')}
        </Link>
      )}
      <button
        type="button"
        onClick={onClose}
        className={cn(
          'ml-auto min-h-11 rounded-md px-2 text-[13px] font-semibold text-muted-foreground hover:text-foreground',
          FOCUS,
        )}
      >
        {t('transactions.close')}
      </button>
    </p>
  )
}
