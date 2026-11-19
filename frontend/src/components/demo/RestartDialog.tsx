import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { Modal } from '@/components/ui/modal'
import { restartCopy } from '@/lib/demo'

/** Confirms "Start over": the visitor's copy is replaced by a new one from the template and the
 * page reloads (so no screen keeps data from the previous copy). */
export function RestartDialog({ onClose }: { onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function restart() {
    setBusy(true)
    setError(null)
    try {
      await restartCopy()
      window.location.assign('/')
    } catch (failure) {
      setBusy(false)
      setError((failure as Error).message)
    }
  }

  return (
    <Modal title={t('demo.restart.title')} onClose={onClose}>
      <p className="text-sm">
        {t('demo.restart.body')}
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" className="h-11 px-4" onClick={onClose}>
          {t('demo.restart.cancel')}
        </Button>
        <Button className="h-11 px-4" disabled={busy} onClick={() => void restart()}>
          {busy ? t('demo.restart.starting') : t('demo.restart.confirm')}
        </Button>
      </div>
    </Modal>
  )
}
