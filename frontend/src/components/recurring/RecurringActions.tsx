import { Check } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { MarkBody, MarkStatus, Recurring, RecurringGroupKey, RecurringItem } from '@/lib/api'
import { useJoinRecurring, useMarkRecurring, useSeparateRecurring } from '@/lib/queries'
import {
  GROUP_OPTIONS,
  groupBody,
  installmentsBody,
  joinTargets,
  MAX_INSTALLMENTS,
  parseInstallments,
  separableMembers,
  statusBody,
} from '@/lib/recurring'
import { cn } from '@/lib/utils'

interface RecurringActionsProps {
  item: RecurringItem
  id: string
  overview: Recurring
}

const ACTION =
  'inline-flex min-h-11 cursor-pointer items-center justify-center gap-1.5 rounded-xl border px-3.5 text-sm font-semibold transition-colors disabled:cursor-default disabled:opacity-60'
const IDLE = 'border-[#D6D6D0] bg-card text-ink-2 hover:bg-muted'
const PRESSED = 'border-primary bg-secondary text-secondary-foreground'

/** The user's marks on a recurring item: status, installments left, "Join with…" and
 * "Separate". */
export function RecurringActions({ item, id, overview }: RecurringActionsProps) {
  const ids = useId()
  const mark = useMarkRecurring()
  const join = useJoinRecurring()
  const separate = useSeparateRecurring()
  const [editing, setEditing] = useState(false)
  const [joining, setJoining] = useState(false)
  const targets = joinTargets(overview, item)
  const [target, setTarget] = useState('')
  const [grouping, setGrouping] = useState(false)
  const [group, setGroup] = useState<RecurringGroupKey | ''>(
    () => GROUP_OPTIONS.find((g) => g.key === item.group_key)?.key ?? '',
  )
  const separable = separableMembers(item)
  const [draft, setDraft] = useState(() => String(item.installments_left ?? ''))
  const [invalid, setInvalid] = useState(false)
  const [savedNote, setSavedNote] = useState<string | null>(null)

  function send(body: MarkBody, note: string) {
    setSavedNote(null)
    mark.mutate(body, { onSuccess: () => setSavedNote(note) })
  }

  function setStatus(status: MarkStatus | null, note: string) {
    send(statusBody(item, status), note)
  }

  function saveInstallments() {
    const left = parseInstallments(draft)
    setInvalid(left === null)
    if (left === null) return
    send(installmentsBody(item, left), t('recurring.saved.installments'))
  }

  function clearInstallments() {
    setDraft('')
    setInvalid(false)
    send(installmentsBody(item, null), t('recurring.saved.installmentsCleared'))
  }

  function saveJoin() {
    const chosen = targets.find((option) => option.key === target)
    if (!chosen) return
    setSavedNote(null)
    join.mutate(
      { merchant: item.merchant, target: chosen.key },
      { onSuccess: () => setSavedNote(t('recurring.saved.joined', { name: chosen.name })) },
    )
  }

  function split(member: string) {
    setSavedNote(null)
    separate.mutate(member, {
      onSuccess: () => setSavedNote(t('recurring.saved.separated', { member })),
    })
  }

  const busy = mark.isPending || join.isPending || separate.isPending
  const failure = mark.error ?? join.error ?? separate.error
  return (
    <div
      id={id}
      role="group"
      aria-label={t('recurring.actions.label', { name: item.name })}
      className="flex flex-col gap-3 border-t border-[#EFEFEA] bg-[#FAFAF8] px-4 py-4 sm:px-5"
    >
      <div className="flex flex-wrap gap-2">
        <StatusButton
          pressed={item.mark === 'confirmed'}
          disabled={busy}
          onClick={() => setStatus('confirmed', t('recurring.saved.isRecurring'))}
        >
          {t('recurring.actions.isRecurring')}
        </StatusButton>
        <StatusButton
          disabled={busy}
          onClick={() => setStatus('dismissed', t('recurring.saved.notRecurring'))}
        >
          {t('recurring.actions.notRecurring')}
        </StatusButton>
        <StatusButton
          pressed={item.mark === 'cancelled'}
          disabled={busy}
          onClick={() => setStatus('cancelled', t('recurring.saved.cancelled'))}
        >
          {t('recurring.actions.cancelled')}
        </StatusButton>
        <button
          type="button"
          aria-expanded={editing}
          aria-controls={`${ids}-installments`}
          disabled={busy}
          onClick={() => setEditing((open) => !open)}
          className={cn(ACTION, editing ? PRESSED : IDLE, FOCUS)}
        >
          {t('recurring.actions.installments')}
        </button>
        <button
          type="button"
          aria-expanded={grouping}
          aria-controls={`${ids}-group`}
          disabled={busy}
          onClick={() => setGrouping((open) => !open)}
          className={cn(ACTION, grouping ? PRESSED : IDLE, FOCUS)}
        >
          {t('recurring.actions.group')}
        </button>
        {targets.length > 0 && (
          <button
            type="button"
            aria-expanded={joining}
            aria-controls={`${ids}-join`}
            disabled={busy}
            onClick={() => setJoining((open) => !open)}
            className={cn(ACTION, joining ? PRESSED : IDLE, FOCUS)}
          >
            {t('recurring.actions.join')}
          </button>
        )}
        {item.mark !== null && (
          <button
            type="button"
            disabled={busy}
            onClick={() => setStatus(null, t('recurring.saved.markCleared'))}
            className={cn(ACTION, 'border-transparent bg-transparent text-ink-2 hover:bg-muted', FOCUS)}
          >
            {t('recurring.actions.clearMark')}
          </button>
        )}
      </div>

      {editing && (
        <form
          id={`${ids}-installments`}
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            saveInstallments()
          }}
        >
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
            {t('recurring.actions.installmentsLabel')}
            <input
              type="number"
              inputMode="numeric"
              min={0}
              max={MAX_INSTALLMENTS}
              step={1}
              value={draft}
              aria-invalid={invalid}
              aria-describedby={invalid ? `${ids}-hint` : undefined}
              onChange={(event) => {
                setDraft(event.target.value)
                setInvalid(false)
              }}
              className="h-11 w-28 rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm font-medium text-foreground tabular-nums outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30 aria-invalid:border-up"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className={cn(ACTION, 'border-primary bg-primary text-primary-foreground hover:bg-primary/85', FOCUS)}
          >
            {t('recurring.actions.saveInstallments')}
          </button>
          {item.installments_left !== null && (
            <button
              type="button"
              disabled={busy}
              onClick={clearInstallments}
              className={cn(ACTION, IDLE, FOCUS)}
            >
              {t('recurring.actions.clearInstallments')}
            </button>
          )}
          {invalid && (
            <p id={`${ids}-hint`} className="basis-full text-[13px] text-up-ink">
              {t('recurring.actions.installmentsHint', { max: MAX_INSTALLMENTS })}
            </p>
          )}
        </form>
      )}

      {grouping && (
        <form
          id={`${ids}-group`}
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            send(groupBody(item, group), t('recurring.saved.group'))
          }}
        >
          <label className="flex min-w-0 flex-[1_1_220px] flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
            {t('recurring.actions.groupLabel')}
            <select
              aria-label={t('recurring.actions.groupLabel')}
              value={group}
              onChange={(event) => setGroup(event.target.value as RecurringGroupKey | '')}
              className="h-11 w-full min-w-0 cursor-pointer rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm font-medium text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
            >
              <option value="">{t('recurring.actions.byCategory')}</option>
              {GROUP_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            disabled={busy}
            className={cn(ACTION, 'border-primary bg-primary text-primary-foreground hover:bg-primary/85', FOCUS)}
          >
            {t('recurring.actions.saveGroup')}
          </button>
        </form>
      )}

      {joining && (
        <form
          id={`${ids}-join`}
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            saveJoin()
          }}
        >
          <label className="flex min-w-0 flex-[1_1_220px] flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
            {t('recurring.actions.joinLabel')}
            <select
              aria-label={t('recurring.actions.joinLabel')}
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              className="h-11 w-full min-w-0 cursor-pointer rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm font-medium text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
            >
              <option value="">{t('recurring.actions.joinPlaceholder')}</option>
              {targets.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            disabled={busy || target === ''}
            className={cn(ACTION, 'border-primary bg-primary text-primary-foreground hover:bg-primary/85', FOCUS)}
          >
            {t('recurring.actions.joinSubmit')}
          </button>
          <p className="basis-full text-[13px] text-muted-foreground">
            {t('recurring.actions.joinHint')}
          </p>
        </form>
      )}

      {separable.length > 0 && (
        <ul aria-label={t('recurring.actions.membersOf', { name: item.name })} className="flex flex-col gap-1.5">
          {separable.map((member) => (
            <li key={member} className="flex items-center justify-between gap-3">
              <span className="min-w-0 text-[13px] text-ink-2 [overflow-wrap:anywhere]">
                {member}
              </span>
              <button
                type="button"
                aria-label={t('recurring.actions.separateNamed', { member })}
                disabled={busy}
                onClick={() => split(member)}
                className={cn(ACTION, IDLE, 'shrink-0', FOCUS)}
              >
                {t('recurring.actions.separate')}
              </button>
            </li>
          ))}
        </ul>
      )}

      {failure && (
        <p
          role="alert"
          className="rounded-[10px] border border-up/30 bg-up-soft px-3 py-2.5 text-[13px] text-up-ink"
        >
          {t('recurring.saveFailed', { message: failure.message })}
        </p>
      )}
      <p role="status" className="min-h-5 text-[13px] font-medium text-primary">
        {busy ? (
          <span className="text-muted-foreground">{t('recurring.saving')}</span>
        ) : (
          savedNote && (
            <span className="inline-flex items-center gap-1.5">
              <Check size={14} aria-hidden="true" />
              {savedNote}
            </span>
          )
        )}
      </p>
    </div>
  )
}

interface StatusButtonProps {
  pressed?: boolean
  disabled: boolean
  onClick: () => void
  children: ReactNode
}

function StatusButton({ pressed, disabled, onClick, children }: StatusButtonProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={cn(ACTION, pressed ? PRESSED : IDLE, FOCUS)}
    >
      {pressed && <Check size={15} aria-hidden="true" />}
      {children}
    </button>
  )
}
