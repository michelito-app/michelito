// "Change who paid" on a payment the user received: the people it can be given to instead.
import type { Member, Payment } from './sharedApi'

/** The group's other people (not the user, not the current payer) a received payment can be
 * given to; none for one the user made or an unattributed one (that one has «Asignar»). */
export function payerChoices<M extends Pick<Member, 'id' | 'is_me'>>(
  payment: Pick<Payment, 'to_me' | 'from_contact'>,
  members: readonly M[],
): M[] {
  if (!payment.to_me || payment.from_contact === null) return []
  return members.filter((m) => !m.is_me && m.id !== payment.from_contact)
}
