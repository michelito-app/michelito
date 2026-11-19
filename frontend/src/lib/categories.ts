// Category colours (the same as the Summary table, by spending rank in the month) and their
// grouping by kind for the pickers.
import { t } from '@/i18n'
import type { Category, Kind } from './api'

/** Category palette, in spending order. It avoids the flow colours (income green, expense
 * terracotta, third-party grey; see lib/colors) and the former blue: a category must not read
 * as income or as an alert. */
export const CATEGORY_PALETTE = [
  '#3FA7C9',
  '#8E5FB8',
  '#D9A93A',
  '#B8467E',
  '#A3994F',
  '#4A5568',
  '#D88FC4',
  '#6B4FA0',
  '#E0B98A',
  '#7A3E8F',
] as const

/** Bank debits to other people: not spending, but they reduce what you kept. The seed name of
 * the server's `categories.THIRD_PARTY` (the user may rename it: today's name comes from
 * `builtinName`; the server also understands this one). */
export const THIRD_PARTY = t('categories.builtin.thirdParty')

/** Stable identity (`builtin_key`) of the system categories the board names. */
export const BUILTIN = { thirdParty: 'THIRD_PARTY' } as const

/** The ones only their link sets (marking an investment or the cash box): they are not picked
 * by hand and have no keywords. The investment-returns category can be picked: any income can
 * be one. */
export const LINK_ONLY_KEYS: readonly string[] = ['INVESTMENT', 'INVESTMENT_CAPITAL', 'CASH_BOX']

/** Is it set only by its link? */
export function isLinkOnly(category: Pick<Category, 'builtin_key'>): boolean {
  return category.builtin_key !== null && LINK_ONLY_KEYS.includes(category.builtin_key)
}

/** The ones that can be picked by hand (without the link-only ones). */
export function choosable<T extends Pick<Category, 'builtin_key'>>(categories: readonly T[]): T[] {
  return categories.filter((c) => !isLinkOnly(c))
}

/** Today's name of a system category, by its stable identity. */
export function builtinName(
  categories: readonly Pick<Category, 'name' | 'builtin_key'>[],
  key: string,
  fallback: string,
): string {
  return categories.find((c) => c.builtin_key === key)?.name ?? fallback
}

/** Colours the user picked, by category name (the rest go by rank). */
export function customColors(
  categories: readonly Pick<Category, 'name' | 'color'>[],
): Readonly<Record<string, string>> {
  return Object.fromEntries(
    categories.filter((c) => c.color !== null).map((c) => [c.name, c.color as string]),
  )
}

/** Former names of renamed categories (same as the server's `categories._LEGACY_NAMES`). */
const LEGACY_NAMES: Readonly<Record<string, string>> = {
  [t('categories.legacy.cashAndTransfers')]: t('categories.builtin.cash'),
}

/** Current name of a category that may come with a former name (an old link). */
export function canonicalCategory(name: string): string {
  return LEGACY_NAMES[name] ?? name
}

/** Grey for categories without a rank (no purchases in the month, or the summary loading). */
export const NO_COLOR = '#C9CDD2'

/** Colour of rank `index` (0 = the category with the most spending). */
export function categoryColor(index: number): string {
  return CATEGORY_PALETTE[index % CATEGORY_PALETTE.length]
}

/** Colour of `category`: the one the user picked or, if none, the one of its rank in `ranking`
 * (Summary categories, largest first). */
export function colorFor(
  ranking: readonly string[],
  category: string,
  custom: Readonly<Record<string, string>> = {},
): string {
  if (custom[category]) return custom[category]
  const index = ranking.indexOf(category)
  return index < 0 ? NO_COLOR : categoryColor(index)
}

export interface CategoryGroup {
  label: string
  names: string[]
}

/** Picker groups, in this order: the group label (plural) and the kind's name (singular). */
export const GROUPS: readonly { kind: Kind; label: string; singular: string }[] = [
  { kind: 'expense', label: t('categories.group.expense'), singular: t('categories.kind.expense') },
  { kind: 'income', label: t('categories.group.income'), singular: t('categories.kind.income') },
  {
    kind: 'transfer',
    label: t('categories.group.transfer'),
    singular: t('categories.kind.transfer'),
  },
]

type Listed = Pick<Category, 'name' | 'kind'> & { hidden?: boolean }

/** Categories grouped by kind (for `<optgroup>`), without hidden ones or empty groups.
 * `keep`: a hidden one that is listed anyway (the row's or the filter's). */
export function categoryGroups(
  categories: readonly Listed[],
  keep: string | null = null,
): CategoryGroup[] {
  const shown = categories.filter((c) => !c.hidden || c.name === keep)
  return GROUPS.map(({ kind, label }) => ({
    label,
    names: shown.filter((c) => c.kind === kind).map((c) => c.name),
  })).filter((group) => group.names.length > 0)
}

/** Value of the "new category" option of the detail's picker. With spaces at the ends: the
 * server strips them from names, so no category can be called this. */
export const NEW_CATEGORY = ' + new category '

/** `data-action` of that option: it is recognised by this, not by the value. */
export const NEW_CATEGORY_ACTION = 'new-category'

/** Is the chosen option the "new category" one? */
export function isNewCategoryOption(
  option: { dataset: Record<string, string | undefined> } | undefined,
): boolean {
  return option?.dataset.action === NEW_CATEGORY_ACTION
}

/** Colours to pick from when creating or editing a category (the design palette). */
export const COLOR_CHOICES: readonly string[] = CATEGORY_PALETTE

/** How many transactions the category has this year (its own text for none). */
export function countText(count: number): string {
  return t('categories.countYear', { count })
}

/** What saving the keywords would move: the count and the RD$ total, plus the US$ without a
 * rate. */
export function previewText(count: number, dop: string, usd: string | null): string {
  if (count === 0) return t('categories.preview.none')
  const money = usd ? t('categories.preview.withUnconverted', { dop, usd }) : dop
  return t('categories.preview.moves', { count, money })
}

/** Conflict note: transactions that also have words of another category. */
export function conflictText(conflicts: number): string | null {
  if (conflicts === 0) return null
  return t('categories.conflicts', { count: conflicts })
}

/** Keywords typed separated by commas or line breaks, without empty ones. */
export function parseKeywords(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((word) => word.trim())
    .filter((word) => word !== '')
}
