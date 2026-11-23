import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { InstallmentDraft, InstallmentPlan, Tx } from './api'
import {
  canBeInstallment,
  COUNT_MAX,
  eachLine,
  foundLine,
  initialForm,
  installmentLabel,
  installmentTag,
  linkedLine,
  NAME_MAX,
  ownerLine,
  type PlanForm,
  planBody,
  planOf,
  planSummary,
  progress,
} from './installments'

const TAG = { plan_id: 7, name: 'Phone (Store)', number: 3, count: 6 }

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

function draft(over: Partial<InstallmentDraft> = {}): InstallmentDraft {
  return {
    fingerprint: 'fp-3',
    name: 'STORE COM',
    account_label: 'VISA ···4242',
    amount_cents: 15_000,
    currency: 'USD',
    month: '2026-02',
    number: 3,
    paid_before: 2,
    ...over,
  }
}

function form(over: Partial<PlanForm> = {}): PlanForm {
  return { ...initialForm(draft()), ...over }
}

describe('row and detail lines', () => {
  it('tags a row of a plan and nothing else', () => {
    expect(installmentTag({ installment: TAG })).toBe('cuota 3/6 · Phone (Store)')
    expect(installmentTag({ installment: null })).toBeNull()
    expect(installmentTag({})).toBeNull()
  })

  it('says which installment it is in the detail', () => {
    expect(linkedLine(TAG)).toBe('Cuota 3 de 6 · Phone (Store)') // spanish-ui
  })
})

describe('planSummary', () => {
  it('counts what is paid, what is left and when it ends', () => {
    expect(planSummary(plan())).toBe('3 de 6 · faltan US$ 450.00 · termina en mayo 2026') // spanish-ui
  })

  it('a plan fully paid says it ended', () => {
    const done = plan({ paid: 6, remaining_cents: 0 })
    expect(planSummary(done)).toBe(t('installments.plan.done', { count: 6, month: 'mayo 2026' })) // spanish-ui
  })

  it('names the installment amount and the card', () => {
    expect(eachLine(plan())).toBe(
      t('installments.plan.each', { amount: 'US$ 150.00', account: 'VISA ···4242' }),
    )
  })

  it("names who pays a member's plan, and nobody for the user's own", () => {
    expect(ownerLine(plan())).toBeNull()
    const member = plan({ group_id: 2, contact_id: 5, group_name: 'Home', contact_name: 'Ana' })
    expect(ownerLine(member)).toBe(t('installments.plan.paidBy', { contact: 'Ana', group: 'Home' }))
  })

  it('labels each installment with its month and state', () => {
    expect(installmentLabel(2, '2026-01', 'paid')).toBe('Cuota 2, enero 2026: pagada') // spanish-ui
  })

  it('keeps the progress between 0 and 1', () => {
    expect(progress({ paid: 3, count: 6 })).toBe(0.5)
    expect(progress({ paid: 9, count: 6 })).toBe(1)
    expect(progress({ paid: 0, count: 0 })).toBe(0)
  })

  it('finds the plan of a row among the loaded ones', () => {
    expect(planOf([plan()], 7)?.name).toBe('Phone (Store)')
    expect(planOf([plan()], 8)).toBeNull()
    expect(planOf(undefined, 7)).toBeNull()
    expect(planOf([plan()], undefined)).toBeNull()
  })
})

describe('canBeInstallment', () => {
  const cards = new Set(['visa'])
  const charge = {
    kind: 'expense',
    amount_cents: 15_000,
    account: 'visa',
    installment: null,
    provisional: false,
    link: '',
  } as Tx

  it('offers it on a card charge not in a plan', () => {
    expect(canBeInstallment(charge, cards)).toBe(true)
  })

  it('offers it on a charge already shared, whose own part is zero', () => {
    const shared = { ...charge, amount_cents: 0, gross_cents: 15_000, link: 'shared' } as Tx
    expect(canBeInstallment(shared, cards)).toBe(true)
  })

  it('not on a refund, another account, a non-expense, a provisional, a leg or a planned row', () => {
    expect(canBeInstallment({ ...charge, amount_cents: -15_000 }, cards)).toBe(false)
    expect(canBeInstallment({ ...charge, account: 'checking' }, cards)).toBe(false)
    expect(canBeInstallment({ ...charge, kind: 'transfer' }, cards)).toBe(false)
    expect(canBeInstallment({ ...charge, installment: TAG }, cards)).toBe(false)
    expect(canBeInstallment({ ...charge, provisional: true }, cards)).toBe(false)
    expect(canBeInstallment({ ...charge, link: 'exchange' }, cards)).toBe(false)
    expect(canBeInstallment({ ...charge, link: 'investment' }, cards)).toBe(false)
    expect(canBeInstallment({ ...charge, link: 'shared' }, cards)).toBe(true)
  })
})

describe('the form', () => {
  it('starts from the draft: its name and number, 6 installments, mine', () => {
    expect(initialForm(draft())).toEqual({
      name: 'STORE COM',
      count: '6',
      number: '3',
      owner: 'me',
      groupId: null,
      contactId: null,
    })
  })

  it('never starts with fewer installments than the number found', () => {
    expect(initialForm(draft({ number: 9 })).count).toBe('9')
  })

  it('says how many earlier installments were found', () => {
    expect(foundLine(draft())).toBe('Encontramos 2 cuotas anteriores.') // spanish-ui
    expect(foundLine(draft({ paid_before: 1 }))).toBe('Encontramos 1 cuota anterior.') // spanish-ui
    expect(foundLine(draft({ paid_before: 0 }))).toBeNull()
  })

  it("builds the user's own plan", () => {
    expect(planBody('fp-3', form({ name: '  Phone (Store) ' }))).toEqual({
      body: { fingerprint: 'fp-3', name: 'Phone (Store)', count: 6, number: 3 },
      error: null,
    })
  })

  it("builds a member's plan with the group and the person", () => {
    const result = planBody('fp-3', form({ owner: 'member', groupId: 2, contactId: 5 }))
    expect(result.body).toEqual({
      fingerprint: 'fp-3',
      name: 'STORE COM',
      count: 6,
      number: 3,
      group_id: 2,
      contact_id: 5,
    })
  })

  it('asks for what is missing or out of range', () => {
    expect(planBody('f', form({ name: ' ' })).error).toBe(
      t('installments.form.invalid.name', { max: NAME_MAX }),
    )
    expect(planBody('f', form({ name: 'x'.repeat(NAME_MAX + 1) })).body).toBeNull()
    expect(planBody('f', form({ count: '1' })).error).toBe(
      t('installments.form.invalid.count', { min: 2, max: COUNT_MAX }),
    )
    expect(planBody('f', form({ count: '2.5' })).body).toBeNull()
    expect(planBody('f', form({ count: String(COUNT_MAX + 1) })).body).toBeNull()
    expect(planBody('f', form({ number: '7' })).error).toBe(
      t('installments.form.invalid.number', { count: 6 }),
    )
    expect(planBody('f', form({ number: '0' })).body).toBeNull()
    expect(planBody('f', form({ owner: 'member', groupId: 2 })).error).toBe(
      t('installments.form.invalid.member'),
    )
  })
})
