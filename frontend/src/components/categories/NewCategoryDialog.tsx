import { Modal } from '@/components/ui/modal'
import { t } from '@/i18n'
import type { Category, Kind } from '@/lib/api'
import { useCreateCategory } from '@/lib/queries'
import { CategoryForm } from './CategoryForm'

interface NewCategoryDialogProps {
  /** Starting kind (that of the row it is created from). */
  kind: Kind
  onCreated: (category: Category) => void
  onClose: () => void
}

/** "New category": name, kind and colour; once created it is handed back to be picked. */
export function NewCategoryDialog({ kind, onCreated, onClose }: NewCategoryDialogProps) {
  const create = useCreateCategory()
  return (
    <Modal title={t('categories.new')} onClose={onClose}>
      <CategoryForm
        initial={{ name: '', kind, color: null }}
        submitLabel={t('categories.create')}
        pending={create.isPending}
        error={
          create.isError ? t('categories.createFailed', { message: create.error.message }) : null
        }
        onSubmit={(fields) => create.mutate(fields, { onSuccess: onCreated })}
        onCancel={onClose}
      />
    </Modal>
  )
}
