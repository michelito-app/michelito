import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router'
import { PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { CandidatePicker } from '@/components/transactions/CandidatePicker'
import { Action, LoadFailure } from '@/components/transactions/linkParts'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import { linkPagePath } from '@/lib/links'
import { useNewGroupCandidates } from '@/lib/queries'
import { cn } from '@/lib/utils'

interface NewGroupPanelProps {
  id: string
  selection: Selection
  /** The URL "Back" returns to from the chosen expense's screen. */
  from: string
  onClose: () => void
}

/** "New group…": the unshared expenses of the last 120 days, on top the ones the server
 * suggests (`primary`: meals, outings and purchases of RD$ 2,000 or more); choosing one opens its
 * screen, where "Share" (split and "With whom") is already open. On opening, focus goes to the
 * search box (or to the panel while loading); on closing it returns to where it was (the button
 * that opened it). */
export function NewGroupPanel({ id, selection, from, onClose }: NewGroupPanelProps) {
  const navigate = useNavigate()
  const candidates = useNewGroupCandidates(selection, true)
  const panel = useRef<HTMLElement>(null)
  const searched = useRef(false)
  const loaded = candidates.data !== undefined

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    panel.current?.focus()
    return () => opener?.focus()
  }, [])

  useEffect(() => {
    if (!loaded || searched.current) return
    const search = panel.current?.querySelector<HTMLInputElement>('input[type="search"]')
    if (search) {
      searched.current = true
      search.focus()
    }
  }, [loaded])

  return (
    <section
      ref={panel}
      id={id}
      tabIndex={-1}
      aria-label={t('shared.newGroup.title')}
      className={cn(
        PANEL,
        'flex max-w-[960px] min-w-0 flex-col gap-3 px-5 py-4 outline-none sm:px-6',
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className={PANEL_TITLE}>{t('shared.newGroup.title')}</h2>
        <Action onClick={onClose}>{t('shared.newGroup.close')}</Action>
      </div>
      <p className="text-[13px] text-muted-foreground">{t('shared.newGroup.help')}</p>
      {candidates.isError && (
        <LoadFailure what={t('shared.newGroup.load')} error={candidates.error} />
      )}
      {candidates.isPending && <Skeleton className="h-32 rounded-xl" />}
      {candidates.data &&
        (candidates.data.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            {t('shared.newGroup.none')}
          </p>
        ) : (
          <CandidatePicker
            items={candidates.data}
            label={t('shared.newGroup.listLabel')}
            action={(item) => (
              <Action
                label={t('shared.newGroup.shareLabel', { merchant: item.merchant })}
                onClick={() => navigate(linkPagePath(item.fingerprint), { state: { from } })}
              >
                {t('shared.newGroup.share')}
              </Action>
            )}
          />
        ))}
    </section>
  )
}
