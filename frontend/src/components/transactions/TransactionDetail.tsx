import { Check, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { FOCUS } from '@/components/summary/styles'
import { CategoryOptions } from './Filters'
import { NewCategoryDialog } from '@/components/categories/NewCategoryDialog'
import type { Category, Tx } from '@/lib/api'
import { choosable, isNewCategoryOption } from '@/lib/categories'
import { useDismissOneOff, useEditTransaction } from '@/lib/queries'
import {
  AMOUNT_TONE_CLASS,
  amountLines,
  amountTone,
  dayLabel,
  type Draft,
  editBody,
  merchantScopeNote,
  NOTE_MAX,
  oneOffAction,
  originText,
  type Scope,
} from '@/lib/transactions'
import { categoryLocked } from '@/lib/links'
import { cn } from '@/lib/utils'
import { HistorySection } from '@/components/log/HistorySection'
import { CashBoxSection } from './CashBoxSection'
import { LinkSummaries } from './LinkSummaries'
import { RecurringSection } from './RecurringSection'
import { ReserveSection } from './ReserveSection'

/** Por debajo de este ancho el detalle es una hoja inferior (ver TransactionsPage). */
const SHEET_QUERY = '(max-width: 1279.98px)'

/** Id del título, para el `aria-labelledby` del panel. */
export const DETAIL_TITLE_ID = 'tx-detail-title'

interface TransactionDetailProps {
  tx: Tx
  categories: Category[]
  /** ¿La fila sigue en la lista con los filtros actuales? */
  inList: boolean
  onSaved: (tx: Tx) => void
  onClose: () => void
  onShowMerchant: (merchant: string) => void
}

function draftOf(tx: Tx): Draft {
  return { category: tx.category, oneOff: tx.one_off, scope: 'transaction', note: tx.note }
}

/** Detalle de la transacción elegida y su corrección (categoría, alcance, gasto único). */
export function TransactionDetail({
  tx,
  categories,
  inList,
  onSaved,
  onClose,
  onShowMerchant,
}: TransactionDetailProps) {
  const ids = useId()
  const heading = useRef<HTMLHeadingElement>(null)
  const [draft, setDraft] = useState<Draft>(() => draftOf(tx))
  // Un vínculo nuevo (la caja fuerte, por ejemplo) cambia la categoría desde fuera del formulario.
  const [seenCategory, setSeenCategory] = useState(tx.category)
  if (seenCategory !== tx.category) {
    setSeenCategory(tx.category)
    setDraft((current) => ({ ...current, category: tx.category }))
  }
  const [savedNote, setSavedNote] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  // La recién creada, mientras la lista de categorías se vuelve a pedir.
  const [created, setCreated] = useState<Category | null>(null)
  // Sin las que solo pone su vínculo: la de la fila, si es una de ellas, sale igual (bloqueada).
  const listed = choosable(categories)
  const options =
    created && !listed.some((c) => c.id === created.id) ? [...listed, created] : listed
  const edit = useEditTransaction()
  const body = editBody(tx, draft)
  const amount = amountLines(tx)
  const locked = categoryLocked(tx)


  // En la hoja inferior (teléfono) el foco va al detalle al abrirlo.
  useEffect(() => {
    if (window.matchMedia(SHEET_QUERY).matches) heading.current?.focus({ preventScroll: true })
  }, [])

  function change(patch: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...patch }))
    setSavedNote(null)
    edit.reset()
  }

  function save() {
    if (body === null) return
    const scope = draft.scope
    edit.mutate(
      { fingerprint: tx.fingerprint, body },
      {
        onSuccess: (saved) => {
          setDraft(draftOf(saved))
          setSavedNote(
            scope === 'merchant'
              ? `Guardado: todo ${saved.merchant} queda en ${saved.category}`
              : 'Guardado',
          )
          onSaved(saved)
        },
      },
    )
  }

  return (
    <div
      className="flex flex-col gap-5"
      onKeyDown={(event) => {
        if (event.key === 'Escape') onClose()
      }}
    >
      <div className="flex items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="text-[13px] text-muted-foreground">
            {dayLabel(tx.day)} · {tx.account_label}
          </span>
          <h2
            id={DETAIL_TITLE_ID}
            ref={heading}
            tabIndex={-1}
            className="text-[22px] leading-tight font-bold tracking-[-0.01em] break-words outline-none"
          >
            {tx.merchant}
          </h2>
          <span
            className={cn(
              'text-[28px] leading-tight font-bold tabular-nums',
              AMOUNT_TONE_CLASS[amountTone(tx)],
            )}
          >
            {amount.main}
          </span>
          <span className="text-[13px] text-muted-foreground">{originText(tx)}</span>
        </div>
        <button
          type="button"
          aria-label="Cerrar detalle"
          onClick={onClose}
          className={cn(
            '-mt-1 -mr-2 flex size-11 shrink-0 items-center justify-center rounded-[10px] text-muted-foreground hover:bg-muted hover:text-foreground xl:hidden',
            FOCUS,
          )}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>

      <div className="flex flex-col gap-1 rounded-xl border border-[#EFEFEA] bg-[#FAFAF8] px-3.5 py-3">
        <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase">
          Como aparece en el estado
        </span>
        <span className="font-mono text-[13px] break-all text-ink-2">{tx.description}</span>
      </div>

      <label className="flex flex-col gap-2 text-[13px] font-semibold text-ink-2">
        Categoría
        <select
          aria-label="Categoría"
          value={draft.category}
          disabled={locked}
          aria-describedby={locked ? `${ids}-locked` : undefined}
          onChange={(event) => {
            if (isNewCategoryOption(event.target.selectedOptions[0])) setCreating(true)
            else change({ category: event.target.value })
          }}
          className="h-11 w-full cursor-pointer rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm font-medium text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <CategoryOptions categories={options} current={tx.category} allowNew />
        </select>
        {locked && (
          <span id={`${ids}-locked`} className="text-xs font-normal text-muted-foreground">
            Su categoría la define el vínculo: quita el enlace para cambiarla.
          </span>
        )}
      </label>
      {creating && (
        <NewCategoryDialog
          kind={tx.kind}
          onClose={() => setCreating(false)}
          onCreated={(category) => {
            setCreated(category)
            setCreating(false)
            change({ category: category.name })
          }}
        />
      )}

      <fieldset className="flex flex-col gap-2" disabled={locked}>
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">Aplicar a</legend>
        <ScopeOption
          name={`${ids}-scope`}
          value="transaction"
          checked={draft.scope === 'transaction'}
          onPick={(scope) => change({ scope })}
        >
          Solo esta transacción
        </ScopeOption>
        <ScopeOption
          name={`${ids}-scope`}
          value="merchant"
          checked={draft.scope === 'merchant'}
          onPick={(scope) => change({ scope })}
        >
          <span>
            Todo {tx.merchant}{' '}
            <span className="text-muted-foreground">
              · {merchantScopeNote(tx)}
            </span>
          </span>
        </ScopeOption>
      </fieldset>

      <label className="flex min-h-11 cursor-pointer items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={draft.oneOff}
          onChange={(event) => change({ oneOff: event.target.checked })}
          className="mt-0.5 size-[18px] shrink-0 cursor-pointer accent-up"
        />
        <span className="flex flex-col gap-0.5">
          <span className="font-semibold">Gasto único</span>
          <span className="text-[13px] text-muted-foreground">
            Cuenta en el total del mes, no en lo habitual
          </span>
        </span>
      </label>

      <OneOffHint tx={tx} />

      <label className="flex flex-col gap-2 text-[13px] font-semibold text-ink-2">
        Nota
        <textarea
          value={draft.note}
          maxLength={NOTE_MAX}
          rows={2}
          placeholder="Para quién fue, qué era…"
          onChange={(event) => change({ note: event.target.value })}
          className="min-h-11 w-full resize-y rounded-xl border border-[#D6D6D0] bg-card px-3 py-2.5 text-sm font-normal text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
        />
        <span className="text-xs font-normal text-muted-foreground">
          {draft.note.length}/{NOTE_MAX} · se guarda con «Guardar» y la búsqueda la encuentra
        </span>
      </label>

      {tx.corrected && (
        <p className="rounded-[10px] bg-secondary px-3 py-2.5 text-[13px] text-secondary-foreground">
          Corregida por ti. Antes: {tx.original_category}.
        </p>
      )}

      {!inList && (
        <p className="text-[13px] text-muted-foreground">Ya no aparece con estos filtros.</p>
      )}

      {edit.isError && (
        <p
          role="alert"
          className="rounded-[10px] border border-up/30 bg-up-soft px-3 py-2.5 text-[13px] text-up-ink"
        >
          No se pudo guardar: {edit.error.message}
        </p>
      )}

      <div className="flex flex-col gap-2.5">
        <div className="flex flex-wrap gap-2.5">
          <Button
            className="h-11 flex-[1_1_140px] rounded-xl text-sm font-semibold"
            disabled={body === null || edit.isPending}
            onClick={save}
          >
            {edit.isPending ? 'Guardando…' : 'Guardar'}
          </Button>
          <Button
            variant="outline"
            className="h-11 flex-[1_1_140px] rounded-xl border-[#D6D6D0] bg-card text-sm font-semibold text-ink-2"
            onClick={() => onShowMerchant(tx.merchant)}
          >
            Ver todo el comercio
          </Button>
        </div>
        <p role="status" className="min-h-5 text-[13px] font-medium text-primary">
          {savedNote && (
            <span className="inline-flex items-center gap-1.5">
              <Check size={14} aria-hidden="true" />
              {savedNote}
            </span>
          )}
        </p>
      </div>

      <LinkSummaries tx={tx} />
      <RecurringSection tx={tx} />
      <ReserveSection tx={tx} />
      <CashBoxSection tx={tx} onSaved={onSaved} onClose={onClose} />
      <HistorySection fingerprint={tx.fingerprint} />
    </div>
  )
}

/** Por qué la fila parece un gasto único y "No es único"; si ya se descartó, "Volver a
 * sugerir" lo deshace. */
function OneOffHint({ tx }: { tx: Tx }) {
  const dismiss = useDismissOneOff()
  const action = oneOffAction(tx)
  if (action === null) return null
  const restoring = action === 'restore'
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-dashed border-up/40 px-3.5 py-3">
      <p className="text-[13px] text-ink-2">
        {restoring ? (
          'Dijiste que no es un gasto único: ya no se sugiere.'
        ) : (
          <>
            <span className="font-semibold">¿Gasto único?</span> {tx.one_off_reasons.join(' · ')}
          </>
        )}
      </p>
      <Button
        variant="outline"
        className="h-11 self-start rounded-xl border-[#D6D6D0] bg-card px-4 text-sm font-semibold text-ink-2"
        disabled={dismiss.isPending}
        onClick={() => dismiss.mutate({ fingerprint: tx.fingerprint, dismissed: !restoring })}
      >
        {restoring ? 'Volver a sugerir' : 'No es único'}
      </Button>
      {dismiss.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo guardar: {dismiss.error.message}
        </p>
      )}
    </div>
  )
}

interface ScopeOptionProps {
  name: string
  value: Scope
  checked: boolean
  onPick: (scope: Scope) => void
  children: ReactNode
}

function ScopeOption({ name, value, checked, onPick, children }: ScopeOptionProps) {
  return (
    <label
      className={cn(
        'flex min-h-11 cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2 text-sm transition-colors',
        checked ? 'border-primary bg-[#F6FAF8]' : 'border-border hover:bg-[#FAFAF8]',
      )}
    >
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        onChange={() => onPick(value)}
        className="size-[18px] shrink-0 cursor-pointer accent-primary"
      />
      {children}
    </label>
  )
}
