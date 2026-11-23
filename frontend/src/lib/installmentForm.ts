// The installment plan forms (pure logic): "It is an installment…" (from a charge) and "Edit
// plan". Their state as typed, the installment numbers as earlier charges are unchecked, and
// the request bodies (the server checks everything again: src/michelito/web/installment_routes.py).
import { t } from '@/i18n'
import type {
  InstallmentBody,
  InstallmentDraft,
  InstallmentEdit,
  InstallmentOwner,
  InstallmentPerson,
  InstallmentPlan,
} from './api'
import { COUNT_MAX, COUNT_MIN, DEFAULT_COUNT, NAME_MAX } from './installments'

/** The owner ("For"): the user, a known person (their contact id) or a new person typed by name. */
export type OwnerChoice = 'me' | 'new' | number

export interface OwnerForm {
  owner: OwnerChoice
  newName: string
}

/** "It is an installment…" as typed (numbers as text until saved). */
export interface PlanForm extends OwnerForm {
  name: string
  count: string
  /** Which installment it is, typed only when the form asks (see `numberAsk`). */
  number: string
  /** The earlier identical charges that are part of the plan (fingerprints). */
  checked: readonly string[]
}

/** "Edit plan" as typed. */
export interface EditForm extends OwnerForm {
  name: string
  count: string
}

type Result<T> = { body: T; error: null } | { body: null; error: string }

function fail<T>(error: string): Result<T> {
  return { body: null, error }
}

function wholeNumber(text: string): number | null {
  const clean = text.trim()
  return /^\d+$/.test(clean) ? Number(clean) : null
}

function monthIndex(month: string): number {
  return Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7)) - 1
}

/** Which installment falls in `month` when the first one is in `firstMonth` (1 for the same). */
export function numberBetween(firstMonth: string, month: string): number {
  return monthIndex(month) - monthIndex(firstMonth) + 1
}

/** The form prefilled from the draft: its name, every earlier charge checked, six installments
 * (or as many as the number needs) and, when known, the person the charge is shared with. */
export function initialForm(draft: InstallmentDraft, preferred: number | null = null): PlanForm {
  return {
    name: draft.name.slice(0, NAME_MAX),
    count: String(Math.max(DEFAULT_COUNT, draft.number)),
    number: '',
    checked: draft.earlier.map((charge) => charge.fingerprint),
    owner: preferred ?? 'me',
    newName: '',
  }
}

export interface Numbering {
  /** The installment each checked earlier charge is (unchecked ones are absent). */
  earlier: ReadonlyMap<string, number>
  /** The installment the chosen charge is. */
  number: number
}

/** The numbers as the server deduces them: consecutive months from the earliest checked charge
 * (installment 1) to the chosen one; nothing checked, the chosen one is installment 1. */
export function numbering(
  draft: Pick<InstallmentDraft, 'earlier' | 'month'>,
  checked: readonly string[],
): Numbering {
  const kept = draft.earlier.filter((charge) => checked.includes(charge.fingerprint))
  const first = kept[0]?.day.slice(0, 7) ?? draft.month
  return {
    earlier: new Map(
      kept.map((charge) => [charge.fingerprint, numberBetween(first, charge.day.slice(0, 7))]),
    ),
    number: numberBetween(first, draft.month),
  }
}

/** Whether the form asks which installment it is: the card's data starts at the charge
 * ('unknown') or the deduced number is past the number of installments ('overCount'). */
export function numberAsk(
  draft: Pick<InstallmentDraft, 'number_known'>,
  deduced: number,
  count: string,
): 'unknown' | 'overCount' | null {
  if (!draft.number_known) return 'unknown'
  const total = wholeNumber(count)
  return total !== null && deduced > total ? 'overCount' : null
}

/** The owner as the API takes it: {} for the user, the person's id, or a new person's name. */
export function ownerBody(form: OwnerForm): Result<InstallmentOwner> {
  if (form.owner === 'me') return { body: {}, error: null }
  if (typeof form.owner === 'number') return { body: { contact_id: form.owner }, error: null }
  const name = form.newName.trim()
  if (name.length === 0 || name.length > NAME_MAX) {
    return fail(t('installments.form.invalid.newPerson', { max: NAME_MAX }))
  }
  return { body: { new_person: name }, error: null }
}

function checkName(text: string): Result<string> {
  const name = text.trim()
  if (name.length === 0 || name.length > NAME_MAX) {
    return fail(t('installments.form.invalid.name', { max: NAME_MAX }))
  }
  return { body: name, error: null }
}

function checkCount(text: string): Result<number> {
  const count = wholeNumber(text)
  if (count === null || count < COUNT_MIN || count > COUNT_MAX) {
    return fail(t('installments.form.invalid.count', { min: COUNT_MIN, max: COUNT_MAX }))
  }
  return { body: count, error: null }
}

/** The POST body, or the first thing to fix in the form. */
export function createBody(draft: InstallmentDraft, form: PlanForm): Result<InstallmentBody> {
  const name = checkName(form.name)
  if (name.error !== null) return fail(name.error)
  const count = checkCount(form.count)
  if (count.error !== null) return fail(count.error)
  const checked = draft.earlier
    .map((charge) => charge.fingerprint)
    .filter((fingerprint) => form.checked.includes(fingerprint))
  const base = { fingerprint: draft.fingerprint, name: name.body, count: count.body, earlier: checked }
  const owner = ownerBody(form)
  if (owner.error !== null) return fail(owner.error)
  if (numberAsk(draft, numbering(draft, checked).number, form.count) === null) {
    return { body: { ...base, ...owner.body }, error: null }
  }
  const number = wholeNumber(form.number)
  if (number === null || number < 1 || number > count.body) {
    return fail(t('installments.form.invalid.number', { count: count.body }))
  }
  return { body: { ...base, number, ...owner.body }, error: null }
}

/** "Edit plan" starts from the plan as it is. */
export function initialEdit(plan: InstallmentPlan): EditForm {
  return { name: plan.name, count: String(plan.count), owner: plan.contact_id ?? 'me', newName: '' }
}

/** Has the owner moved to someone else (the recorded installments move with it)? */
export function ownerChanged(plan: Pick<InstallmentPlan, 'contact_id'>, owner: OwnerChoice): boolean {
  return owner !== (plan.contact_id ?? 'me')
}

/** The PATCH body with only what changed ({}: nothing to save), or the first thing to fix. */
export function editBody(plan: InstallmentPlan, form: EditForm): Result<InstallmentEdit> {
  const name = checkName(form.name)
  if (name.error !== null) return fail(name.error)
  const count = checkCount(form.count)
  if (count.error !== null) return fail(count.error)
  const owner = ownerBody(form)
  if (owner.error !== null) return fail(owner.error)
  return {
    body: {
      ...(name.body !== plan.name ? { name: name.body } : {}),
      ...(count.body !== plan.count ? { count: count.body } : {}),
      ...(ownerChanged(plan, form.owner) ? { owner: owner.body } : {}),
    },
    error: null,
  }
}

/** For a charge already shared: the group's only other member, when they are a known person. */
export function preferredPerson(
  people: readonly InstallmentPerson[],
  members: readonly { id: number; is_me: boolean }[] | undefined,
): number | null {
  const others = (members ?? []).filter((member) => !member.is_me)
  if (others.length !== 1) return null
  return people.some((person) => person.id === others[0].id) ? others[0].id : null
}

/** `id` when it is one of the people the owner field offers, else null. */
export function knownPerson(people: readonly InstallmentPerson[], id: number | null): number | null {
  return id !== null && people.some((person) => person.id === id) ? id : null
}

/** The people the owner field offers: the user's groups' people, plus the plan's own if it is not there
 * (its group was archived). */
export function ownerChoices(
  people: readonly InstallmentPerson[],
  current: InstallmentPerson | null,
): InstallmentPerson[] {
  if (current === null || people.some((person) => person.id === current.id)) return [...people]
  return [...people, current]
}

/** The `<select>` value of a choice, and back. */
export function ownerValue(owner: OwnerChoice): string {
  return typeof owner === 'number' ? `person-${owner}` : owner
}

export function parseOwnerValue(value: string): OwnerChoice {
  if (value === 'me' || value === 'new') return value
  return Number(value.replace('person-', ''))
}
