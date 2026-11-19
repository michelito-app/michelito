import { useState, type ReactNode } from 'react'
import type { Candidate } from '@/lib/api'
import { shownCandidates } from '@/lib/picker'
import { Action, FIELD, LinkedRow, PickList } from './linkParts'

interface CandidatePickerProps {
  items: Candidate[]
  /** Nombre de la lista (lectores de pantalla y buscador). */
  label: string
  /** Con casillas: lo elegido y cómo cambia. */
  chosen?: ReadonlySet<string>
  onToggle?: (fingerprint: string) => void
  /** Sin casillas: la acción de cada opción (p. ej. «Enlazar»). */
  action?: (item: Candidate) => ReactNode
}

/** Selector de un vínculo: buscador (texto o monto, en toda la lista), las primeras opciones
 * que el servidor marcó y el resto tras «Ver más (N)». */
export function CandidatePicker({ items, label, chosen, onToggle, action }: CandidatePickerProps) {
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState(false)
  const { visible, more } = shownCandidates(items, query)
  const searching = query.trim() !== ''
  const shown = expanded ? [...visible, ...more] : visible

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <input
        type="search"
        aria-label={`Buscar en ${label.toLowerCase()}`}
        placeholder="Buscar por comercio, cuenta o monto"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        className={FIELD}
      />
      {searching && visible.length === 0 && (
        <p className="text-[13px] text-muted-foreground">Nada coincide con «{query.trim()}».</p>
      )}
      {!searching && visible.length === 0 && !expanded && (
        <p className="text-[13px] text-muted-foreground">
          Nada encaja de lleno: lo demás está en «Ver más».
        </p>
      )}
      {shown.length > 0 &&
        (chosen && onToggle ? (
          <PickList items={shown} chosen={chosen} onToggle={onToggle} label={label} />
        ) : (
          <ul aria-label={label} className="flex flex-col gap-2">
            {shown.map((item) => (
              <LinkedRow key={item.fingerprint} item={item} action={action?.(item)} />
            ))}
          </ul>
        ))}
      {more.length > 0 && (
        <div>
          <Action onClick={() => setExpanded((v) => !v)}>
            {expanded ? 'Ver menos' : `Ver más (${more.length})`}
          </Action>
        </div>
      )}
    </div>
  )
}
