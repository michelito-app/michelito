import { describe, expect, it } from 'vitest'
import { coverStart } from './coverDraft'
import { sharedKeys } from './sharedQueries'

const ANA = 2
const BETO = 3
const LUIS = 4

const part = (contact_id: number, cents: number) => ({ contact_id, name: '', is_me: false, cents })

describe('"Also paid for…" on an existing payment', () => {
  it('starts from what it settles (an accepted difference included), as stored', () => {
    const payment = {
      from_contact: ANA,
      settles_cents: 110_000,
      allocations: [part(ANA, 10_000), part(BETO, 100_000)],
    }
    expect(coverStart(payment, [])).toEqual({
      covers: [BETO],
      shares: { [ANA]: '100.00', [BETO]: '1000.00' },
      base: 110_000,
    })
  })

  it('keeps who it covers and adds the suggested person, asking for a proposal', () => {
    const payment = {
      from_contact: ANA,
      settles_cents: 100_000,
      allocations: [part(ANA, 50_000), part(LUIS, 50_000)],
    }
    expect(coverStart(payment, [BETO])).toEqual({ covers: [LUIS, BETO], shares: undefined, base: 100_000 })
    // A suggestion it already covers changes nothing.
    expect(coverStart(payment, [LUIS]).shares).toEqual({ [ANA]: '500.00', [LUIS]: '500.00' })
  })

  it('with nobody else yet, the suggestion is proposed', () => {
    const payment = { from_contact: ANA, settles_cents: 100, allocations: [part(ANA, 100)] }
    expect(coverStart(payment, [BETO])).toEqual({ covers: [BETO], shares: undefined, base: 100 })
  })
})

describe('the proposal query key', () => {
  it('tells groups apart', () => {
    const query = { from_contact: ANA, amount_cents: 1, currency: 'DOP', day: '2026-02-10', covers: [BETO] }
    expect(sharedKeys.proposal({ ...query, group_id: 1 })).not.toEqual(
      sharedKeys.proposal({ ...query, group_id: 2 }),
    )
  })
})
