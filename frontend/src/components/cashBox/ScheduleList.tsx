import { useState } from 'react'
import { Action, ConfirmBox, Failure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { CashBox, CashSchedule } from '@/lib/api'
import { scheduleText } from '@/lib/cashBox'
import { formatMoney } from '@/lib/links'
import { useChangeCashBox } from '@/lib/queries'
import { CashEntryForm } from './CashEntryForm'

interface ScheduleListProps {
  box: CashBox
  today: string
}

/** "Scheduled payments and collections": each schedule with how often and when it comes next, and
 * buttons to pause or resume, edit and delete; plus "Schedule a payment or collection…". */
export function ScheduleList({ box, today }: ScheduleListProps) {
  const [form, setForm] = useState<CashSchedule | 'new' | null>(null)
  return (
    <section aria-label={t('cashBox.schedule.title')} className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">{t('cashBox.schedule.title')}</h3>
      {box.schedules.length === 0 && (
        <p className="text-[13px] text-muted-foreground">{t('cashBox.schedule.none')}</p>
      )}
      {box.schedules.length > 0 && (
        <ul className="flex flex-col">
          {box.schedules.map((schedule) => (
            <ScheduleRow key={schedule.id} schedule={schedule} onEdit={() => setForm(schedule)} />
          ))}
        </ul>
      )}
      {form === null ? (
        <div>
          <Action onClick={() => setForm('new')}>{t('cashBox.action.schedule')}</Action>
        </div>
      ) : (
        <CashEntryForm
          key={form === 'new' ? 'new' : form.id}
          kind={form === 'new' ? 'expense' : form.kind === 'payment' ? 'expense' : 'income'}
          box={box}
          today={today}
          schedule={form}
          onDone={() => setForm(null)}
        />
      )}
    </section>
  )
}

function ScheduleRow({ schedule, onEdit }: { schedule: CashSchedule; onEdit: () => void }) {
  const change = useChangeCashBox()
  const [confirming, setConfirming] = useState(false)
  const sign = schedule.kind === 'payment' ? '−' : '+'
  return (
    <li
      data-testid="cash-schedule"
      className="flex flex-col gap-2 border-b border-[#F2F2EE] py-2.5 last:border-b-0"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-sm font-semibold break-words">
            {schedule.kind === 'payment'
              ? t('cashBox.schedule.payment')
              : t('cashBox.schedule.collection')}
            {' · '}
            {schedule.concept}
          </span>
          <span className="text-[13px] break-words text-ink-2">{scheduleText(schedule)}</span>
        </div>
        <span className="shrink-0 text-sm font-semibold tabular-nums">
          {sign}
          {formatMoney(schedule.amount_cents, schedule.currency)}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        <Action
          disabled={change.isPending}
          label={
            schedule.paused
              ? t('cashBox.schedule.resumeLabel', { concept: schedule.concept })
              : t('cashBox.schedule.pauseLabel', { concept: schedule.concept })
          }
          onClick={() =>
            change.mutate({ action: 'schedule-pause', id: schedule.id, paused: !schedule.paused })
          }
        >
          {schedule.paused ? t('cashBox.schedule.resume') : t('cashBox.schedule.pause')}
        </Action>
        <Action
          onClick={onEdit}
          label={t('cashBox.schedule.editLabel', { concept: schedule.concept })}
        >
          {t('cashBox.schedule.edit')}
        </Action>
        <Action
          onClick={() => setConfirming(true)}
          label={t('cashBox.schedule.deleteLabel', { concept: schedule.concept })}
        >
          {t('cashBox.schedule.delete')}
        </Action>
      </div>
      {confirming && (
        <ConfirmBox
          label={t('cashBox.schedule.deleteLabel', { concept: schedule.concept })}
          confirmLabel={t('cashBox.schedule.deleteYes')}
          busy={change.isPending}
          onConfirm={() => change.mutate({ action: 'schedule-delete', id: schedule.id })}
          onCancel={() => setConfirming(false)}
        >
          {t('cashBox.schedule.deleteConfirm')}
        </ConfirmBox>
      )}
      <Failure error={change.error} />
    </li>
  )
}
