// The detail's correction form (category, scope, one-off, note): its draft, what saving would
// send and the save itself. Shared by the desktop panel and the phone's sheets.
import { useState } from 'react'
import { t } from '@/i18n'
import type { Category, Tx } from '@/lib/api'
import { choosable } from '@/lib/categories'
import { useEditTransaction } from '@/lib/queries'
import { type Draft, editBody } from '@/lib/transactions'

function draftOf(tx: Tx): Draft {
  return { category: tx.category, oneOff: tx.one_off, scope: 'transaction', note: tx.note }
}

export interface Correction {
  draft: Draft
  change: (patch: Partial<Draft>) => void
  /** What saving would send; null when nothing changed. */
  body: ReturnType<typeof editBody>
  save: (onDone?: () => void) => void
  /** Restores the saved values (a sheet closed without saving). */
  discard: () => void
  edit: ReturnType<typeof useEditTransaction>
  savedNote: string | null
  /** The categories the picker offers (plus the one just created). */
  options: Category[]
  onCreated: (category: Category) => void
}

export function useCorrection(
  tx: Tx,
  categories: Category[],
  onSaved: (tx: Tx) => void,
): Correction {
  const [draft, setDraft] = useState<Draft>(() => draftOf(tx))
  // A new link (the cash box, for example) changes the category from outside the form.
  const [seenCategory, setSeenCategory] = useState(tx.category)
  if (seenCategory !== tx.category) {
    setSeenCategory(tx.category)
    setDraft((current) => ({ ...current, category: tx.category }))
  }
  const [savedNote, setSavedNote] = useState<string | null>(null)
  // The one just created, while the category list is fetched again.
  const [created, setCreated] = useState<Category | null>(null)
  // Without the ones only a link sets: the row's own, if it is one of them, still shows (locked).
  const listed = choosable(categories)
  const options =
    created && !listed.some((c) => c.id === created.id) ? [...listed, created] : listed
  const edit = useEditTransaction()
  const body = editBody(tx, draft)

  function change(patch: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...patch }))
    setSavedNote(null)
    edit.reset()
  }

  function save(onDone?: () => void) {
    if (body === null) return
    const scope = draft.scope
    edit.mutate(
      { fingerprint: tx.fingerprint, body },
      {
        onSuccess: (saved) => {
          setDraft(draftOf(saved))
          setSavedNote(
            scope === 'merchant'
              ? t('transactions.detail.savedMerchant', {
                  merchant: saved.merchant,
                  category: saved.category,
                })
              : t('transactions.saved'),
          )
          onSaved(saved)
          onDone?.()
        },
      },
    )
  }

  function discard() {
    setDraft(draftOf(tx))
    edit.reset()
  }

  function onCreated(category: Category) {
    setCreated(category)
    change({ category: category.name })
  }

  return { draft, change, body, save, discard, edit, savedNote, options, onCreated }
}
