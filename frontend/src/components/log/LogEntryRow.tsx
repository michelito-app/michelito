import { useState } from 'react'
import { Link } from 'react-router'
import { FOCUS, ROW_DIVIDER } from '@/components/summary/styles'
import { t } from '@/i18n'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  affectedText,
  entryHref,
  entryLine,
  kindLabel,
  linkLabel,
  type LogEntry,
  REASON_MAX,
  showsAffected,
  timeText,
  toggledText,
  undoNote,
} from '@/lib/log'
import { useRedo, useSaveReason, useUndo } from '@/lib/logQueries'
import { cn } from '@/lib/utils'

const SMALL = 'h-11 rounded-xl px-4 text-sm font-semibold'
const OUTLINE = cn(SMALL, 'border-[#D6D6D0] bg-card text-ink-2')

interface LogEntryRowProps {
  entry: LogEntry
  /** In a transaction's history the link to it is not needed. */
  showLink?: boolean
}

/** An entry as a readable line, with its kind, how many transactions it touched, the author, the
 * link, the reason (editable) and undo; an undone one says so and offers "Redo" (one row per
 * change: undoing and redoing toggles it, with "undone and redone N times"). */
export function LogEntryRow({ entry, showLink = true }: LogEntryRowProps) {
  const line = entryLine(entry)
  // In the detail's history the accessible name goes by number: the merchant is already in the
  // detail's title (and this way it does not clash with the row's button in the list).
  const name = showLink ? line : t('log.row.changeNumber', { id: entry.id })
  const href = showLink ? entryHref(entry) : null
  const undo = useUndo()
  const redo = useRedo()
  const note = undoNote(entry)
  const toggled = toggledText(entry)
  return (
    <li className={cn(ROW_DIVIDER, 'flex min-w-0 flex-col gap-1.5 py-3')}>
      <p className="text-sm font-semibold break-words text-foreground">{line}</p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
        <span>{timeText(new Date(entry.at))}</span>
        <span aria-hidden="true">·</span>
        <span>{kindLabel(entry.kind)}</span>
        {showsAffected(entry) && (
          <>
            <span aria-hidden="true">·</span>
            <span>{affectedText(entry.affected)}</span>
          </>
        )}
        {entry.author === 'claude' && (
          <Badge className="border border-primary/30 bg-secondary text-secondary-foreground">
            {t('log.row.claude')}
          </Badge>
        )}
        {entry.undone && <Badge className="bg-muted text-muted-foreground">{t('log.row.undoneBadge')}</Badge>}
        {toggled && <span data-testid="log-toggled">{toggled}</span>}
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
            {linkLabel(entry)}
          </Link>
        )}
        {entry.undone && entry.can_redo && (
          <Button
            variant="outline"
            className={OUTLINE}
            aria-label={t('log.row.redoNamed', { name })}
            disabled={redo.isPending}
            onClick={() => redo.mutate(entry.id)}
          >
            {redo.isPending ? t('log.row.redoing') : t('log.row.redo')}
          </Button>
        )}
        {!entry.undone && entry.can_undo && (
          <Button
            variant="outline"
            className={OUTLINE}
            aria-label={t('log.row.undoNamed', { name })}
            disabled={undo.isPending}
            onClick={() => undo.mutate(entry.id)}
          >
            {undo.isPending ? t('log.row.undoing') : t('log.row.undo')}
          </Button>
        )}
      </div>
      {note && <p className="text-[13px] text-muted-foreground">{note}</p>}
      {undo.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('log.row.undoFailed', { message: undo.error.message })}
        </p>
      )}
      {redo.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('log.row.redoFailed', { message: redo.error.message })}
        </p>
      )}
    </li>
  )
}

/** The reason: written afterwards, from here (it is never asked for when saving). */
function Reason({ entry, line }: { entry: LogEntry; line: string }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(entry.reason ?? '')
  const save = useSaveReason()
  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-x-2 text-[13px]">
        {entry.reason && (
          <span className="break-words text-ink-2">
            {t('log.reason.value', { reason: entry.reason })}
          </span>
        )}
        <button
          type="button"
          aria-label={t(entry.reason ? 'log.reason.editNamed' : 'log.reason.writeNamed', { line })}
          onClick={() => {
            setText(entry.reason ?? '')
            setEditing(true)
          }}
          className={cn(
            '-mx-2 flex min-h-11 items-center rounded-md px-2 font-semibold text-primary hover:bg-muted/60',
            FOCUS,
          )}
        >
          {entry.reason ? t('log.reason.edit') : t('log.reason.write')}
        </button>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <textarea
        aria-label={t('log.reason.fieldNamed', { line })}
        value={text}
        maxLength={REASON_MAX}
        rows={2}
        placeholder={t('log.reason.placeholder')}
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
          {t('log.reason.save')}
        </Button>
        <Button variant="outline" className={OUTLINE} onClick={() => setEditing(false)}>
          {t('log.reason.cancel')}
        </Button>
        <span className="text-xs text-muted-foreground">
          {text.length}/{REASON_MAX}
        </span>
      </div>
      {save.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('log.reason.saveFailed', { message: save.error.message })}
        </p>
      )}
    </div>
  )
}
