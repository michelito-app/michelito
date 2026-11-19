// Selección múltiple de Transacciones (lógica pura). Las reglas de qué se cambia viven en el
// servidor (src/finanzas/web/batch_edit.py); aquí, qué se ofrece y cómo se dice.
import type { BatchResult, Category, LinkKind, SkipReason, Tx } from './api'
import { choosable } from './categories'
import { formatDop } from './money'

/** El máximo de un lote (`batch_edit.BATCH_MAX`). */
export const BATCH_MAX = 500

/** Los vínculos que fijan la categoría de sus transacciones (el servidor las omite). */
const FIXED_BY_LINK: readonly LinkKind[] = ['cash_box', 'investment', 'reimbursement', 'exchange']

export function fixedByLink(tx: Pick<Tx, 'link'>): boolean {
  return FIXED_BY_LINK.includes(tx.link)
}

/** Las elegidas que siguen en la lista (al cambiar los filtros, las que salen se sueltan). */
export function visibleChosen<T extends Pick<Tx, 'fingerprint'>>(
  items: readonly T[],
  chosen: ReadonlySet<string>,
): T[] {
  return items.filter((t) => chosen.has(t.fingerprint))
}

/** Las elegidas que siguen en `items` (el mismo conjunto si no sale ninguna): al cambiar los
 * filtros, las que dejan de verse se sueltan y no vuelven al quitar el filtro. */
export function pruned(
  chosen: ReadonlySet<string>,
  items: readonly Pick<Tx, 'fingerprint'>[],
): ReadonlySet<string> {
  const present = new Set(items.map((t) => t.fingerprint))
  if ([...chosen].every((fp) => present.has(fp))) return chosen
  return new Set([...chosen].filter((fp) => present.has(fp)))
}

/** Las filas que se ven: con grupos (categoría, comercio), solo las de los grupos abiertos. */
export function visibleRows<T>(
  groups: readonly { key: string; items: readonly T[] }[],
  open: ReadonlySet<string>,
): T[] {
  return groups.filter((g) => open.has(g.key)).flatMap((g) => [...g.items])
}

/** Agrega o quita una huella (devuelve un conjunto nuevo). */
export function toggled(chosen: ReadonlySet<string>, fingerprint: string): Set<string> {
  const next = new Set(chosen)
  if (!next.delete(fingerprint)) next.add(fingerprint)
  return next
}

type Counted = Pick<Tx, 'amount_cents' | 'amount_dop_cents'>

/** «3 seleccionadas · RD$ 15,000» (los montos en RD$ sin signo); con débitos y créditos
 * mezclados, «… · entran RD$ X · salen RD$ Y»; las que no tienen tasa (US$ de un mes sin tasa)
 * no suman y se dice cuántas. */
export function counterText(items: readonly Counted[]): string {
  const count = items.length === 1 ? '1 seleccionada' : `${items.length} seleccionadas`
  const rated = items.filter((t) => t.amount_dop_cents !== null)
  const sum = (list: readonly Counted[]) =>
    list.reduce((total, t) => total + Math.abs(t.amount_dop_cents ?? 0), 0)
  const incoming = rated.filter((t) => t.amount_cents < 0)
  const outgoing = rated.filter((t) => t.amount_cents >= 0)
  const money =
    incoming.length && outgoing.length
      ? `entran ${formatDop(sum(incoming))} · salen ${formatDop(sum(outgoing))}`
      : formatDop(sum(rated))
  const unrated = items.length - rated.length
  const missing =
    unrated === 0 ? '' : ` · ${unrated} sin tasa (no suma${unrated === 1 ? '' : 'n'})`
  return `${count} · ${money}${missing}`
}

export interface BatchOptions {
  categories: Category[]
  notice: string | null
}

/** Las categorías que se ofrecen para las elegidas: sin las ocultas ni las que pone su vínculo;
 * con algún débito, tampoco las de ingreso (un débito no es ingreso). Débitos y créditos
 * mezclados: se avisa por qué faltan los ingresos. */
export function batchOptions(
  categories: readonly Category[],
  items: readonly Pick<Tx, 'amount_cents'>[],
): BatchOptions {
  const debits = items.some((t) => t.amount_cents > 0)
  const credits = items.some((t) => t.amount_cents < 0)
  const shown = choosable(categories).filter((c) => !c.hidden && !(debits && c.kind === 'ingreso'))
  const notice =
    debits && credits
      ? 'Hay débitos y créditos: las categorías de ingreso no se ofrecen (un débito no es ingreso).'
      : null
  return { categories: shown, notice }
}

/** Cuántas elegidas fija un vínculo (no se cambiarán), para avisar antes. */
export function linkedText(items: readonly Pick<Tx, 'link'>[]): string | null {
  const count = items.filter(fixedByLink).length
  if (count === 0) return null
  return count === 1
    ? '1 está en un vínculo que fija su categoría: no se cambiará.'
    : `${count} están en un vínculo que fija su categoría: no se cambiarán.`
}

const SKIPPED: Record<SkipReason, [string, string]> = {
  caja: [
    'es de la caja fuerte (una entrada va a un ingreso; una salida, a un gasto)',
    'son de la caja fuerte (una entrada va a un ingreso; una salida, a un gasto)',
  ],
  vinculo: ['está en un vínculo', 'están en un vínculo'],
  direccion: ['es un débito (no puede ser ingreso)', 'son débitos (no pueden ser ingreso)'],
  sin_cambio: ['ya estaba en esa categoría', 'ya estaban en esa categoría'],
  desconocida: ['ya no existe', 'ya no existen'],
}
const ORDER: readonly SkipReason[] = [
  'vinculo',
  'caja',
  'direccion',
  'sin_cambio',
  'desconocida',
]

/** «12 pasaron a Cripto · 3 no se cambiaron: están en un vínculo». */
export function resultText(result: BatchResult, category: string): string {
  const applied = result.applied.length
  const head =
    applied === 0
      ? 'Ninguna cambió'
      : applied === 1
        ? `1 pasó a ${category}`
        : `${applied} pasaron a ${category}`
  const parts = ORDER.flatMap((reason) => {
    const count = result.skipped.filter((s) => s.reason === reason).length
    if (count === 0) return []
    const [one, many] = SKIPPED[reason]
    return [count === 1 ? `1 no se cambió: ${one}` : `${count} no se cambiaron: ${many}`]
  })
  return [head, ...parts].join(' · ')
}
