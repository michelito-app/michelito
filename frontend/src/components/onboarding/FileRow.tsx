import { CircleAlert, CircleCheck, FileText, LoaderCircle, LockKeyhole } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import {
  REQUESTABLE_BANKS,
  type RequestableBank,
  type UploadFile,
  bankName,
  failed,
  opened,
  readLine,
  requestBank,
  stateText,
} from '@/lib/onboarding'
import { cn } from '@/lib/utils'

function StateIcon({ file }: { file: UploadFile }) {
  if (opened(file)) return <CircleCheck size={18} className="text-down" aria-hidden="true" />
  if (file.state === 'locked') return <LockKeyhole size={18} aria-hidden="true" />
  if (failed(file)) return <CircleAlert size={18} className="text-up" aria-hidden="true" />
  if (file.state === 'reading') {
    return <LoaderCircle size={18} className="animate-spin" aria-hidden="true" />
  }
  return <FileText size={18} aria-hidden="true" />
}

/** One file of the processing screen: its name and state; once read, bank · account · month ·
 * transactions and "squared to the cent"; an unsupported one offers "notify me when it is
 * supported". */
export function FileRow({ file }: { file: UploadFile }) {
  return (
    <li data-file-state={file.state} className="flex gap-3 border-b border-border py-3 last:border-b-0">
      <span className="mt-0.5 shrink-0 text-ink-2">
        <StateIcon file={file} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="truncate text-sm font-semibold">{file.name}</p>
        {file.reads.map((read, index) => (
          <p key={index} className="text-sm text-ink-2">
            {readLine(read)}
          </p>
        ))}
        <p
          className={cn(
            'text-[13px]',
            opened(file) ? 'font-semibold text-down' : failed(file) ? 'text-up' : 'text-muted-foreground',
          )}
        >
          {stateText(file.state)}
        </p>
        {file.state === 'unsupported' && <BankRequest />}
      </div>
    </li>
  )
}

/** "Notify me when it is supported": only the bank's name (from a fixed list) is recorded. */
function BankRequest() {
  const [open, setOpen] = useState(false)
  const [bank, setBank] = useState<RequestableBank>(REQUESTABLE_BANKS[0])
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'failed'>('idle')
  const [error, setError] = useState<string | null>(null)
  const id = useId()

  async function send() {
    setState('busy')
    try {
      await requestBank(bank)
      setState('done')
    } catch (failure) {
      setError((failure as Error).message)
      setState('failed')
    }
  }

  if (state === 'done') {
    return <p role="status" className="text-[13px] text-ink-2">{t('onboarding.request.done')}</p>
  }
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn('min-h-11 self-start text-[13px] font-semibold text-primary underline', FOCUS)}
      >
        {t('onboarding.request.open')}
      </button>
    )
  }
  return (
    <div className="flex flex-wrap items-end gap-2 pt-1">
      <label htmlFor={id} className="flex flex-col gap-1 text-[13px] font-medium">
        {t('onboarding.request.which')}
        <select
          id={id}
          value={bank}
          onChange={(event) => setBank(event.target.value as RequestableBank)}
          className={cn('h-11 rounded-lg border border-input bg-card px-2 text-sm', FOCUS)}
        >
          {REQUESTABLE_BANKS.map((key) => (
            <option key={key} value={key}>
              {bankName(key)}
            </option>
          ))}
        </select>
      </label>
      <Button className="h-11 px-4" disabled={state === 'busy'} onClick={() => void send()}>
        {t('onboarding.request.send')}
      </Button>
      {error && (
        <p role="alert" className="w-full text-[13px] text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
