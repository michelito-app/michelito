import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { InstallmentDraft, InstallmentPlan } from './api'
import {
  createBody,
  editBody,
  initialEdit,
  initialForm,
  numberAsk,
  numbering,
  numberBetween,
  ownerBody,
  ownerChoices,
  ownerValue,
  parseOwnerValue,
  preferredPerson,
  knownPerson,
  type PlanForm,
} from './installmentForm'
import { COUNT_MAX, NAME_MAX } from './installments'

function draft(over: Partial<InstallmentDraft> = {}): InstallmentDraft {
  return {
    fingerprint: 'fp-feb',
    name: 'STORE COM',
    account_label: 'VISA ···4242',
    amount_cents: 15_000,
    currency: 'USD',
    month: '2026-02',
    number: 3,
    paid_before: 2,
    earlier: [
      { fingerprint: 'fp-dec', day: '2025-12-14', description: 'STORE', amount_cents: 15_000, number: 1 },
      { fingerprint: 'fp-jan', day: '2026-01-14', description: 'STORE', amount_cents: 15_000, number: 2 },
    ],
    number_known: true,
    suggested_contact_id: null,
    ...over,
  }
}

function plan(over: Partial<InstallmentPlan> = {}): InstallmentPlan {
  return {
    id: 7,
    name: 'Phone (Store)',
    account_label: 'VISA ···4242',
    amount_cents: 15_000,
    currency: 'USD',
    count: 6,
    paid: 3,
    remaining_cents: 45_000,
    first_month: '2025-12',
    last_month: '2026-05',
    group_id: null,
    contact_id: null,
    group_name: null,
    contact_name: null,
    receipt_id: null,
    missing: [],
    installments: [],
    ...over,
  }
}

function form(over: Partial<PlanForm> = {}): PlanForm {
  return { ...initialForm(draft()), ...over }
}

describe('initialForm', () => {
  it('starts with every earlier charge checked, six installments and the user as owner', () => {
    expect(initialForm(draft())).toEqual({
      name: 'STORE COM',
      count: '6',
      number: '',
      checked: ['fp-dec', 'fp-jan'],
      owner: 'me',
      newName: '',
    })
  })

  it('makes room for a late installment and prefers the person the charge is shared with', () => {
    const late = initialForm(draft({ number: 9 }), 4)
    expect(late.count).toBe('9')
    expect(late.owner).toBe(4)
  })

  it('cuts a long merchant name to the limit', () => {
    expect(initialForm(draft({ name: 'x'.repeat(NAME_MAX + 5) })).name).toHaveLength(NAME_MAX)
  })
})

describe('numbering', () => {
  it('counts months from the earliest checked charge', () => {
    expect(numberBetween('2025-12', '2026-02')).toBe(3)
    expect(numberBetween('2026-02', '2026-02')).toBe(1)
  })

  it('numbers every checked charge and the chosen one', () => {
    const all = numbering(draft(), ['fp-dec', 'fp-jan'])
    expect(all.number).toBe(3)
    expect(all.earlier.get('fp-dec')).toBe(1)
    expect(all.earlier.get('fp-jan')).toBe(2)
  })

  it('renumbers when the oldest charge is unchecked', () => {
    const some = numbering(draft(), ['fp-jan'])
    expect(some.number).toBe(2)
    expect(some.earlier.get('fp-jan')).toBe(1)
    expect(some.earlier.has('fp-dec')).toBe(false)
  })

  it('is installment 1 when nothing earlier is checked', () => {
    expect(numbering(draft(), []).number).toBe(1)
  })
})

describe('numberAsk', () => {
  it('asks only when the number is unknown or does not fit', () => {
    expect(numberAsk(draft(), 3, '6')).toBeNull()
    expect(numberAsk(draft({ number_known: false, earlier: [] }), 1, '6')).toBe('unknown')
    expect(numberAsk(draft(), 3, '2')).toBe('overCount')
    expect(numberAsk(draft(), 3, 'abc')).toBeNull()
  })
})

describe('ownerBody', () => {
  it('is empty for the user, the id for a known person and the name for a new one', () => {
    expect(ownerBody({ owner: 'me', newName: 'ignored' })).toEqual({ body: {}, error: null })
    expect(ownerBody({ owner: 4, newName: '' })).toEqual({ body: { contact_id: 4 }, error: null })
    expect(ownerBody({ owner: 'new', newName: '  Test Person  ' })).toEqual({
      body: { new_person: 'Test Person' },
      error: null,
    })
  })

  it('asks for the new person name', () => {
    expect(ownerBody({ owner: 'new', newName: '  ' })).toEqual({
      body: null,
      error: t('installments.form.invalid.newPerson', { max: NAME_MAX }),
    })
  })
})

describe('createBody', () => {
  it('sends the checked earlier charges and no number when it was deduced', () => {
    expect(createBody(draft(), form({ checked: ['fp-jan'] }))).toEqual({
      body: { fingerprint: 'fp-feb', name: 'STORE COM', count: 6, earlier: ['fp-jan'] },
      error: null,
    })
  })

  it('sends a new person and a known one', () => {
    expect(createBody(draft(), form({ owner: 'new', newName: 'Test Person' })).body).toMatchObject({
      new_person: 'Test Person',
    })
    expect(createBody(draft(), form({ owner: 9 })).body).toMatchObject({ contact_id: 9 })
  })

  it('sends the typed number when the card data starts at the charge', () => {
    const unknown = draft({ number_known: false, earlier: [], number: 1, paid_before: 0 })
    expect(createBody(unknown, form({ checked: [], number: '4' })).body).toEqual({
      fingerprint: 'fp-feb',
      name: 'STORE COM',
      count: 6,
      earlier: [],
      number: 4,
    })
    expect(createBody(unknown, form({ checked: [], number: '' })).error).toBe(
      t('installments.form.invalid.number', { count: 6 }),
    )
  })

  it('needs a typed number when the deduced one does not fit', () => {
    expect(createBody(draft(), form({ count: '2' })).error).toBe(
      t('installments.form.invalid.number', { count: 2 }),
    )
    expect(createBody(draft(), form({ count: '2', number: '2' })).body).toMatchObject({
      count: 2,
      number: 2,
    })
  })

  it('checks the name and the number of installments', () => {
    expect(createBody(draft(), form({ name: ' ' })).error).toBe(
      t('installments.form.invalid.name', { max: NAME_MAX }),
    )
    expect(createBody(draft(), form({ count: '1' })).error).toBe(
      t('installments.form.invalid.count', { min: 2, max: COUNT_MAX }),
    )
    expect(createBody(draft(), form({ count: '6.5' })).error).toBe(
      t('installments.form.invalid.count', { min: 2, max: COUNT_MAX }),
    )
  })
})

describe('editBody', () => {
  it('starts from the plan and sends nothing when nothing changed', () => {
    const start = initialEdit(plan({ contact_id: 4 }))
    expect(start).toEqual({ name: 'Phone (Store)', count: '6', owner: 4, newName: '' })
    expect(editBody(plan({ contact_id: 4 }), start)).toEqual({ body: {}, error: null })
  })

  it('sends only what changed', () => {
    const mine = plan()
    expect(editBody(mine, { ...initialEdit(mine), name: ' Phone ', count: '12' })).toEqual({
      body: { name: 'Phone', count: 12 },
      error: null,
    })
    expect(editBody(mine, { ...initialEdit(mine), owner: 'new', newName: 'Test Person' })).toEqual({
      body: { owner: { new_person: 'Test Person' } },
      error: null,
    })
    expect(editBody(plan({ contact_id: 4 }), { ...initialEdit(plan()), owner: 'me' })).toEqual({
      body: { owner: {} },
      error: null,
    })
  })

  it('checks what was typed', () => {
    expect(editBody(plan(), { ...initialEdit(plan()), count: '0' }).error).toBe(
      t('installments.form.invalid.count', { min: 2, max: COUNT_MAX }),
    )
    expect(editBody(plan(), { ...initialEdit(plan()), owner: 'new' }).error).toBe(
      t('installments.form.invalid.newPerson', { max: NAME_MAX }),
    )
  })
})

describe('owner choices', () => {
  const people = [
    { id: 4, name: 'Ana Test' },
    { id: 9, name: 'Luis Test' },
  ]

  it('prefers the only other member of the shared group when they are a known person', () => {
    expect(preferredPerson(people, [{ id: 1, is_me: true }, { id: 9, is_me: false }])).toBe(9)
    expect(preferredPerson(people, [{ id: 1, is_me: true }, { id: 5, is_me: false }])).toBeNull()
    expect(
      preferredPerson(people, [
        { id: 4, is_me: false },
        { id: 9, is_me: false },
      ]),
    ).toBeNull()
    expect(preferredPerson(people, undefined)).toBeNull()
  })

  it('suggests a person only when the owner field offers them', () => {
    expect(knownPerson(people, people[0].id)).toBe(people[0].id)
    expect(knownPerson(people, 12345)).toBeNull()
    expect(knownPerson(people, null)).toBeNull()
  })

  it('adds the plan person when they are not in the list', () => {
    expect(ownerChoices(people, { id: 12, name: 'Old Test' })).toEqual([
      ...people,
      { id: 12, name: 'Old Test' },
    ])
    expect(ownerChoices(people, { id: 4, name: 'Ana Test' })).toEqual(people)
    expect(ownerChoices(people, null)).toEqual(people)
  })

  it('round-trips the select values', () => {
    for (const owner of ['me', 'new', 4] as const) {
      expect(parseOwnerValue(ownerValue(owner))).toBe(owner)
    }
  })
})
