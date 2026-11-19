import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/modal'
import { t } from '@/i18n'
import type { Category } from '@/lib/api'
import {
  categoryGroups,
  choosable,
  conflictText,
  parseKeywords,
  previewText,
} from '@/lib/categories'
import { formatDop, formatUsd } from '@/lib/money'
import { useDeleteCategory, useKeywordPreview, useUpdateCategory } from '@/lib/queries'
import { CategoryForm, FIELD_CLASS } from './CategoryForm'

/** Wait after the last key press before asking for the preview. */
const PREVIEW_DEBOUNCE_MS = 300

interface DialogProps {
  category: Category
  onClose: () => void
}

const ALERT =
  'rounded-[10px] border border-up/30 bg-up-soft px-3 py-2.5 text-[13px] text-up-ink'

/** Rename, change the colour and, for a user category, the kind. */
export function EditCategoryDialog({ category, onClose }: DialogProps) {
  const update = useUpdateCategory()
  return (
    <Modal title={t('categories.editNamed', { name: category.name })} onClose={onClose}>
      <CategoryForm
        initial={{ name: category.name, kind: category.kind, color: category.color }}
        kindLocked={category.builtin}
        submitLabel={t('categories.save')}
        pending={update.isPending}
        error={
          update.isError ? t('categories.saveFailed', { message: update.error.message }) : null
        }
        onSubmit={(fields) =>
          update.mutate(
            {
              id: category.id,
              patch: category.builtin ? { name: fields.name, color: fields.color } : fields,
            },
            { onSuccess: onClose },
          )
        }
        onCancel={onClose}
      />
    </Modal>
  )
}

function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return settled
}

/** Keywords with a preview of what they would move, before saving. */
export function KeywordsDialog({ category, onClose }: DialogProps) {
  const [text, setText] = useState(category.keywords.join(', '))
  const words = useDebounced(parseKeywords(text).join('\n'), PREVIEW_DEBOUNCE_MS)
  const keywords = words === '' ? [] : words.split('\n')
  const preview = useKeywordPreview(category.id, keywords, true)
  const update = useUpdateCategory()
  const data = preview.data
  return (
    <Modal title={t('categories.keywordsOf', { name: category.name })} onClose={onClose}>
      <label className="flex flex-col gap-2 text-[13px] font-semibold text-ink-2">
        {t('categories.keywordsDialog.label')}
        <textarea
          value={text}
          rows={3}
          onChange={(event) => setText(event.target.value)}
          placeholder={t('categories.keywordsDialog.placeholder')}
          className={`${FIELD_CLASS} h-auto py-2.5`}
        />
      </label>
      <p className="text-[13px] text-muted-foreground">
        {t('categories.keywordsDialog.help')}
      </p>
      <div role="status" className="flex min-h-10 flex-col gap-1 text-[13px]">
        {preview.isError && <span className="text-up-ink">{preview.error.message}</span>}
        {data && !preview.isError && (
          <>
            <span className="font-semibold text-ink-2">
              {previewText(
                data.count,
                formatDop(data.total_cents),
                data.unconverted_usd_cents ? formatUsd(data.unconverted_usd_cents) : null,
              )}
            </span>
            {conflictText(data.conflicts) && (
              <span className="text-muted-foreground">{conflictText(data.conflicts)}</span>
            )}
          </>
        )}
      </div>
      {update.isError && (
        <p role="alert" className={ALERT}>
          {t('categories.saveFailed', { message: update.error.message })}
        </p>
      )}
      <div className="flex flex-wrap gap-2.5">
        <Button
          className="h-11 flex-[1_1_120px] rounded-xl text-sm font-semibold"
          disabled={update.isPending}
          onClick={() =>
            update.mutate(
              { id: category.id, patch: { keywords: parseKeywords(text) } },
              { onSuccess: onClose },
            )
          }
        >
          {update.isPending ? t('categories.saving') : t('categories.save')}
        </Button>
        <Button
          variant="outline"
          className="h-11 flex-[1_1_120px] rounded-xl text-sm font-semibold"
          onClick={onClose}
        >
          {t('categories.cancel')}
        </Button>
      </div>
    </Modal>
  )
}

interface DeleteDialogProps extends DialogProps {
  categories: Category[]
}

/** Delete a user category: its transactions, rules and keywords move to another one. */
export function DeleteCategoryDialog({ category, categories, onClose }: DeleteDialogProps) {
  const others = choosable(categories).filter((c) => c.id !== category.id)
  const fallback = others.find((c) => c.kind === category.kind && !c.hidden) ?? others[0]
  const [target, setTarget] = useState<number>(fallback.id)
  const remove = useDeleteCategory()
  const byName = new Map(others.map((c) => [c.name, c.id]))
  const chosen = others.find((c) => c.id === target)?.name ?? null
  return (
    <Modal title={t('categories.deleteNamed', { name: category.name })} onClose={onClose}>
      <label className="flex flex-col gap-2 text-[13px] font-semibold text-ink-2">
        {t('categories.deleteDialog.moveTo')}
        <select
          value={chosen ?? ''}
          onChange={(event) => setTarget(byName.get(event.target.value) ?? target)}
          className={`${FIELD_CLASS} cursor-pointer`}
        >
          {categoryGroups(others, chosen).map((group) => (
            <optgroup key={group.label} label={group.label}>
              {group.names.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      {remove.isError && (
        <p role="alert" className={ALERT}>
          {t('categories.deleteFailed', { message: remove.error.message })}
        </p>
      )}
      <div className="flex flex-wrap gap-2.5">
        <Button
          variant="destructive"
          className="h-11 flex-[1_1_120px] rounded-xl text-sm font-semibold"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate({ id: category.id, reassignTo: target }, { onSuccess: onClose })
          }
        >
          {remove.isPending ? t('categories.deleting') : t('categories.delete')}
        </Button>
        <Button
          variant="outline"
          className="h-11 flex-[1_1_120px] rounded-xl text-sm font-semibold"
          onClick={onClose}
        >
          {t('categories.cancel')}
        </Button>
      </div>
    </Modal>
  )
}
