// A new shared group started from a credit ("It is a payment…" → "+ New group"): the plan the
// server proposes, and the pure pieces of the flow (who paid, searching the expense, the split
// and the request body). See `analysis/ledger_credit.py`.
import type { LinkedTx } from './api'
import type { ChosenPerson } from './ledger'
import { fold } from './picker'
import type { NewPerson } from './sharedApi'

export interface PersonGuess {
  contact_id: number | null
  name: string
  alias: string | null
}

export interface ExpenseOption extends LinkedTx {
  fits: boolean // the credit is a fair share of it
}

export interface CreditOption {
  tx: LinkedTx
  person: PersonGuess | null
}

export interface CreditPlan {
  person: PersonGuess | null
  expenses: ExpenseOption[]
  credits: CreditOption[]
}

/** An expense of the new group: a bank transaction or one typed by hand (cash). */
export type ChosenExpense =
  | { kind: 'tx'; key: string; tx: LinkedTx }
  | { kind: 'cash'; key: string; description: string; amount_cents: number; currency: string; day: string }

/** A credit of the new group and who paid it. */
export interface ChosenCredit {
  tx: LinkedTx
  payer: ChosenPerson
}

export type CreditSplit = 'paid' | 'equal'

export interface CreditGroupBody {
  name: string
  split: CreditSplit
  payments: { fingerprint: string; person: NewPerson }[]
  expenses: (
    | { fingerprint: string }
    | { amount_cents: number; currency: string; day: string; description: string }
  )[]
}

/** The guessed person as a chosen chip (an existing contact, or a new one with the bank's text
 * as alias). */
export function personOf(guess: PersonGuess | null): ChosenPerson | null {
  if (!guess) return null
  if (guess.contact_id != null) {
    return { key: `c${guess.contact_id}`, label: guess.name, person: { contact_id: guess.contact_id } }
  }
  const person: NewPerson = guess.alias ? { name: guess.name, alias: guess.alias } : { name: guess.name }
  return { key: `n${fold(guess.name)}`, label: guess.name, person }
}

/** Options whose merchant, statement text or amount (as typed: "850", "1,250.50") match. */
export function searchExpenses<T extends LinkedTx>(options: readonly T[], query: string): T[] {
  const text = fold(query.trim())
  if (!text) return [...options]
  const digits = query.replace(/[^\d.]/g, '')
  return options.filter((o) => {
    const words = fold(`${o.merchant} ${o.description ?? ''}`)
    if (words.includes(text)) return true
    if (!digits) return false
    const amount = (Math.abs(o.amount_cents) / 100).toFixed(2)
    return amount.startsWith(digits) || amount.replace(/\.00$/, '') === digits
  })
}

/** "Taxi", "RD$ 900" typed by hand: whole cents, or null if it is not a positive amount. */
export function parseCents(text: string): number | null {
  const clean = text.replace(/[^\d.]/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  const cents = Math.round(Number(clean) * 100)
  return cents > 0 ? cents : null
}

export function expenseCents(expense: ChosenExpense): number {
  return expense.kind === 'tx' ? Math.abs(expense.tx.amount_cents) : expense.amount_cents
}

function expenseCurrency(expense: ChosenExpense): string {
  return expense.kind === 'tx' ? expense.tx.currency : expense.currency
}

/** The proposed group name: the first expense's merchant or description. */
export function defaultName(expenses: readonly ChosenExpense[]): string {
  const first = expenses[0]
  if (!first) return ''
  const name = first.kind === 'tx' ? first.tx.merchant : first.description
  return name.trim().slice(0, 80)
}

export interface SplitPreview {
  currency: string | null // null: more than one currency
  totalCents: number // the expenses
  paidCents: number // the credits
  people: number // the user and each different payer
  equalCents: number // a share split equally (rounded down)
  /** "Their share is what they paid" is possible: one currency, not over the expenses. */
  paidAllowed: boolean
  /** Split equally it is already settled: each payer paid an equal share (±1 cent). */
  equalSettles: boolean
  mineCents: number // the user's share when theirs is what they paid
  defaultSplit: CreditSplit
}

/** The numbers of the confirmation step, and its default split: equal when that already
 * settles it (or "paid" is not possible), else "their share is what they paid". */
export function splitPreview(expenses: readonly ChosenExpense[], credits: readonly ChosenCredit[]): SplitPreview {
  const currencies = new Set([
    ...expenses.map(expenseCurrency),
    ...credits.map((c) => c.tx.currency),
  ])
  const currency = currencies.size === 1 ? [...currencies][0] : null
  const totalCents = expenses.reduce((sum, e) => sum + expenseCents(e), 0)
  const paidCents = credits.reduce((sum, c) => sum + Math.abs(c.tx.amount_cents), 0)
  const byPayer = new Map<string, number>()
  for (const credit of credits) {
    byPayer.set(credit.payer.key, (byPayer.get(credit.payer.key) ?? 0) + Math.abs(credit.tx.amount_cents))
  }
  const people = byPayer.size + 1
  const equalCents = Math.floor(totalCents / people)
  const paidAllowed = currency !== null && paidCents <= totalCents
  const equalSettles =
    currency !== null && [...byPayer.values()].every((paid) => Math.abs(paid - totalCents / people) <= 1)
  return {
    currency,
    totalCents,
    paidCents,
    people,
    equalCents,
    paidAllowed,
    equalSettles,
    mineCents: totalCents - paidCents,
    defaultSplit: equalSettles || !paidAllowed ? 'equal' : 'paid',
  }
}

export function creditGroupBody(
  name: string,
  split: CreditSplit,
  expenses: readonly ChosenExpense[],
  credits: readonly ChosenCredit[],
): CreditGroupBody {
  return {
    name: name.trim(),
    split,
    payments: credits.map((c) => ({ fingerprint: c.tx.fingerprint, person: c.payer.person })),
    expenses: expenses.map((e) =>
      e.kind === 'tx'
        ? { fingerprint: e.tx.fingerprint }
        : { amount_cents: e.amount_cents, currency: e.currency, day: e.day, description: e.description },
    ),
  }
}

/** What a person owes the user in a group after the user pays them `paidCents` (their balance
 * goes up: a debt of the user shrinks, or they come to owe it back). */
export function afterPaying(
  balanceCents: number,
  paidCents: number,
): { kind: 'owes' | 'owe' | 'settled'; cents: number } {
  const after = balanceCents + paidCents
  if (after === 0) return { kind: 'settled', cents: 0 }
  return after > 0 ? { kind: 'owes', cents: after } : { kind: 'owe', cents: -after }
}
