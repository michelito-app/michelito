// @vitest-environment jsdom
import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { t } from '@/i18n'
import type { InstallmentCharge, InstallmentDraft } from '@/lib/api'
import { installmentKeys } from '@/lib/installmentQueries'
import { sharedKeys } from '@/lib/sharedQueries'
import { InstallmentSheet } from './InstallmentSheet'
import { NewPlanSheet } from './NewPlanSheet'
import {
  button,
  click,
  draftOf,
  field,
  fill,
  flush,
  planOf,
  render,
  type Rendered,
  sentBody,
  stubWrites,
} from './testing'

const PEOPLE = [
  { id: 4, name: 'Ana Test' },
  { id: 9, name: 'Luis Test' },
]

let shown: Rendered | null = null

afterEach(() => {
  shown?.unmount()
  shown = null
  vi.unstubAllGlobals()
})

function sheet(draft: InstallmentDraft = draftOf(), sharedGroupId: number | null = null) {
  const data: [readonly unknown[], unknown][] = [
    [installmentKeys.draft(draft.fingerprint), draft],
    [installmentKeys.people, PEOPLE],
  ]
  if (sharedGroupId !== null) {
    data.push([
      sharedKeys.group(sharedGroupId),
      { id: sharedGroupId, members: [{ id: 1, is_me: true }, { id: 9, is_me: false }] },
    ])
  }
  const onCreated = vi.fn()
  shown = render(
    createElement(InstallmentSheet, {
      fingerprint: draft.fingerprint,
      sharedGroupId,
      onClose: () => undefined,
      onCreated,
    }),
    data,
  )
  return { container: shown.container, onCreated }
}

function numberLabels(container: HTMLElement): string[] {
  return [...container.querySelectorAll('[data-testid="installment-earlier-number"]')].map(
    (item) => item.textContent ?? '',
  )
}

function position(container: HTMLElement): string | null {
  return container.querySelector('[data-testid="installment-position"]')?.textContent ?? null
}

describe('InstallmentSheet', () => {
  it('says which installment it is and lists the earlier charges, without a number field', () => {
    const { container } = sheet()
    expect(position(container)).toBe(t('installments.form.position', { number: 3, count: '6' }))
    expect(field(container, t('installments.form.number'))).toBeNull()
    expect(container.textContent).toContain(t('installments.form.found', { count: 2 }))
    expect(numberLabels(container)).toEqual([
      t('installments.form.earlierNumber', { number: 1 }),
      t('installments.form.earlierNumber', { number: 2 }),
    ])
    expect((field(container, t('installments.form.owner')) as HTMLSelectElement).value).toBe('me')
  })

  it('renumbers the charges when one is unchecked', () => {
    const { container } = sheet()
    click(container.querySelector('[data-testid="installment-earlier"] input[type="checkbox"]'))
    expect(numberLabels(container)).toEqual([
      t('installments.form.earlierSkipped'),
      t('installments.form.earlierNumber', { number: 1 }),
    ])
    expect(position(container)).toBe(t('installments.form.position', { number: 2, count: '6' }))
  })

  it('asks for the number when the card data starts at the charge', () => {
    const { container } = sheet(draftOf({ earlier: [], number: 1, paid_before: 0, number_known: false }))
    expect(position(container)).toBeNull()
    expect(container.textContent).toContain(t('installments.form.numberUnknown'))
    expect(field(container, t('installments.form.number'))).not.toBeNull()
  })

  it('asks for the number when the deduced one does not fit', () => {
    const { container } = sheet()
    fill(field(container, t('installments.form.count')), '2')
    expect(container.textContent).toContain(
      t('installments.form.numberOver', { count: '2', number: 3 }),
    )
    expect(field(container, t('installments.form.number'))).not.toBeNull()
  })

  it('reveals the name field for a new person and sends it', async () => {
    const fetch = stubWrites(planOf())
    const { container, onCreated } = sheet()
    expect(field(container, t('installments.form.newName'))).toBeNull()
    fill(field(container, t('installments.form.owner')), 'new')
    fill(field(container, t('installments.form.newName')), 'Test Person')
    click(button(container, t('installments.form.submit')))
    await flush()
    expect(sentBody(fetch)).toEqual({
      fingerprint: 'fp-feb',
      name: 'TEST STORE',
      count: 6,
      earlier: ['fp-dec', 'fp-jan'],
      new_person: 'Test Person',
    })
    expect(onCreated).toHaveBeenCalled()
  })

  it('says what is missing instead of sending', () => {
    const fetch = stubWrites(planOf())
    const { container } = sheet()
    fill(field(container, t('installments.form.owner')), 'new')
    click(button(container, t('installments.form.submit')))
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      t('installments.form.invalid.newPerson', { max: 80 }),
    )
    expect(fetch).not.toHaveBeenCalledWith('/api/installments', expect.anything())
  })

  it('starts with the person the charge is already shared with', () => {
    const { container } = sheet(draftOf(), 3)
    expect((field(container, t('installments.form.owner')) as HTMLSelectElement).value).toBe(
      'person-9',
    )
  })
})

describe('NewPlanSheet', () => {
  const charge: InstallmentCharge = {
    fingerprint: 'fp-feb',
    day: '2026-02-07',
    description: 'TEST STORE 123',
    merchant: 'Test Store',
    account_label: 'VISA ···0000',
    amount_cents: 15_000,
    currency: 'USD',
    number: null,
  }

  function picker(charges: InstallmentCharge[]) {
    shown = render(createElement(NewPlanSheet, { onClose: () => undefined, onCreated: () => undefined }), [
      [installmentKeys.charges(null), charges],
      [installmentKeys.draft('fp-feb'), draftOf()],
      [installmentKeys.people, PEOPLE],
    ])
    return shown.container
  }

  it('goes from the picked charge to the short form', () => {
    const container = picker([charge])
    expect(container.textContent).toContain(t('installments.picker.title'))
    click(container.querySelector('[data-testid="installment-charges"] button'))
    expect(container.querySelector('[data-testid="installment-form"]')).not.toBeNull()
    expect(position(container)).toBe(t('installments.form.position', { number: 3, count: '6' }))
  })

  it('says so when there is no charge to start from', () => {
    expect(picker([]).textContent).toContain(t('installments.picker.empty'))
  })
})
