// Types of Shared, the ledger (src/michelito/web/ledger_schemas.py): money in whole cents, ISO
// dates. Balances are from the user's point of view: positive, owed to the user; negative, the
// user owes.
import type { CurrencyCents, LinkedTx } from './api'

/** A transaction's place in the ledger (`Tx.ledger`): the entry it comes from, the payment it
 * reconciles, or (`group`) the user's share of an expense someone else paid. */
export interface LedgerRef {
  group_id: number
  group_name: string
  role: 'entry' | 'payment' | 'group'
  entry_id: number | null
  payment_id: number | null
  my_share_cents: number | null
  pending_cents: number | null // still owed to the user for the entry
  currency: string
  paid_by_name: string // who paid the entry (empty: the user)
}

export interface Contact {
  id: number
  name: string
  is_me: boolean
  aliases: string[]
}

/** A name seen in incoming transfers that is not a contact yet ("seen in your bank"). */
export interface BankName {
  name: string
  raw: string // as the bank prints it: it becomes the alias
  count: number
  last_day: string
}

export interface Contacts {
  contacts: Contact[] // the user first, then by name
  bank_names: BankName[]
  recent_payers: number[] // who paid recently, most recent first
}

/** "In total ≈": balances in two currencies as one, at the current month's rate (positive: owed
 * to the user). */
export interface Approx {
  currency: string
  cents: number
}

/** A rate used (RD$ per US$, as stored: "63.7000") and the month it comes from. */
export interface RateUsed {
  value: string
  month: string
}

export interface PersonGroup {
  group_id: number
  group_name: string
  archived: boolean
  balance: CurrencyCents[]
  written_off: boolean
  leftover: CurrencyCents[] // exchange leftovers taken as settled, signed
}

/** A contact across groups (the People row and the person view). */
export interface Person {
  id: number
  name: string
  aliases: string[]
  balance: CurrencyCents[]
  group_count: number
  groups: PersonGroup[]
  total: Approx | null // with a balance in two currencies
}

export interface GroupRow {
  id: number
  name: string
  archived: boolean
  balance: CurrencyCents[] // owed minus owing: do not show (it cancels people)
  owed_to_me: CurrencyCents[] // what the people who owe the user add up to
  i_owe: CurrencyCents[] // what the user owes the people they owe
  people: string[] // every member but the user
  last_day: string | null
  unattributed: number
  total: Approx | null // with balances in two currencies
}

export interface Total {
  currency: string
  owed_to_me_cents: number
  i_owe_cents: number
}

export interface SharedHome {
  totals: Total[]
  people: Person[]
  groups: GroupRow[]
  review_people: boolean // "Review your people" (once, after the migration)
  suggestions: LinkedTx[] // "these dinners look shared", only without groups
}

export interface Member {
  id: number
  name: string
  is_me: boolean
  written_off: boolean
  balance: CurrencyCents[] // what they owe the user in this group (net)
  leftover: CurrencyCents[] // exchange leftovers taken as settled, signed
  leftover_settled: boolean // the per-person toggle
  total: Approx | null // with a balance in two currencies
}

export interface SplitLine {
  contact_id: number
  name: string
  is_me: boolean
  cents: number
  parts?: number | null // a split by parts: their number of parts
}

export interface Effect {
  kind: 'owe' | 'lent' | 'none'
  cents: number
}

export type SplitMode = 'equal' | 'exact' | 'parts'

export interface Entry {
  kind: 'entry'
  id: number
  day: string
  description: string
  amount_cents: number
  currency: string
  paid_by: number
  paid_by_name: string
  paid_by_me: boolean
  category_id: number | null
  split: SplitMode
  splits: SplitLine[]
  effect: Effect
  my_share_cents: number
  pending_cents: number
  written_off_cents: number
  debt_pending_cents: number
  transaction: LinkedTx | null
}

export interface Payment {
  kind: 'payment'
  id: number
  day: string
  from_contact: number | null // null: unattributed
  from_name: string
  to_contact: number
  to_name: string
  from_me: boolean
  to_me: boolean
  amount_cents: number // received
  settles_cents: number // what it settles: what was sent once a difference was accepted
  currency: string
  sent_cents: number | null
  difference_cents: number | null // sent − received (null: unknown or equal)
  accepted: boolean
  note: string
  excess_cents: number
  unconverted: boolean
  transaction: LinkedTx | null
  allocations: Allocation[] // who it is for, the payer first ("Paid for others")
  rate: RateUsed | null // the rate it settled claims in the other currency with
}

/** Who a payment settles with: the person and how much. */
export interface Allocation {
  contact_id: number
  name: string
  is_me: boolean
  cents: number
}

/** An expense or payment that names a person (before removing them from a group). */
export interface UsedIn {
  id: number
  day: string
  description: string
  amount_cents: number
  currency: string
  after: SplitLine[] // an expense with their share: how it would be split without them
  to_payer: boolean // nobody else is left: it becomes the payer's alone
  paid_by_name: string
  paid_by_me: boolean
}

/** Where a person appears in a group: `resplittable` when they only have shares. */
export interface MemberUsage {
  contact_id: number
  name: string
  shares: UsedIn[]
  paid: UsedIn[]
  payments: UsedIn[]
  free: boolean
  resplittable: boolean
  message: string
}

export type TimelineItem = Entry | Payment

/** "Ana paid RD$ 38,440 too much and Beto owes US$ 629.31. Was that payment for Beto too?" */
export interface CoverSuggestion {
  payment_id: number // the oldest of them
  payment_ids: number[] // every payment of the payer it is about, oldest first
  payer_id: number
  payer_name: string
  covers: number[]
  names: string[]
  excess_cents: number
  currency: string
  owed: CurrencyCents[]
  text: string
}

/** One proposed allocation: what it covers of that person (payment's currency), what they owed
 * then and, when their claims are in the other currency, the part converted. */
export interface Proposed {
  contact_id: number
  name: string
  cents: number
  owed_cents: number
  equivalent: CurrencyCents | null
}

/** One payment of a suggestion with its proposed allocations (the payer first). */
export interface CoverPayment {
  payment_id: number
  day: string
  amount_cents: number // what it settles
  currency: string
  allocations: Proposed[]
  rate: RateUsed | null
}

/** A person's balance in the group once the plan is applied. */
export interface CoverAfter {
  contact_id: number
  name: string
  balance: CurrencyCents[]
  leftover: CurrencyCents[]
}

/** "Yes" to a suggestion: each payment's proposal, in order, and the balances after. */
export interface CoverPlan {
  text: string
  payments: CoverPayment[]
  after: CoverAfter[]
}

export interface CoverBody {
  payments: { payment_id: number; allocations: ShareBody[] }[]
}

export interface Proposal {
  currency: string
  allocations: Proposed[] // the payer first
  rate: RateUsed | null // the payment month's rate, when a claim is in the other currency
}

export interface Group {
  id: number
  name: string
  archived: boolean
  category_id: number | null
  members: Member[] // the user first
  balance: CurrencyCents[]
  owed_to_me: CurrencyCents[]
  i_owe: CurrencyCents[]
  excess: CurrencyCents[]
  unattributed: Payment[]
  timeline: TimelineItem[] // most recent first
  total: Approx | null // with balances in two currencies
  cover: CoverSuggestion | null // "Was that payment for someone else too?"
}

// --- Requests ------------------------------------------------------------------------------

/** A person for a group: an existing contact or a new one (`alias`: as the bank prints it). */
export interface NewPerson {
  contact_id?: number
  name?: string
  alias?: string
}

export interface ShareBody {
  contact_id: number
  cents: number
}

export interface PartsBody {
  contact_id: number
  parts: number
}

/** An expense: with `fingerprint` ("I paid it") the bank sets amount, date and description. */
export interface EntryBody {
  fingerprint?: string
  paid_by?: number
  amount_cents?: number
  currency?: string
  day?: string
  description?: string
  category_id?: number | null
  split: SplitMode
  people?: number[]
  shares?: ShareBody[]
  parts?: PartsBody[]
}

export interface PaymentBody {
  from_contact: number | null
  to_contact: number
  amount_cents: number
  currency: string
  day: string
  sent_cents?: number
  fingerprint?: string
  allocations?: ShareBody[] // "Also pays for…": adding up to amount_cents, the payer included
}

export interface PaymentPatch {
  from_contact?: number
  accepted?: boolean
  fingerprint?: string
  unlink?: boolean
}
