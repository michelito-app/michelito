import { useQueryClient } from '@tanstack/react-query'
import { FileUp } from 'lucide-react'
import { type ChangeEvent, type DragEvent, useEffect, useId, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { FileRow } from '@/components/onboarding/FileRow'
import { PasswordPrompt } from '@/components/onboarding/PasswordPrompt'
import { SharePrompt } from '@/components/onboarding/SharePrompt'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import {
  type Job,
  MAX_FILES,
  MAX_FILE_MB,
  type Onboarding,
  POLL_MS,
  type SharedFile,
  fetchJob,
  fetchLatestJob,
  filesProblem,
  lockedFiles,
  noneSquared,
  onboardingKey,
  peekShare,
  startUpload,
  takeShareToken,
} from '@/lib/onboarding'
import { request } from '@/lib/api'
import { useIsMobile } from '@/lib/useMobile'
import { cn } from '@/lib/utils'

// The share token is taken out of the address once per page load (a StrictMode double render
// must not lose it).
let shared: { token: string | null } | null = null
function initialShare(): string | null {
  shared ??= { token: takeShareToken() }
  return shared.token
}

interface UploadFlowProps {
  /** The public demo, for the exit when nothing squared. */
  demoUrl?: string
}

/** Upload several PDFs (drag and drop on a computer, the file picker on a phone) and follow
 * each one live: reading → bank · account · month · transactions → "squared to the cent", or why
 * it was not kept. "See my summary" appears with the first statement that squares. */
export function UploadFlow({ demoUrl }: UploadFlowProps) {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [share, setShare] = useState<{ token: string; files: SharedFile[] } | null>(null)
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const id = useId()
  const mobile = useIsMobile()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Back to where the person left it (an unfinished upload, or the demo and back).
  useEffect(() => {
    let alive = true
    const token = initialShare()
    if (token) {
      peekShare(token)
        .then((files) => {
          if (alive) setShare({ token, files })
        })
        .catch((failure: Error) => {
          if (alive) setError(failure.message)
        })
    }
    fetchLatestJob()
      .then((latest) => {
        const pending = latest && (!latest.done || lockedFiles(latest).length > 0 || latest.squared === 0)
        if (alive && latest && pending) setJob(latest)
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (!job || job.done) return
    const timer = window.setTimeout(() => {
      fetchJob(job.id)
        .then(setJob)
        .catch((failure: Error) => setError(failure.message))
    }, POLL_MS)
    return () => window.clearTimeout(timer)
  }, [job])

  async function send(files: File[]) {
    if (!files.length) return
    const problem = filesProblem(files)
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    try {
      setJob(await startUpload(files))
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function picked(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    void send(files)
  }

  function dropped(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    void send(Array.from(event.dataTransfer.files))
  }

  async function openSummary() {
    await queryClient.invalidateQueries()
    const state = await queryClient.fetchQuery({
      queryKey: onboardingKey,
      queryFn: () => request<Onboarding>('/api/onboarding'),
    })
    navigate(state.landing ? `/?month=${state.landing}` : '/', { replace: true })
  }

  const finished = job !== null && job.done
  const nothing = job !== null && noneSquared(job) && lockedFiles(job).length === 0
  return (
    <div className="flex flex-col gap-4">
      {share && (
        <SharePrompt
          token={share.token}
          files={share.files}
          onImported={setJob}
          onDone={() => setShare(null)}
        />
      )}
      <section
        aria-label={t('onboarding.upload.label')}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={dropped}
        className={cn(
          PANEL,
          'flex flex-col items-center gap-3 border-dashed px-5 py-7 text-center',
          dragging && 'border-primary bg-secondary',
        )}
      >
        <FileUp size={28} className="text-primary" aria-hidden="true" />
        {!mobile && <p className="text-sm font-semibold">{t('onboarding.upload.drop')}</p>}
        <input
          ref={input}
          id={id}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="sr-only"
          onChange={picked}
        />
        <Button className="h-12 px-6 text-base" disabled={busy} onClick={() => input.current?.click()}>
          {busy ? t('onboarding.upload.uploading') : t('onboarding.upload.pick')}
        </Button>
        <p className="text-[13px] text-muted-foreground">
          {t('onboarding.upload.hint', { count: MAX_FILES, megabytes: MAX_FILE_MB })}
        </p>
      </section>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {job && (
        <section aria-label={t('onboarding.upload.files')} className={cn(PANEL, 'px-5 py-2')}>
          <ul aria-live="polite">
            {job.files.map((file) => (
              <FileRow key={file.id} file={file} />
            ))}
          </ul>
        </section>
      )}
      {job && finished && lockedFiles(job).length > 0 && <PasswordPrompt job={job} onTried={setJob} />}
      {job && job.squared > 0 && (
        <div className="flex flex-col gap-2">
          <Button className="h-12 text-base" onClick={() => void openSummary()}>
            {t('onboarding.result.open')}
          </Button>
          <p className="text-[13px] text-muted-foreground">{t('onboarding.result.nudge')}</p>
        </div>
      )}
      {nothing && (
        <section role="status" className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}>
          <h2 className="text-[17px] font-[650] tracking-tight">{t('onboarding.result.none')}</h2>
          <p className="text-sm text-ink-2">{t('onboarding.result.noneLead')}</p>
          <div className="flex flex-wrap gap-2">
            <Button className="h-11 px-4" onClick={() => input.current?.click()}>
              {t('onboarding.result.retry')}
            </Button>
            {demoUrl && (
              <a
                href={demoUrl}
                className={cn(
                  'inline-flex min-h-11 items-center rounded-lg border border-border px-4 text-sm font-medium no-underline',
                  FOCUS,
                )}
              >
                {t('onboarding.gate.demo')}
              </a>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
