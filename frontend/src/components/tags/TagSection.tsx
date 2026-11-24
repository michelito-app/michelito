import { X } from 'lucide-react'
import { Link } from 'react-router'
import { t } from '@/i18n'
import type { Tx } from '@/lib/api'
import { useTagTransactions, useUntagTransactions } from '@/lib/tagQueries'
import { canRemove } from '@/lib/tags'
import { TagPicker } from './TagPicker'

/** A transaction's tags as chips (one from its group, loan or plan cannot be removed here)
 * and "Add tag". */
export function TagSection({ tx }: { tx: Tx }) {
  const chips = tx.tags ?? []
  const add = useTagTransactions()
  const remove = useUntagTransactions()
  return (
    <section aria-label={t('tags.page.title')} className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase">
        {t('tags.page.title')}
      </h3>
      {chips.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {chips.map((chip) => (
            <li key={chip.id} className="flex items-center gap-1 rounded-full border border-border bg-card py-1 pr-1 pl-3 text-[13px]">
              <Link to={`/tags/${chip.id}`} className="hover:underline">
                {chip.name}
              </Link>
              {canRemove(chip) ? (
                <button
                  type="button"
                  aria-label={t('tags.chip.removeLabel', { name: chip.name })}
                  onClick={() => remove.mutate({ id: chip.id, fingerprints: [tx.fingerprint] })}
                  className="flex size-7 items-center justify-center rounded-full text-muted-foreground hover:bg-muted"
                >
                  <X size={14} aria-hidden="true" />
                </button>
              ) : (
                <span className="w-2" />
              )}
            </li>
          ))}
        </ul>
      )}
      <TagPicker
        label={t('tags.chip.add')}
        exclude={new Set(chips.map((chip) => chip.id))}
        busy={add.isPending}
        onPick={(id) => add.mutate({ id, fingerprints: [tx.fingerprint] })}
      />
    </section>
  )
}
