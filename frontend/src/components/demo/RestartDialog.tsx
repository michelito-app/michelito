import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/modal'
import { restartCopy } from '@/lib/demo'

/** Confirma «Empezar de nuevo»: la copia del visitante se cambia por una nueva de la plantilla
 * y la página se recarga (así ninguna pantalla se queda con datos de la copia anterior). */
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
    <Modal title="Empezar de nuevo" onClose={onClose}>
      <p className="text-sm">
        Se borran tus cambios en la demo y vuelves a los datos inventados del principio.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" className="h-11 px-4" onClick={onClose}>
          Cancelar
        </Button>
        <Button className="h-11 px-4" disabled={busy} onClick={() => void restart()}>
          {busy ? 'Empezando…' : 'Borrar mis cambios'}
        </Button>
      </div>
    </Modal>
  )
}
