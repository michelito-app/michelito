// @vitest-environment jsdom
import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { t } from '@/i18n'
import type { InstallmentPlan } from '@/lib/api'
import { installmentKeys } from '@/lib/installmentQueries'
import { EditPlanSheet } from './EditPlanSheet'
import { button, click, field, fill, flush, planOf, render, type Rendered, sentBody, stubWrites } from './testing'

const PEOPLE = [{ id: 4, name: 'Ana Test' }]
const LINKED = planOf({
  installments: [
    { number: 1, month: '2025-12', state: 'paid', fingerprint: 'fp-dec' },
    { number: 2, month: '2026-01', state: 'pending', fingerprint: null },
  ],
})

let shown: Rendered | null = null

afterEach(() => {
  shown?.unmount()
  shown = null
  vi.unstubAllGlobals()
})

function sheet(plan: InstallmentPlan = LINKED) {
  const onClose = vi.fn()
  shown = render(createElement(EditPlanSheet, { plan, onClose }), [
    [installmentKeys.people, PEOPLE],
    [installmentKeys.charges(plan.id), []],
  ])
  return { container: shown.container, onClose }
}

describe('EditPlanSheet', () => {
  it('sends only what changed and closes', async () => {
    const fetch = stubWrites(LINKED)
    const { container, onClose } = sheet()
    fill(field(container, t('installments.form.name')), 'Renamed plan')
    fill(field(container, t('installments.form.count')), '12')
    click(button(container, t('installments.edit.save')))
    await flush()
    expect(fetch.mock.calls[0][0]).toBe('/api/installments/7')
    expect(sentBody(fetch)).toEqual({ name: 'Renamed plan', count: 12 })
    expect(onClose).toHaveBeenCalled()
  })

  it('warns that recorded installments move when the owner changes', async () => {
    const fetch = stubWrites(LINKED)
    const { container } = sheet()
    const moves = () => container.querySelector('[data-testid="installment-owner-moves"]')
    expect(moves()).toBeNull()
    fill(field(container, t('installments.form.owner')), 'person-4')
    expect(moves()?.textContent).toBe(t('installments.edit.ownerMoves'))
    click(button(container, t('installments.edit.save')))
    await flush()
    expect(sentBody(fetch)).toEqual({ owner: { contact_id: 4 } })
  })

  it('closes without a request when nothing changed', () => {
    const fetch = stubWrites(LINKED)
    const { container, onClose } = sheet()
    click(button(container, t('installments.edit.save')))
    expect(fetch).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('lists the linked charges and unlinks one', async () => {
    const fetch = stubWrites(LINKED)
    const { container } = sheet()
    const remove = container.querySelector(
      `[aria-label="${t('installments.edit.removeLabel', { number: 1 })}"]`,
    )
    expect(container.querySelectorAll('[data-testid="installment-plan-charges"] li')).toHaveLength(1)
    click(remove)
    await flush()
    expect(fetch.mock.calls[0][0]).toBe('/api/installments/7/transactions/fp-dec')
    expect(fetch.mock.calls[0][1]?.method).toBe('DELETE')
  })

  it('offers the plan charges to add, and says when there are none', () => {
    const { container } = sheet()
    click(button(container, t('installments.edit.add')))
    expect(container.textContent).toContain(t('installments.edit.addEmpty'))
  })
})
