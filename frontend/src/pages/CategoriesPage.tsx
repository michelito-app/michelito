import { useState } from 'react'
import {
  DeleteCategoryDialog,
  EditCategoryDialog,
  KeywordsDialog,
} from '@/components/categories/CategoryDialogs'
import { NewCategoryDialog } from '@/components/categories/NewCategoryDialog'
import { LoadError } from '@/components/LoadError'
import { PANEL, PANEL_TITLE, ROW_DIVIDER } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { Category } from '@/lib/api'
import { countText, GROUPS, isLinkOnly } from '@/lib/categories'
import { useCategories, useUpdateCategory } from '@/lib/queries'
import { cn } from '@/lib/utils'

type Open =
  | { dialog: 'new' }
  | { dialog: 'edit' | 'keywords' | 'delete'; category: Category }
  | null

const ACTION = 'h-11 rounded-xl px-3 text-[13px] font-semibold'

/** Pantalla Categorías: por tipo, con su color, cuántas transacciones tiene en el año y sus
 * palabras clave. Crear, renombrar, recolorear, ocultar y borrar (las del usuario). */
export function CategoriesPage() {
  const categories = useCategories()
  const [open, setOpen] = useState<Open>(null)
  const close = () => setOpen(null)

  if (categories.isError) {
    return (
      <LoadError
        what="las categorías"
        error={categories.error}
        onRetry={() => categories.refetch()}
      />
    )
  }
  if (categories.isPending) return <PageSkeleton />
  const all = categories.data

  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">Categorías</h1>
          <p className="text-[13px] text-muted-foreground">
            Las palabras clave mueven transacciones pasadas y futuras.
          </p>
        </div>
        <Button className={cn(ACTION, 'px-4')} onClick={() => setOpen({ dialog: 'new' })}>
          Nueva categoría
        </Button>
      </header>
      <div className="flex max-w-[960px] flex-col gap-6">
        {GROUPS.map(({ kind, label }) => {
          const items = all.filter((c) => c.kind === kind)
          if (items.length === 0) return null
          return (
            <section key={kind} aria-label={label} className={cn(PANEL, 'py-2')}>
              <h2 className={cn(PANEL_TITLE, 'px-4 pt-3 pb-2 sm:px-6')}>{label}</h2>
              <ul>
                {items.map((category) => (
                  <CategoryRow
                    key={category.id}
                    category={category}
                    onOpen={(dialog) => setOpen({ dialog, category })}
                  />
                ))}
              </ul>
            </section>
          )
        })}
      </div>
      {open?.dialog === 'new' && (
        <NewCategoryDialog kind="gasto" onCreated={close} onClose={close} />
      )}
      {open?.dialog === 'edit' && <EditCategoryDialog category={open.category} onClose={close} />}
      {open?.dialog === 'keywords' && (
        <KeywordsDialog category={open.category} onClose={close} />
      )}
      {open?.dialog === 'delete' && (
        <DeleteCategoryDialog category={open.category} categories={all} onClose={close} />
      )}
    </>
  )
}

interface CategoryRowProps {
  category: Category
  onOpen: (dialog: 'edit' | 'keywords' | 'delete') => void
}

function CategoryRow({ category, onOpen }: CategoryRowProps) {
  const update = useUpdateCategory()
  return (
    <li
      aria-label={category.name}
      className={cn(ROW_DIVIDER, 'flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6')}
    >
      <div className="flex min-w-0 flex-[1_1_220px] items-start gap-3">
        {category.color === null ? (
          // Sin color elegido: el Resumen y la lista le dan el de su puesto en el mes.
          <span
            title="Color automático: el de su puesto en el Resumen"
            className="mt-1.5 size-3 shrink-0 rounded-full border-[1.5px] border-dashed border-muted-foreground"
          >
            <span className="sr-only">Color automático</span>
          </span>
        ) : (
          <span
            aria-hidden="true"
            className="mt-1.5 size-3 shrink-0 rounded-full"
            style={{ backgroundColor: category.color }}
          />
        )}
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="flex flex-wrap items-baseline gap-x-2 text-sm font-semibold break-words">
            {category.name}
            {category.hidden && (
              <span className="text-xs font-medium text-muted-foreground">Oculta</span>
            )}
          </span>
          <span className="text-[13px] text-muted-foreground">
            {countText(category.count_year)}
            {category.builtin && ' · del sistema'}
          </span>
          {category.keywords.length > 0 && (
            <span className="text-[13px] break-words text-ink-2">
              Palabras: {category.keywords.join(', ')}
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Button
          variant="outline"
          className={ACTION}
          aria-label={`Editar ${category.name}`}
          onClick={() => onOpen('edit')}
        >
          Editar
        </Button>
        {!isLinkOnly(category) && (
          <Button
            variant="outline"
            className={ACTION}
            aria-label={`Palabras clave de ${category.name}`}
            onClick={() => onOpen('keywords')}
          >
            Palabras clave
          </Button>
        )}
        <Button
          variant="outline"
          className={ACTION}
          aria-label={`${category.hidden ? 'Mostrar' : 'Ocultar'} ${category.name}`}
          disabled={update.isPending}
          onClick={() => update.mutate({ id: category.id, patch: { hidden: !category.hidden } })}
        >
          {category.hidden ? 'Mostrar' : 'Ocultar'}
        </Button>
        {!category.builtin && (
          <Button
            variant="outline"
            className={ACTION}
            aria-label={`Borrar ${category.name}`}
            onClick={() => onOpen('delete')}
          >
            Borrar
          </Button>
        )}
      </div>
      {update.isError && (
        <p role="alert" className="w-full text-[13px] text-up-ink">
          No se pudo guardar: {update.error.message}
        </p>
      )}
    </li>
  )
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Cargando las categorías" className="flex flex-col gap-6">
      <Skeleton className="h-9 w-56 rounded-[10px]" />
      <div className="flex max-w-[960px] flex-col gap-6">
        {[0, 1].map((i) => (
          <Skeleton key={i} className="h-48 rounded-2xl" />
        ))}
      </div>
    </div>
  )
}
