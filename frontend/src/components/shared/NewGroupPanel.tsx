import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router'
import { PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { CandidatePicker } from '@/components/transactions/CandidatePicker'
import { Action, LoadFailure } from '@/components/transactions/linkParts'
import { Skeleton } from '@/components/ui/skeleton'
import type { Selection } from '@/lib/accountFilter'
import { linkPagePath } from '@/lib/links'
import { useNewGroupCandidates } from '@/lib/queries'
import { cn } from '@/lib/utils'

interface NewGroupPanelProps {
  id: string
  selection: Selection
  /** La URL a la que vuelve «Volver» desde la pantalla del gasto elegido. */
  from: string
  onClose: () => void
}

/** «Nuevo grupo…»: los gastos sin compartir de los últimos 120 días, arriba los que el servidor
 * sugiere (`primary`: comidas, salidas y compras de RD$ 2,000 o más); elegir uno abre su
 * pantalla, donde «Compartir» (reparto y «Con quién») ya está abierto. Al abrir, el foco va al
 * buscador (o al panel mientras carga); al cerrar vuelve a donde estaba (el botón que lo
 * abrió). */
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
      aria-label="Nuevo grupo"
      className={cn(
        PANEL,
        'flex max-w-[960px] min-w-0 flex-col gap-3 px-5 py-4 outline-none sm:px-6',
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className={PANEL_TITLE}>Nuevo grupo</h2>
        <Action onClick={onClose}>Cerrar</Action>
      </div>
      <p className="text-[13px] text-muted-foreground">
        Elige el gasto que compartiste (de los últimos 120 días); luego dices cómo se reparte
        y con quién. Arriba, comidas, salidas y compras de RD$ 2,000 o más; lo demás, en «Ver
        más» o con el buscador.
      </p>
      {candidates.isError && <LoadFailure what="los gastos" error={candidates.error} />}
      {candidates.isPending && <Skeleton className="h-32 rounded-xl" />}
      {candidates.data &&
        (candidates.data.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            No hay gastos sin compartir en los últimos 120 días.
          </p>
        ) : (
          <CandidatePicker
            items={candidates.data}
            label="Gastos sin compartir"
            action={(item) => (
              <Action
                label={`Compartir ${item.merchant}`}
                onClick={() => navigate(linkPagePath(item.fingerprint), { state: { from } })}
              >
                Compartir…
              </Action>
            )}
          />
        ))}
    </section>
  )
}
