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

export interface PersonGroup {
  group_id: number
  group_name: string
  archived: boolean
  balance: CurrencyCents[]
  written_off: boolean
}

/** A contact across groups (the People row and the person view). */
export interface Person {
  id: number
  name: string
  aliases: string[]
  balance: CurrencyCents[]
  group_count: number
  groups: PersonGroup[]
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
}

export interface SplitLine {
  contact_id: number
  name: string
  is_me: boolean
  cents: number
}

export interface Effect {
  kind: 'owe' | 'lent' | 'none'
  cents: number
}

export type SplitMode = 'equal' | 'exact'

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
  currency: string
  sent_cents: number | null
  difference_cents: number | null // sent − received (null: unknown or equal)
  accepted: boolean
  note: string
  excess_cents: number
  unconverted: boolean
  transaction: LinkedTx | null
}

export type TimelineItem = Entry | Payment

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
}

export interface PaymentBody {
  from_contact: number | null
  to_contact: number
  amount_cents: number
  currency: string
  day: string
  sent_cents?: number
  fingerprint?: string
}

export interface PaymentPatch {
  from_contact?: number
  accepted?: boolean
  fingerprint?: string
  unlink?: boolean
}
