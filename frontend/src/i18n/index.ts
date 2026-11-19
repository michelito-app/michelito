// UI text catalog. Every visible string lives in a locale catalog under an English key; the
// code asks for it with `t(key, params)`. Spanish (`es`) is the only locale and the default.
//
// A message is a template with `{name}` placeholders, or a plural message: one template per
// CLDR plural category of the locale (`one`, `other`, optionally `many`) plus an optional
// `zero` used for exactly 0. Plural messages take a numeric `count`. Parameters are inserted
// as given (numbers with `String`): callers format money, dates and grouped numbers first, so
// a year stays "2026" and an amount says what `formatDop` says.
import { es } from './es'

/** Locale for `Intl` formatting (dates, numbers, plural rules). */
export const LOCALE = 'es-DO'

export interface PluralMessage {
  readonly zero?: string
  readonly one: string
  readonly many?: string
  readonly other: string
}

export type Message = string | PluralMessage

/** The shape every locale catalog satisfies. */
export type Catalog = Readonly<Record<string, Message>>

type Messages = typeof es
export type MessageKey = keyof Messages

type Placeholders<S extends string> = S extends `${string}{${infer Name}}${infer Rest}`
  ? Name | Placeholders<Rest>
  : never

type Value = string | number

type ParamsOf<M> = M extends string
  ? Record<Placeholders<M>, Value>
  : M extends PluralMessage
    ? { count: number } & Record<Exclude<Placeholders<M[keyof M] & string>, 'count'>, Value>
    : never

type HasParams<M> = M extends string ? ([Placeholders<M>] extends [never] ? false : true) : true

/** The arguments after the key: nothing, or the parameters the message names. */
export type Args<K extends MessageKey> =
  HasParams<Messages[K]> extends true ? [params: ParamsOf<Messages[K]>] : []

const plurals = new Intl.PluralRules(LOCALE)
const PLACEHOLDER = /\{(\w+)\}/g

/** The template for `message` with these params (the plural form chosen by `count`). */
export function template(message: Message, params: Readonly<Record<string, unknown>> = {}): string {
  if (typeof message === 'string') return message
  const count = Number(params.count)
  if (count === 0 && message.zero !== undefined) return message.zero
  const category = plurals.select(count)
  if (category === 'one') return message.one
  if (category === 'many' && message.many !== undefined) return message.many
  return message.other
}

/** Splits a template into literal text and placeholder names, in order. */
export function pieces(text: string): { text: string; name: string | null }[] {
  const out: { text: string; name: string | null }[] = []
  let last = 0
  for (const match of text.matchAll(PLACEHOLDER)) {
    if (match.index > last) out.push({ text: text.slice(last, match.index), name: null })
    out.push({ text: match[0], name: match[1] })
    last = match.index + match[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last), name: null })
  return out
}

/** The catalog message for `key`, with its placeholders filled. */
export function t<K extends MessageKey>(key: K, ...args: Args<K>): string {
  const params = (args[0] ?? {}) as Readonly<Record<string, unknown>>
  const text = template(es[key] as Message, params)
  return text.replace(PLACEHOLDER, (whole, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : whole,
  )
}

/** The raw catalog entry (for code that needs the template itself, e.g. tests). */
export function message<K extends MessageKey>(key: K): Messages[K] {
  return es[key]
}
