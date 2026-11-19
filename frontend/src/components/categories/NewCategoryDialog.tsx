import { Modal } from '@/components/ui/modal'
import type { Category, Kind } from '@/lib/api'
import { useCreateCategory } from '@/lib/queries'
import { CategoryForm } from './CategoryForm'

interface NewCategoryDialogProps {
  /** Tipo de partida (el de la fila desde la que se crea). */
  kind: Kind
  onCreated: (category: Category) => void
  onClose: () => void
}

/** "Nueva categoría": nombre, tipo y color; al crearla se devuelve para elegirla. */
export function NewCategoryDialog({ kind, onCreated, onClose }: NewCategoryDialogProps) {
  const create = useCreateCategory()
  return (
    <Modal title="Nueva categoría" onClose={onClose}>
      <CategoryForm
        initial={{ name: '', kind, color: null }}
        submitLabel="Crear"
        pending={create.isPending}
        error={create.isError ? `No se pudo crear: ${create.error.message}` : null}
        onSubmit={(fields) => create.mutate(fields, { onSuccess: onCreated })}
        onCancel={onClose}
      />
    </Modal>
  )
}
