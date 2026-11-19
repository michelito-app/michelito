import { useState } from 'react'
import { Link } from 'react-router'
import { FOCUS, ROW_DIVIDER } from '@/components/summary/styles'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  affectedText,
  entryHref,
  entryLine,
  kindLabel,
  type LogEntry,
  REASON_MAX,
  timeText,
  undoNote,
} from '@/lib/log'
import { useSaveReason, useUndo } from '@/lib/logQueries'
import { cn } from '@/lib/utils'

const SMALL = 'h-11 rounded-xl px-4 text-sm font-semibold'
const OUTLINE = cn(SMALL, 'border-[#D6D6D0] bg-card text-ink-2')

interface LogEntryRowProps {
  entry: LogEntry
  /** En el historial de una transacción no hace falta el enlace a ella. */
  showLink?: boolean
}

/** Una entrada en una línea legible, con su tipo, cuántas transacciones tocó, el autor, el
 * enlace, el motivo (editable) y «Deshacer» (o por qué no se puede). */
export function LogEntryRow({ entry, showLink = true }: LogEntryRowProps) {
  const line = entryLine(entry)
  // En el historial del detalle, el nombre accesible va por número: el comercio ya está en el
  // título del detalle (y así no choca con el botón de la fila en la lista).
  const name = showLink ? line : `el cambio n.º ${entry.id}`
  const href = showLink ? entryHref(entry) : null
  const undo = useUndo()
  const note = undoNote(entry)
  return (
    <li className={cn(ROW_DIVIDER, 'flex min-w-0 flex-col gap-1.5 py-3')}>
      <p className="text-sm font-semibold break-words text-foreground">{line}</p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
        <span>{timeText(new Date(entry.at))}</span>
        <span aria-hidden="true">·</span>
        <span>{kindLabel(entry.kind)}</span>
        <span aria-hidden="true">·</span>
        <span>{affectedText(entry.affected)}</span>
        {entry.author === 'claude' && (
          <Badge className="border border-primary/30 bg-secondary text-secondary-foreground">
            Claude
          </Badge>
        )}
        {entry.undone && <Badge className="bg-muted text-muted-foreground">Deshecha</Badge>}
      </div>
      <Reason entry={entry} line={name} />
      <div className="flex flex-wrap items-center gap-2">
        {href && (
          <Link
            to={href}
            className={cn(
              '-mx-2 flex min-h-11 items-center rounded-md px-2 text-[13px] font-semibold text-primary no-underline hover:bg-muted/60',
              FOCUS,
            )}
          >
            {entry.target_type === 'comercio' ? 'Ver el comercio' : 'Ver la transacción'}
          </Link>
        )}
        {entry.can_undo && (
          <Button
            variant="outline"
            className={OUTLINE}
            aria-label={`Deshacer: ${name}`}
            disabled={undo.isPending}
            onClick={() => undo.mutate(entry.id)}
          >
            {undo.isPending ? 'Deshaciendo…' : 'Deshacer'}
          </Button>
        )}
      </div>
      {note && !entry.undone && <p className="text-[13px] text-muted-foreground">{note}</p>}
      {undo.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo deshacer: {undo.error.message}
        </p>
      )}
    </li>
  )
}

/** El motivo: se escribe después, desde aquí (nunca se pide al guardar). */
function Reason({ entry, line }: { entry: LogEntry; line: string }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(entry.reason ?? '')
  const save = useSaveReason()
  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-x-2 text-[13px]">
        {entry.reason && <span className="break-words text-ink-2">Motivo: {entry.reason}</span>}
        <button
          type="button"
          aria-label={`${entry.reason ? 'Editar' : 'Escribir'} motivo: ${line}`}
          onClick={() => {
            setText(entry.reason ?? '')
            setEditing(true)
          }}
          className={cn(
            '-mx-2 flex min-h-11 items-center rounded-md px-2 font-semibold text-primary hover:bg-muted/60',
            FOCUS,
          )}
        >
          {entry.reason ? 'Editar motivo' : 'Escribir motivo'}
        </button>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <textarea
        aria-label={`Motivo: ${line}`}
        value={text}
        maxLength={REASON_MAX}
        rows={2}
        placeholder="Por qué lo cambiaste"
        onChange={(event) => setText(event.target.value)}
        className="min-h-11 w-full resize-y rounded-xl border border-[#D6D6D0] bg-card px-3 py-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          className={SMALL}
          disabled={save.isPending}
          onClick={() =>
            save.mutate({ id: entry.id, reason: text }, { onSuccess: () => setEditing(false) })
          }
        >
          Guardar motivo
        </Button>
        <Button variant="outline" className={OUTLINE} onClick={() => setEditing(false)}>
          Cancelar
        </Button>
        <span className="text-xs text-muted-foreground">
          {text.length}/{REASON_MAX}
        </span>
      </div>
      {save.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo guardar: {save.error.message}
        </p>
      )}
    </div>
  )
}
