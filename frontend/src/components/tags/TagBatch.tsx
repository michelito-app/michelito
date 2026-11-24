import { t } from '@/i18n'
import type { Tx } from '@/lib/api'
import { useTagTransactions } from '@/lib/tagQueries'
import type { BatchNote } from '@/lib/useTxSelection'
import { TagPicker } from './TagPicker'

interface TagBatchProps {
  chosen: Tx[]
  onDone: (note: BatchNote) => void
}

/** In selection mode: "Tag…" every chosen row at once (one log entry). */
export function TagBatch({ chosen, onDone }: TagBatchProps) {
  const tag = useTagTransactions()
  if (chosen.length === 0) return null
  return (
    <TagPicker
      label={t('tags.selection.tag')}
      busy={tag.isPending}
      onPick={(id) =>
        tag.mutate(
          { id, fingerprints: chosen.map((tx) => tx.fingerprint) },
          {
            onSuccess: (result) =>
              onDone({ text: t('tags.selection.done', { count: result.added }), entryId: result.entry_id }),
          },
        )
      }
    />
  )
}
