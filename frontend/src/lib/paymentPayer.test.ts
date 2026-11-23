import { describe, expect, test } from 'vitest'
import { payerChoices } from './paymentPayer'

const members = [
  { id: 1, name: 'Tú', is_me: true },
  { id: 2, name: 'Javier', is_me: false },
  { id: 3, name: 'Alex', is_me: false },
]

describe('payerChoices', () => {
  test('offers the other people of the group for a payment the user received', () => {
    // Arrange
    const payment = { to_me: true, from_contact: 2 }

    // Act
    const choices = payerChoices(payment, members)

    // Assert
    expect(choices.map((m) => m.id)).toEqual([3])
  })

  test('offers nobody for a payment the user made', () => {
    expect(payerChoices({ to_me: false, from_contact: 1 }, members)).toEqual([])
  })

  test('offers nobody for an unattributed payment (it has its own «Asignar»)', () => {
    expect(payerChoices({ to_me: true, from_contact: null }, members)).toEqual([])
  })

  test('offers nobody when the payer is the only other person', () => {
    expect(payerChoices({ to_me: true, from_contact: 2 }, members.slice(0, 2))).toEqual([])
  })
})
