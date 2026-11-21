// "Also paid for…" state, shared by the new-payment sheet and a payment's detail.
import { useState } from 'react'
import { allocationCents, centsField, proposalFields, shortfall } from './ledger'
import type { Member, Payment, Proposal, ShareBody } from './sharedApi'
import { useProposal } from './sharedQueries'

export interface CoverStart {
  covers: number[]
  /** The stored amounts as text; undefined: ask the server for a proposal. */
  shares: Record<number, string> | undefined
  /** What the amounts add up to: what the payment settles (`settles_cents`). */
  base: number
}

/** Where an existing payment's "Also paid for…" starts: who it already covers plus anyone the
 * suggestion adds (in that order), over what it settles (an accepted difference included, as
 * the server validates). With the stored amounts when nobody is added; when the suggestion adds
 * someone (or it covers nobody else yet), the server's proposal. */
export function coverStart(
  payment: Pick<Payment, 'from_contact' | 'settles_cents' | 'allocations'>,
  preselect: readonly number[],
): CoverStart {
  const existing = payment.allocations
    .filter((a) => a.contact_id !== payment.from_contact)
    .map((a) => a.contact_id)
  const added = preselect.filter((id) => !existing.includes(id) && id !== payment.from_contact)
  const covers = [...existing, ...added]
  const stored =
    existing.length > 0 && added.length === 0
      ? Object.fromEntries(payment.allocations.map((a) => [a.contact_id, centsField(a.cents)]))
      : undefined
  return { covers, shares: stored, base: payment.settles_cents }
}

export interface CoverDraftInput {
  groupId: number
  payer: Member | null
  amountCents: number | null
  currency: string
  day: string
  /** An existing payment: proposals are at its own position. */
  paymentId?: number | null
  /** Who it already covers (besides the payer) and the stored amounts, as typed text. */
  initialCovers?: readonly number[]
  initialShares?: Readonly<Record<number, string>>
}

export interface CoverDraft {
  covers: readonly number[]
  shares: Readonly<Record<number, string>>
  proposal: Proposal | null
  /** Cents still to allocate (0: adds up), null while a field is not an amount. */
  missing: number | null
  ready: boolean
  /** What to save: [] when it covers nobody else (all of it is the payer's). */
  allocations: ShareBody[] | null
  toggle: (id: number, on: boolean) => void
  type: (id: number, value: string) => void
  reset: () => void
}

/** "Also paid for…" state: the people checked (in order) and each one's amount. Until a field is
 * typed in, the amounts are the server's proposal (`ledger.propose_allocations`: the payer's own
 * balance first, then the others in the order checked, converted at the payment month's rate);
 * checking or unchecking someone asks again. */
export function useCoverDraft(input: CoverDraftInput): CoverDraft {
  const initialCovers = input.initialCovers ?? []
  const [covers, setCovers] = useState<readonly number[]>(initialCovers)
  // Typed (or stored) amounts; `null` while the proposal rules.
  const [typed, setTyped] = useState<Readonly<Record<number, string>> | null>(
    input.initialShares ?? null,
  )
  const payer = input.payer
  const query =
    payer && covers.length > 0 && input.amountCents
      ? {
          group_id: input.groupId,
          from_contact: payer.id,
          amount_cents: input.amountCents,
          currency: input.currency,
          day: input.day,
          covers,
          payment_id: input.paymentId ?? null,
        }
      : null
  const proposal = useProposal(query)
  const data = query ? (proposal.data ?? null) : null
  const shares = typed ?? (data ? proposalFields(data) : {})
  const people = payer ? [payer.id, ...covers] : []
  const allocated = covers.length > 0 ? allocationCents(people, shares) : null
  const missing =
    covers.length === 0
      ? 0
      : allocated && input.amountCents
        ? shortfall(input.amountCents, Object.values(allocated))
        : null
  const allocations =
    covers.length === 0
      ? []
      : allocated
        ? Object.entries(allocated)
            .map(([id, cents]) => ({ contact_id: Number(id), cents }))
            .filter((a) => a.cents > 0)
        : null
  return {
    covers,
    shares,
    proposal: data,
    missing,
    ready: missing === 0 && allocations !== null && (covers.length === 0 || typed !== null || data !== null),
    allocations,
    toggle: (id, on) => {
      setCovers(on ? [...covers.filter((c) => c !== id), id] : covers.filter((c) => c !== id))
      setTyped(null)
    },
    type: (id, value) => setTyped({ ...shares, [id]: value }),
    reset: () => {
      setCovers([])
      setTyped(null)
    },
  }
}
