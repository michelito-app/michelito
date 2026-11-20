// Shared (the ledger) in the interface, pure: texts, the split math the form previews and the
// people picker's order. The server does the real math (src/michelito/analysis/ledger.py); the
// preview mirrors its equal-split cent rule so what the form shows is what gets saved.
import { t } from '@/i18n'
import type { CurrencyCents } from './api'
import { formatMoney } from './links'
import { fold } from './picker'
import { joinPhrases } from './summary'
import type {
  BankName,
  Contact,
  Effect,
  Entry,
  Member,
  NewPerson,
  PartsBody,
  Payment,
  Person,
  ShareBody,
  SplitLine,
  SplitMode,
  Total,
} from './sharedApi'

/** The user is "You"; anyone else, by name. */
export function displayName(name: string, isMe: boolean): string {
  return isMe ? t('shared.you') : name
}

/** Up to two initials for an avatar: "Ana Ficticia" → "AF", "luis" → "L". */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  return words
    .slice(0, 2)
    .map((word) => word.charAt(0).toLocaleUpperCase())
    .join('')
}

/** Whether a balance is owed to the user, owed by the user, or settled (the first currency that
 * is not zero decides when they point different ways). */
export type Tone = 'owed' | 'owe' | 'settled'

export function balanceTone(balance: readonly CurrencyCents[]): Tone {
  const first = balance.find((part) => part.cents !== 0)
  if (!first) return 'settled'
  return first.cents > 0 ? 'owed' : 'owe'
}

/** A person's balance: "owes you RD$ 1,250", "you owe RD$ 300" or "Settled"; one part per
 * currency. */
export function personBalanceText(balance: readonly CurrencyCents[]): string {
  const parts = balance.filter((part) => part.cents !== 0)
  if (parts.length === 0) return t('shared.balance.settled')
  return parts
    .map((part) => {
      const amount = formatMoney(Math.abs(part.cents), part.currency)
      return part.cents > 0
        ? t('shared.balance.owesYou', { amount })
        : t('shared.balance.youOwe', { amount })
    })
    .join(' · ')
}

/** A group's balance in a list: "owed to you RD$ 4,000", "you owe RD$ 300" or "Settled". */
export function groupBalanceText(balance: readonly CurrencyCents[]): string {
  const parts = balance.filter((part) => part.cents !== 0)
  if (parts.length === 0) return t('shared.balance.settled')
  return parts
    .map((part) => {
      const amount = formatMoney(Math.abs(part.cents), part.currency)
      return part.cents > 0
        ? t('shared.balance.owedToYou', { amount })
        : t('shared.balance.youOweGroup', { amount })
    })
    .join(' · ')
}

/** The home's net lines: "Owed to you RD$ X · You owe RD$ Y", RD$ first and one line per extra
 * currency; none when everything is settled. */
export function totalsLines(totals: readonly Total[]): string[] {
  const order = (currency: string) => (currency === 'DOP' ? 0 : 1)
  return [...totals]
    .filter((total) => total.owed_to_me_cents !== 0 || total.i_owe_cents !== 0)
    .sort((a, b) => order(a.currency) - order(b.currency) || a.currency.localeCompare(b.currency))
    .map((total) =>
      t('shared.totals.line', {
        owed: formatMoney(total.owed_to_me_cents, total.currency),
        owe: formatMoney(total.i_owe_cents, total.currency),
      }),
    )
}

/** A group's two sides as signed parts: what people owe the user (positive) and what the user
 * owes (negative), each currency apart and never netted (different people never cancel). */
export function groupSides(owed: readonly CurrencyCents[], owe: readonly CurrencyCents[]): CurrencyCents[] {
  return [
    ...owed.filter((part) => part.cents > 0),
    ...owe.filter((part) => part.cents > 0).map((part) => ({ ...part, cents: -part.cents })),
  ]
}

/** The group's one sentence: "Owed to you RD$ 2,100 in this group", "You owe …" or settled. */
export function groupSentence(balance: readonly CurrencyCents[]): string {
  const parts = balance.filter((part) => part.cents !== 0)
  if (parts.length === 0) return t('shared.group.sentence.settled')
  const owed = parts.filter((part) => part.cents > 0)
  const owe = parts.filter((part) => part.cents < 0)
  const list = (items: CurrencyCents[]) =>
    items.map((part) => formatMoney(Math.abs(part.cents), part.currency)).join(' + ')
  const sentences = []
  if (owed.length) sentences.push(t('shared.group.sentence.owed', { amount: list(owed) }))
  if (owe.length) sentences.push(t('shared.group.sentence.owe', { amount: list(owe) }))
  return sentences.join(' · ')
}

/** People with a balance first (the API's order) and the settled ones apart. */
export function splitSettled(people: readonly Person[]): { open: Person[]; settled: Person[] } {
  const open = people.filter((person) => balanceTone(person.balance) !== 'settled')
  const settled = people.filter((person) => balanceTone(person.balance) === 'settled')
  return { open, settled }
}

// --- Split ---------------------------------------------------------------------------------

/** `total` cents divided among `people` (in that order, without repeats); the leftover cent(s)
 * go to the payer, or to the first person when the payer is not among them (the server's rule). */
export function equalShares(total: number, people: readonly number[], payer: number): ShareBody[] {
  const chosen = [...new Set(people)]
  if (chosen.length === 0) return []
  const base = Math.floor(total / chosen.length)
  const left = total - base * chosen.length
  const taker = chosen.includes(payer) ? payer : chosen[0]
  return chosen.map((id) => ({ contact_id: id, cents: base + (id === taker ? left : 0) }))
}

/** `total` cents by parts: each person gets total × parts / total parts rounded down to the
 * cent; the leftover cent(s) go to the payer, or to the first person (the server's rule). */
export function partsShares(
  total: number,
  people: readonly number[],
  parts: Readonly<Record<number, number>>,
  payer: number,
): ShareBody[] {
  const chosen = [...new Set(people)]
  if (chosen.length === 0) return []
  const counts = chosen.map((id) => Math.max(1, Math.floor(parts[id] ?? 1)))
  const sum = counts.reduce((a, b) => a + b, 0)
  const cents = counts.map((count) => Math.floor((total * count) / sum))
  const taker = chosen.includes(payer) ? chosen.indexOf(payer) : 0
  cents[taker] += total - cents.reduce((a, b) => a + b, 0)
  return chosen.map((id, index) => ({ contact_id: id, cents: cents[index] }))
}

/** What is missing (positive) or over (negative) for exact shares to add up to `total`. */
export function shortfall(total: number, shares: readonly number[]): number {
  return total - shares.reduce((sum, cents) => sum + cents, 0)
}

/** "RD$ 200 missing", "RD$ 50 over" or that it adds up. */
export function shortfallText(missing: number, currency: string): string {
  if (missing > 0) return t('shared.split.missing', { amount: formatMoney(missing, currency) })
  if (missing < 0) return t('shared.split.over', { amount: formatMoney(-missing, currency) })
  return t('shared.split.addsUp')
}

/** How an expense is being split, as the form edits it. `shares`: what was typed per person
 * (exact mode); `parts`: each person's number of parts (parts mode, 1 when missing). */
export interface SplitDraft {
  mode: SplitMode
  people: readonly number[]
  shares: Readonly<Record<number, string>>
  parts?: Readonly<Record<number, number>>
}

/** Equal among everyone given. */
export function equalDraft(people: readonly number[]): SplitDraft {
  return { mode: 'equal', people: [...people], shares: {} }
}

/** Cents as an exact field shows them: "1250.50". */
export function centsField(cents: number): string {
  return (cents / 100).toFixed(2)
}

/** The draft's current amounts per person, whatever the mode (exact: what was typed, as cents;
 * a field that is not an amount counts as 0). */
export function draftAmounts(draft: SplitDraft, total: number, payer: number): Record<number, number> {
  if (draft.mode === 'equal') {
    return Object.fromEntries(equalShares(total, draft.people, payer).map((s) => [s.contact_id, s.cents]))
  }
  if (draft.mode === 'parts') {
    return Object.fromEntries(
      partsShares(total, draft.people, draft.parts ?? {}, payer).map((s) => [s.contact_id, s.cents]),
    )
  }
  return Object.fromEntries(
    draft.people.map((id) => [id, amountCents((draft.shares[id] ?? '').trim() || '0', true) ?? 0]),
  )
}

/** The draft in another mode, starting from the current split: exact amounts are prefilled with
 * what each person has now (so only the different one needs editing); parts keep the parts given
 * before, or 1 each. */
export function switchMode(draft: SplitDraft, mode: SplitMode, total: number, payer: number): SplitDraft {
  if (mode === draft.mode) return draft
  if (mode === 'exact') {
    const amounts = draftAmounts(draft, total, payer)
    return {
      ...draft,
      mode,
      shares: Object.fromEntries(draft.people.map((id) => [id, centsField(amounts[id] ?? 0)])),
    }
  }
  if (mode === 'parts') {
    const parts = Object.fromEntries(draft.people.map((id) => [id, draft.parts?.[id] ?? 1]))
    return { ...draft, mode, parts }
  }
  return { ...draft, mode }
}

/** Checks or unchecks a person, keeping `order` (the group's): in exact mode a new person starts
 * at 0 and the shortfall shows what to fill; in parts mode, at 1 part. */
export function togglePerson(draft: SplitDraft, id: number, order: readonly number[]): SplitDraft {
  const chosen = new Set(draft.people)
  if (chosen.has(id)) {
    const shares = { ...draft.shares }
    delete shares[id]
    return { ...draft, people: draft.people.filter((p) => p !== id), shares }
  }
  const people = order.filter((p) => p === id || chosen.has(p))
  if (draft.mode === 'exact') return { ...draft, people, shares: { ...draft.shares, [id]: centsField(0) } }
  if (draft.mode === 'parts') return { ...draft, people, parts: { ...draft.parts, [id]: 1 } }
  return { ...draft, people }
}

/** One person's parts, from 1 up. */
export function setParts(draft: SplitDraft, id: number, parts: number): SplitDraft {
  return { ...draft, parts: { ...draft.parts, [id]: Math.max(1, Math.min(999, Math.floor(parts))) } }
}

/** The typed exact shares in cents (empty or invalid counts as 0); null if any is not an amount. */
export function exactCents(draft: SplitDraft): Record<number, number> | null {
  const found: Record<number, number> = {}
  for (const id of draft.people) {
    const text = (draft.shares[id] ?? '').trim()
    if (text === '') {
      found[id] = 0
      continue
    }
    const cents = amountCents(text, true)
    if (cents === null) return null
    found[id] = cents
  }
  return found
}

/** "1,250.50" → 125050; null unless a non-negative amount with up to two decimals (positive
 * unless `zero`). */
export function amountCents(text: string, zero = false): number | null {
  const clean = text.trim().replace(/^(RD|US)?\$\s*/i, '').replaceAll(',', '')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  const cents = Math.round(Number(clean) * 100)
  if (cents === 0 && !zero) return null
  return cents
}

/** The split's missing amount (exact mode), or 0 when it adds up or is equal or by parts; null
 * when a typed share is not an amount. */
export function draftShortfall(draft: SplitDraft, total: number): number | null {
  if (draft.mode !== 'exact') return 0
  const cents = exactCents(draft)
  return cents === null ? null : shortfall(total, Object.values(cents))
}

/** Is the split complete: someone checked and, if exact, the amounts add up? */
export function draftValid(draft: SplitDraft, total: number): boolean {
  if (draft.people.length === 0) return false
  if (draft.mode !== 'exact') return true
  return total > 0 && draftShortfall(draft, total) === 0
}

/** The split line: "Equal among 4 · RD$ 1,250 each", "All for Ana", "Exact amounts" or "By
 * parts · 5 parts". */
export function splitSummary(
  draft: SplitDraft,
  total: number,
  currency: string,
  members: readonly Pick<Member, 'id' | 'name' | 'is_me'>[],
): string {
  if (draft.mode === 'exact') return t('shared.add.splitExact')
  if (draft.mode === 'parts') {
    const count = draft.people.reduce((sum, id) => sum + (draft.parts?.[id] ?? 1), 0)
    return t('shared.add.splitParts', { count })
  }
  if (draft.people.length === 1) {
    const member = members.find((m) => m.id === draft.people[0])
    return t('shared.add.splitEqualOne', {
      name: member ? displayName(member.name, member.is_me) : '',
    })
  }
  const each = draft.people.length ? Math.floor(total / draft.people.length) : 0
  return t('shared.add.splitEqual', {
    count: draft.people.length,
    amount: formatMoney(each, currency),
  })
}

/** The request's split fields: `people` (equal), `parts` or `shares` (exact, without zeros). */
export function splitFields(draft: SplitDraft): {
  split: SplitMode
  people?: number[]
  shares?: ShareBody[]
  parts?: PartsBody[]
} {
  if (draft.mode === 'equal') return { split: 'equal', people: [...draft.people] }
  if (draft.mode === 'parts') {
    return {
      split: 'parts',
      parts: draft.people.map((id) => ({ contact_id: id, parts: draft.parts?.[id] ?? 1 })),
    }
  }
  const cents = exactCents(draft) ?? {}
  return {
    split: 'exact',
    shares: draft.people
      .map((id) => ({ contact_id: id, cents: cents[id] ?? 0 }))
      .filter((share) => share.cents > 0),
  }
}

/** A saved entry's split as a draft (to edit it, in its mode). */
export function draftOf(entry: Pick<Entry, 'split' | 'splits'>): SplitDraft {
  const people = entry.splits.map((s) => s.contact_id)
  if (entry.split === 'equal') return equalDraft(people)
  if (entry.split === 'parts') {
    return {
      mode: 'parts',
      people,
      shares: {},
      parts: Object.fromEntries(entry.splits.map((s) => [s.contact_id, s.parts ?? 1])),
    }
  }
  return {
    mode: 'exact',
    people,
    shares: Object.fromEntries(entry.splits.map((s) => [s.contact_id, centsField(s.cents)])),
  }
}

/** How an expense would be split without someone: "You RD$ 450 · Carola RD$ 450". */
export function resplitText(
  lines: readonly Pick<SplitLine, 'name' | 'is_me' | 'cents'>[],
  currency: string,
): string {
  return lines.map((line) => `${displayName(line.name, line.is_me)} ${formatMoney(line.cents, currency)}`).join(' · ')
}

/** A split line in the entry detail: "RD$ 1,632", or "2 parts · RD$ 1,632" by parts. */
export function splitLineText(line: Pick<SplitLine, 'cents' | 'parts'>, currency: string): string {
  const amount = formatMoney(line.cents, currency)
  if (line.parts == null) return amount
  return t('shared.detail.partsLine', { count: line.parts, amount })
}

// --- Timeline ------------------------------------------------------------------------------

/** The expense row: "Dinner at Bocao · Ana paid · RD$ 5,000". */
export function entryLine(entry: Pick<Entry, 'description' | 'paid_by_name' | 'paid_by_me' | 'amount_cents' | 'currency'>): string {
  return t('shared.entry.line', {
    description: entry.description,
    payer: entry.paid_by_me ? t('shared.youLower') : entry.paid_by_name,
    amount: formatMoney(entry.amount_cents, entry.currency),
  })
}

/** The expense's effect on the user: "you owe RD$ 1,250", "you lent RD$ 3,750" or "not yours". */
export function effectText(effect: Effect, currency: string): string {
  const amount = formatMoney(effect.cents, currency)
  if (effect.kind === 'owe') return t('shared.entry.owe', { amount })
  if (effect.kind === 'lent') return t('shared.entry.lent', { amount })
  return t('shared.entry.none')
}

/** The payment row: "Luis → You · RD$ 1,000" (unattributed: "Unassigned → You"); a payment on
 * behalf of others adds who else it covers: "Javier → You · RD$ 1,632 (covers Gordo)". */
export function paymentLine(
  payment: Pick<Payment, 'from_contact' | 'from_name' | 'from_me' | 'to_name' | 'to_me' | 'amount_cents' | 'currency'> &
    Partial<Pick<Payment, 'allocations'>>,
): string {
  const from =
    payment.from_contact === null
      ? t('shared.payment.unknown')
      : displayName(payment.from_name, payment.from_me)
  const line = t('shared.payment.line', {
    from,
    to: displayName(payment.to_name, payment.to_me),
    amount: formatMoney(payment.amount_cents, payment.currency),
  })
  const covered = coveredText(payment)
  return covered ? `${line} ${covered}` : line
}

/** "(covers Gordo)" when a payment covers other people besides the payer; null otherwise. */
export function coveredText(
  payment: Pick<Payment, 'from_contact'> & Partial<Pick<Payment, 'allocations'>>,
): string | null {
  const allocations = payment.allocations ?? []
  const others = allocations.filter((a) => a.contact_id !== payment.from_contact)
  if (others.length === 0) return null
  const names = joinPhrases(others.map((a) => displayName(a.name, a.is_me)))
  return t('shared.payment.covers', { names })
}

/** What a "Paid for others" payment starts with: each covered person's balance (what they owe
 * the user, in `currency`), the payer's own included. */
export function allocationDraft(
  members: readonly Pick<Member, 'id' | 'balance'>[],
  people: readonly number[],
  currency: string,
): Record<number, string> {
  return Object.fromEntries(
    people.map((id) => {
      const owed = members.find((m) => m.id === id)?.balance.find((b) => b.currency === currency)?.cents ?? 0
      return [id, centsField(Math.max(owed, 0))]
    }),
  )
}

/** The typed allocations in cents (blank counts as 0); null if any is not an amount. */
export function allocationCents(
  people: readonly number[],
  typed: Readonly<Record<number, string>>,
): Record<number, number> | null {
  const found: Record<number, number> = {}
  for (const id of people) {
    const cents = amountCents((typed[id] ?? '').trim() || '0', true)
    if (cents === null) return null
    found[id] = cents
  }
  return found
}

/** Items (most recent first) grouped by their month, in order. */
export function byMonth<T extends { day: string }>(items: readonly T[]): { month: string; items: T[] }[] {
  const groups: { month: string; items: T[] }[] = []
  for (const item of items) {
    const month = item.day.slice(0, 7)
    const last = groups[groups.length - 1]
    if (last && last.month === month) last.items.push(item)
    else groups.push({ month, items: [item] })
  }
  return groups
}

// --- Payments ------------------------------------------------------------------------------

/** What a "Record payment" starts with for a person: who pays whom (from their balance: if they
 * owe the user, they pay) and the whole amount, in the first currency with a balance. */
export interface PaymentDraft {
  received: boolean // true: the person paid the user
  cents: number
  currency: string
}

export function paymentDraft(balance: readonly CurrencyCents[]): PaymentDraft {
  const first = balance.find((part) => part.cents !== 0)
  if (!first) return { received: true, cents: 0, currency: 'DOP' }
  return { received: first.cents > 0, cents: Math.abs(first.cents), currency: first.currency }
}

/** A warning when a payment goes against the balance or beyond it: the rest is not lost, it
 * becomes a claim the other way (the backend does the same). `balance`: the person's, positive
 * when they owe the user; `received`: they pay the user. Null when it fits. */
export function paymentWarning(
  balance: readonly CurrencyCents[],
  received: boolean,
  cents: number | null,
  currency: string,
  name: string,
): string | null {
  if (!cents || cents <= 0) return null
  const signed = balance.find((part) => part.currency === currency)?.cents ?? 0
  const due = Math.max(received ? signed : -signed, 0)
  if (cents <= due) return null
  const rest = formatMoney(cents - due, currency)
  if (due === 0) {
    return received
      ? t('shared.pay.warnAgainst', { name, amount: rest })
      : t('shared.pay.warnAgainstYou', { name, amount: rest })
  }
  return received
    ? t('shared.pay.warnOver', { name, amount: rest })
    : t('shared.pay.warnOverYou', { name, amount: rest })
}

/** "Sent X · Received Y · difference Z" when a payment's two ends differ. */
export function differenceText(payment: Pick<Payment, 'sent_cents' | 'amount_cents' | 'difference_cents' | 'currency'>): string | null {
  if (payment.difference_cents === null || payment.sent_cents === null) return null
  return t('shared.detail.difference', {
    sent: formatMoney(payment.sent_cents, payment.currency),
    received: formatMoney(payment.amount_cents, payment.currency),
    difference: formatMoney(Math.abs(payment.difference_cents), payment.currency),
  })
}

/** Who to preselect in "Paid by": the most recent payer among `candidates`, else the first. */
export function defaultPayer(candidates: readonly number[], recent: readonly number[]): number | null {
  return recent.find((id) => candidates.includes(id)) ?? candidates[0] ?? null
}

// --- People picker -------------------------------------------------------------------------

export type PeopleOption =
  | { kind: 'contact'; contact: Contact; alias: string | null }
  | { kind: 'bank'; bank: BankName }
  | { kind: 'create'; name: string }

/** The picker's options for `query`, in this order: contacts (by name or alias), names seen in
 * the bank's transfers, and "Create "query"" (unless the name already exists). `taken`: contact
 * ids already chosen; `takenNames`: new names already chosen. */
export function peopleOptions(
  query: string,
  contacts: readonly Contact[],
  bankNames: readonly BankName[],
  taken: ReadonlySet<number>,
  takenNames: ReadonlySet<string> = new Set(),
  limit = 6,
): PeopleOption[] {
  const wanted = fold(query.trim())
  if (wanted === '') return []
  const options: PeopleOption[] = []
  const names = new Set<string>()
  for (const contact of contacts) {
    if (contact.is_me) continue
    names.add(fold(contact.name))
    contact.aliases.forEach((alias) => names.add(fold(alias)))
    if (taken.has(contact.id)) continue
    if (fold(contact.name).includes(wanted)) {
      options.push({ kind: 'contact', contact, alias: null })
      continue
    }
    const alias = contact.aliases.find((a) => fold(a).includes(wanted))
    if (alias) options.push({ kind: 'contact', contact, alias })
  }
  for (const bank of bankNames) {
    if (takenNames.has(fold(bank.name))) continue
    if (fold(bank.name).includes(wanted) || fold(bank.raw).includes(wanted)) {
      options.push({ kind: 'bank', bank })
    }
  }
  const exact = names.has(wanted) || takenNames.has(wanted) ||
    bankNames.some((b) => fold(b.name) === wanted)
  const found = options.slice(0, limit)
  if (!exact) found.push({ kind: 'create', name: query.trim() })
  return found
}

/** A person chosen for a group: an existing contact, a name seen in the bank (it becomes their
 * alias) or a new name. */
export interface ChosenPerson {
  key: string
  label: string
  person: NewPerson
}

/** The request body of a chosen option. */
export function chosenOf(option: PeopleOption): ChosenPerson {
  switch (option.kind) {
    case 'contact':
      return {
        key: `c${option.contact.id}`,
        label: option.contact.name,
        person: { contact_id: option.contact.id },
      }
    case 'bank':
      return {
        key: `n${fold(option.bank.name)}`,
        label: option.bank.name,
        person: { name: option.bank.name, alias: option.bank.raw },
      }
    case 'create':
      return { key: `n${fold(option.name)}`, label: option.name, person: { name: option.name } }
  }
}
