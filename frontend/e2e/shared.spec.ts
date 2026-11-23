// Shared (the ledger), on a wide screen and on the phone (projects chromium, mobile at 390 px and
// mobile-360). Made-up data from tests/e2e_server.py: a gift «for someone else» with Luis
// (RD$ 4,000 owed), «Ropa de Marta» settled by a payment by hand, and a written-off group with
// Rosa. Each test that writes undoes everything at the end through the log (the same spec runs in
// three projects on one database).
import { expect, test, type Page } from '@playwright/test'
import {
  addEntry,
  addPayment,
  contacts,
  createGroup,
  fingerprintOf,
  logMark,
  undoSince,
} from './ledger'
import { escapeRegExp, literal, t } from './text'
import type { Group } from '../src/lib/sharedApi'

const FEBRUARY = '2026-02'
const NEW_GROUP = 'Viaje de prueba' // spanish-data
const DINNER_GROUP = 'Cena de prueba' // spanish-data

let mark = 0
test.beforeEach(async ({ request }) => {
  mark = await logMark(request)
})
test.afterEach(async ({ request }) => {
  await undoSince(request, mark)
})

function dialog(page: Page, title: string) {
  return page.getByRole('dialog', { name: title })
}

async function noSidewaysScroll(page: Page, what: string) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow, what).toBeLessThanOrEqual(0)
}

/** A group with Carola (a name seen in the bank, with its alias) and a new person, Pedro. */
async function tripGroup(page: Page) {
  return createGroup(page.request, DINNER_GROUP, [
    { name: 'Carola Ficticia', alias: 'CAROLA FICTICIA' }, // spanish-data
    { name: 'Pedro Ficticio' }, // spanish-data
  ])
}

/** A group where «Persona Ficticia» owes RD$ 1,500: half the RD$ 3,000 dinner the user paid. */
async function owingGroup(page: Page) {
  const group = await createGroup(page.request, DINNER_GROUP, [
    { name: 'Persona Ficticia', alias: 'PERSONA FICTICIA' }, // spanish-data
  ])
  const dinner = await fingerprintOf(page.request, FEBRUARY, /RESTAURANTE COMPARTIDO/)
  return addEntry(page.request, group.id, {
    fingerprint: dinner,
    split: 'equal',
    people: group.members.map((m) => m.id),
  })
}

test('home: People by default with the settled ones folded; Groups is in the URL and Back restores it', async ({
  page,
}) => {
  await page.goto('/shared')
  await expect(page.getByRole('heading', { level: 1, name: t('shared.title') })).toBeVisible()
  await expect(page.getByTestId('shared-totals')).toHaveText(
    t('shared.totals.line', { owed: 'RD$ 4,000', owe: 'RD$ 0' }),
  )
  const views = page.getByRole('group', { name: t('shared.view.label') })
  await expect(views.getByRole('button', { name: t('shared.view.people') })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const luis = page.getByRole('list', { name: t('shared.people.label') }).getByRole('link', { name: /Luis/ })
  await expect(luis).toContainText(t('shared.balance.owesYou', { amount: 'RD$ 4,000' }))
  await expect(luis).toContainText(t('shared.people.inGroups', { count: 1 }))
  const settled = page.getByRole('button', { name: t('shared.people.settled', { count: 2 }) })
  await expect(settled).toHaveAttribute('aria-expanded', 'false')
  await settled.click()
  const settledList = page.getByRole('list', { name: t('shared.people.settledLabel') })
  await expect(settledList).toContainText('Marta')
  await expect(settledList).toContainText('Rosa')
  await noSidewaysScroll(page, 'people')

  await views.getByRole('button', { name: t('shared.view.groups') }).click()
  await expect(page).toHaveURL(/\/shared\?view=groups$/)
  const groups = page.getByRole('list', { name: t('shared.groups.label') })
  await groups.getByRole('button', { name: /Ropa de Marta/ }).click()
  await expect(page).toHaveURL(/\/shared\/\d+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Ropa de Marta') // spanish-data
  await expect(page.getByTestId('group-sentence')).toHaveText(t('shared.group.sentence.settled'))
  const payment = page.getByTestId('timeline-payment')
  await expect(payment).toContainText(
    t('shared.payment.line', { from: 'Marta', to: t('shared.you'), amount: 'RD$ 2,175' }),
  )
  await expect(payment).toContainText(t('shared.payment.unlinked'))
  await expect(page.getByTestId('timeline-entry')).toContainText(
    t('shared.entry.lent', { amount: 'RD$ 2,175' }),
  )
  await noSidewaysScroll(page, 'group')

  // The browser's Back returns to Groups.
  await page.goBack()
  await expect(page).toHaveURL(/\/shared\?view=groups$/)
  await expect(views.getByRole('button', { name: t('shared.view.groups') })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  // And so does the page's own «Back».
  await groups.getByRole('button', { name: /Ropa de Marta/ }).click()
  await page.getByRole('button', { name: t('shared.back') }).click()
  await expect(page).toHaveURL(/\/shared\?view=groups$/)
})

test('"Add expense" floats above the bottom bar on a phone and is a header button elsewhere', async ({
  page,
}) => {
  await page.goto('/shared')
  const add = page.getByRole('button', { name: t('shared.addExpense') })
  await expect(add).toBeVisible()
  const box = (await add.boundingBox())!
  expect(box.height).toBeGreaterThanOrEqual(44)
  const bar = page.locator('nav[data-bottom-bar]')
  if (await bar.isVisible()) {
    const barBox = (await bar.boundingBox())!
    expect(box.y + box.height).toBeLessThanOrEqual(barBox.y)
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  } else {
    const title = (await page.getByRole('heading', { level: 1 }).boundingBox())!
    expect(Math.abs(box.y + box.height / 2 - (title.y + title.height / 2))).toBeLessThan(30)
  }
})

test('a person: the per-group breakdown and "Record payment" prefilled with the whole balance', async ({
  page,
}) => {
  await page.goto('/shared')
  await page.getByRole('list', { name: t('shared.people.label') }).getByRole('link', { name: /Luis/ }).click()
  await expect(page).toHaveURL(/\/shared\/people\/\d+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Luis')
  await expect(page.getByTestId('person-balance')).toHaveText(
    t('shared.balance.owesYou', { amount: 'RD$ 4,000' }),
  )
  await page.getByRole('button', { name: t('shared.person.recordPayment') }).click()
  const pay = dialog(page, t('shared.pay.title'))
  await expect(pay.getByTestId('payment-direction')).toHaveText(t('shared.pay.paidYou', { name: 'Luis' }))
  await expect(pay.getByLabel(t('shared.pay.amount'))).toHaveValue('4000.00')
  await expect(pay).toContainText(t('shared.pay.all', { amount: 'RD$ 4,000' }))
  // One tap flips the direction.
  await pay.getByRole('button', { name: t('shared.pay.flip') }).click()
  await expect(pay.getByTestId('payment-direction')).toHaveText(t('shared.pay.youPaid', { name: 'Luis' }))
  await noSidewaysScroll(page, 'payment sheet')
  await page.keyboard.press('Escape')
  await expect(pay).toHaveCount(0)
})

test('a new group with people from the suggestions: a name seen in the bank and a new one', async ({
  page,
}) => {
  await page.goto('/shared?view=groups')
  await page.getByRole('button', { name: t('shared.groups.new') }).click()
  const sheet = dialog(page, t('shared.newGroup.title'))
  await sheet.getByLabel(t('shared.newGroup.name')).fill(NEW_GROUP)
  const people = sheet.getByRole('list', { name: t('shared.newGroup.people') })
  // "You" is always there and cannot be removed.
  await expect(people).toContainText(t('shared.you'))
  await expect(people.getByRole('button', { name: t('shared.people.remove', { name: t('shared.you') }) })).toHaveCount(0)

  const search = sheet.getByLabel(t('shared.newGroup.search'))
  await search.fill('carola')
  const suggestions = sheet.getByRole('list', { name: t('shared.people.suggestions') })
  const seen = suggestions.getByRole('button', { name: /Carola Ficticia/ })
  await expect(seen).toContainText(t('shared.people.seenInBank'))
  await seen.click()
  await search.fill('Ana Nueva') // spanish-data
  await suggestions.getByRole('button', { name: t('shared.people.createNamed', { name: 'Ana Nueva' }) }).click() // spanish-data
  await expect(people).toContainText('Carola Ficticia')
  await expect(people).toContainText('Ana Nueva') // spanish-data
  await noSidewaysScroll(page, 'new group sheet')
  await sheet.getByRole('button', { name: t('shared.newGroup.create') }).click()

  await expect(page).toHaveURL(/\/shared\/\d+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(NEW_GROUP)
  const cards = page.getByRole('list', { name: t('shared.group.cards') })
  await expect(cards).toContainText('Carola Ficticia')
  await expect(cards).toContainText('Ana Nueva') // spanish-data
  // The name seen in the bank became the person's alias.
  const carola = (await contacts(page.request)).contacts.find((c) => c.name === 'Carola Ficticia')
  expect(carola?.aliases).toEqual(['CAROLA FICTICIA'])
})

test('add an expense by both paths: "I paid it" from the bank and "someone else paid"', async ({
  page,
}) => {
  const group = await tripGroup(page)
  await page.goto(`/shared/${group.id}`)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(DINNER_GROUP)

  // Path 1: a recent bank expense, likely ones first; the group is the one we came from.
  await page.getByRole('button', { name: t('shared.addExpense') }).click()
  const paths = dialog(page, t('shared.add.title'))
  await paths.getByRole('button', { name: new RegExp(escapeRegExp(t('shared.add.mine'))) }).click()
  const pick = dialog(page, t('shared.add.pickTitle'))
  const asador = pick.getByRole('button', {
    name: t('shared.add.pickLabel', { merchant: 'ASADOR FICTICIO', amount: 'RD$ 5,200' }),
  })
  await expect(asador).toBeVisible()
  await noSidewaysScroll(page, 'candidates')
  await asador.click()
  const mine = dialog(page, t('shared.add.mine'))
  await expect(mine.getByRole('button', { name: DINNER_GROUP })).toHaveAttribute('aria-pressed', 'true')
  await expect(mine.getByTestId('split-summary')).toHaveText(
    t('shared.add.splitEqual', { count: 3, amount: 'RD$ 1,733' }),
  )
  await mine.getByRole('button', { name: t('shared.add.save') }).click()
  await expect(mine).toHaveCount(0)
  const asadorRow = page.getByTestId('timeline-entry').filter({ hasText: 'ASADOR FICTICIO' })
  await expect(asadorRow).toContainText(
    t('shared.entry.line', { description: 'ASADOR FICTICIO', payer: t('shared.youLower'), amount: 'RD$ 5,200' }),
  )
  // The leftover cent goes to the payer: the others owe RD$ 1,733.33 each.
  await expect(asadorRow).toContainText(t('shared.entry.lent', { amount: 'RD$ 3,467' }))

  // Path 2: a full-screen form with a big amount, "Paid by" and the split line.
  await page.getByRole('button', { name: t('shared.addExpense') }).click()
  await dialog(page, t('shared.add.title'))
    .getByRole('button', { name: new RegExp(escapeRegExp(t('shared.add.other'))) })
    .click()
  const other = dialog(page, t('shared.add.other'))
  const amount = other.getByLabel(t('shared.add.amount'))
  await expect(amount).toHaveAttribute('inputmode', 'decimal')
  await amount.fill('1500')
  await other.getByLabel(t('shared.add.description')).fill('Taxi')
  const payers = other.getByRole('group', { name: t('shared.add.paidBy') })
  await expect(payers.getByRole('button', { name: 'Carola Ficticia' })).toHaveAttribute('aria-pressed', 'true')
  await payers.getByRole('button', { name: 'Pedro Ficticio' }).click()
  await expect(other.getByTestId('split-summary')).toHaveText(
    t('shared.add.splitEqual', { count: 3, amount: 'RD$ 500' }),
  )
  await noSidewaysScroll(page, 'paid by someone else')
  await other.getByRole('button', { name: t('shared.add.save') }).click()
  await expect(other).toHaveCount(0)
  const taxi = page.getByTestId('timeline-entry').filter({ hasText: 'Taxi' })
  await expect(taxi).toContainText(
    t('shared.entry.line', { description: 'Taxi', payer: 'Pedro Ficticio', amount: 'RD$ 1,500' }),
  )
  await expect(taxi).toContainText(t('shared.entry.owe', { amount: 'RD$ 500' }))
})

test('exact amounts start from the current split; the shortfall is live and it saves when it adds up', async ({
  page,
}) => {
  const group = await tripGroup(page)
  await page.goto(`/shared/${group.id}`)
  await page.getByRole('button', { name: t('shared.addExpense') }).click()
  await dialog(page, t('shared.add.title'))
    .getByRole('button', { name: new RegExp(escapeRegExp(t('shared.add.other'))) })
    .click()
  const form = dialog(page, t('shared.add.other'))
  await form.getByLabel(t('shared.add.amount')).fill('900')
  await form.getByLabel(t('shared.add.description')).fill('Supermercado') // spanish-data
  await form.getByTestId('split-summary').click()

  const split = dialog(page, t('shared.split.title'))
  await split.getByLabel(t('shared.split.exact')).check()
  const done = split.getByRole('button', { name: t('shared.done') })
  const shortfall = split.getByTestId('split-shortfall')
  const you = split.getByLabel(t('shared.split.amountOf', { name: t('shared.you') }))
  const pedro = split.getByLabel(t('shared.split.amountOf', { name: 'Pedro Ficticio' }))
  // Prefilled with the equal split: it already adds up, only the different one is edited.
  await expect(you).toHaveValue('300.00')
  await expect(split.getByLabel(t('shared.split.amountOf', { name: 'Carola Ficticia' }))).toHaveValue('300.00')
  await expect(pedro).toHaveValue('300.00')
  await expect(shortfall).toHaveText(t('shared.split.addsUp'))
  await expect(done).toBeEnabled()
  await you.fill('200')
  await expect(shortfall).toHaveText(t('shared.split.missing', { amount: 'RD$ 100' }))
  await expect(done).toBeDisabled()
  // Unchecking a person drops their amount; checking them again starts at 0.
  const pedroBox = split.getByRole('checkbox', { name: 'Pedro Ficticio' })
  await pedroBox.uncheck()
  await expect(shortfall).toHaveText(t('shared.split.missing', { amount: 'RD$ 400' }))
  await pedroBox.check()
  await expect(pedro).toHaveValue('0.00')
  await expect(shortfall).toHaveText(t('shared.split.missing', { amount: 'RD$ 400' }))
  await pedro.fill('500')
  await expect(shortfall).toHaveText(t('shared.split.over', { amount: 'RD$ 100' }))
  await expect(done).toBeDisabled()
  await pedro.fill('400')
  await expect(shortfall).toHaveText(t('shared.split.addsUp'))
  await noSidewaysScroll(page, 'split sheet')
  await done.click()
  await expect(split).toHaveCount(0)
  await expect(form.getByTestId('split-summary')).toHaveText(t('shared.add.splitExact'))
  await form.getByRole('button', { name: t('shared.add.save') }).click()
  await expect(form).toHaveCount(0)
  await expect(page.getByTestId('timeline-entry').filter({ hasText: 'Supermercado' })).toContainText( // spanish-data
    t('shared.entry.owe', { amount: 'RD$ 200' }),
  )
})

test("a split by parts: steppers, the amounts by parts, and the detail shows each one's parts", async ({
  page,
}) => {
  const group = await tripGroup(page)
  await page.goto(`/shared/${group.id}`)
  await page.getByRole('button', { name: t('shared.addExpense') }).click()
  await dialog(page, t('shared.add.title'))
    .getByRole('button', { name: new RegExp(escapeRegExp(t('shared.add.other'))) })
    .click()
  const form = dialog(page, t('shared.add.other'))
  await form.getByLabel(t('shared.add.amount')).fill('1200')
  await form.getByLabel(t('shared.add.description')).fill('Entradas') // spanish-data
  await form.getByTestId('split-summary').click()
  const split = dialog(page, t('shared.split.title'))
  await split.getByLabel(t('shared.split.parts')).check()
  const amounts = split.getByTestId('split-amount')
  await expect(amounts).toHaveText(['RD$ 400', 'RD$ 400', 'RD$ 400'])
  const more = split.getByRole('button', { name: t('shared.split.morePart', { name: 'Pedro Ficticio' }) })
  const less = split.getByRole('button', { name: t('shared.split.lessPart', { name: 'Pedro Ficticio' }) })
  await expect(less).toBeDisabled() // never under 1 part
  const box = await more.boundingBox()
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  expect(box?.width ?? 0).toBeGreaterThanOrEqual(44)
  await more.click()
  await expect(amounts).toHaveText(['RD$ 300', 'RD$ 300', 'RD$ 600'])
  await noSidewaysScroll(page, 'split by parts')
  await split.getByRole('button', { name: t('shared.done') }).click()
  await expect(form.getByTestId('split-summary')).toHaveText(t('shared.add.splitParts', { count: 4 }))
  await form.getByRole('button', { name: t('shared.add.save') }).click()
  await expect(form).toHaveCount(0)
  const row = page.getByTestId('timeline-entry').filter({ hasText: 'Entradas' }) // spanish-data
  await expect(row).toContainText(t('shared.entry.owe', { amount: 'RD$ 300' }))
  await row.click()
  const detail = dialog(page, t('shared.detail.entry'))
  await expect(detail.getByRole('list', { name: t('shared.detail.split') })).toContainText(
    t('shared.detail.partsLine', { count: 2, amount: 'RD$ 600' }),
  )
  // Editing keeps the mode.
  await detail.getByRole('button', { name: t('shared.detail.edit') }).click()
  await expect(page.getByTestId('split-summary')).toHaveText(t('shared.add.splitParts', { count: 4 }))
})

test('removing a person: why someone who paid stays, and "Remove from N expenses" re-splits in one undo', async ({
  page,
}) => {
  const group = await tripGroup(page)
  const me = group.members.find((m) => m.is_me)!.id
  const carola = group.members.find((m) => m.name === 'Carola Ficticia')!.id
  const pedro = group.members.find((m) => m.name === 'Pedro Ficticio')!.id
  await addEntry(page.request, group.id, {
    paid_by: me,
    amount_cents: 90_000,
    description: 'Taxi de prueba', // spanish-data
    day: '2026-02-10',
    split: 'equal',
    people: [me, carola, pedro],
  })
  await addEntry(page.request, group.id, {
    paid_by: carola,
    amount_cents: 60_000,
    description: 'Cine de prueba', // spanish-data
    day: '2026-02-11',
    split: 'exact',
    shares: [
      { contact_id: me, cents: 10_000 },
      { contact_id: carola, cents: 20_000 },
      { contact_id: pedro, cents: 30_000 },
    ],
  })
  // Only Pedro's: without him nobody else is left, so it would be all mine.
  await addEntry(page.request, group.id, {
    paid_by: me,
    amount_cents: 5_000,
    description: 'Regalo de prueba', // spanish-data
    day: '2026-02-12',
    split: 'exact',
    shares: [{ contact_id: pedro, cents: 5_000 }],
  })
  await page.goto(`/shared/${group.id}`)
  await page.getByRole('button', { name: t('shared.menuOf', { name: DINNER_GROUP }) }).click()
  await dialog(page, DINNER_GROUP).getByRole('button', { name: t('shared.group.people') }).click()
  const people = dialog(page, t('shared.group.people'))
  // Carola paid an expense: she stays, and it says why.
  await people.getByRole('button', { name: t('shared.group.removePerson', { name: 'Carola Ficticia' }) }).click()
  const panel = people.getByTestId('remove-person')
  await expect(panel.getByRole('status')).toContainText('Cine de prueba') // spanish-data
  await expect(panel.getByRole('button', { name: t('shared.group.removeResplit', { count: 1 }) })).toHaveCount(0)
  await panel.getByRole('button', { name: t('shared.group.removeCancel') }).click()
  // Pedro only has shares: one step takes him out of all three and re-splits them, each shown
  // as it would be before confirming.
  await people.getByRole('button', { name: t('shared.group.removePerson', { name: 'Pedro Ficticio' }) }).click()
  const shares = panel.getByTestId('remove-share')
  await expect(shares.filter({ hasText: 'Taxi de prueba' })).toContainText( // spanish-data
    t('shared.group.removeAfter', { split: `${t('shared.you')} RD$ 450 · Carola Ficticia RD$ 450` }),
  )
  const gift = shares.filter({ hasText: 'Regalo de prueba' }) // spanish-data
  await expect(gift.getByRole('note')).toHaveText(t('shared.group.removeToYou'))
  await noSidewaysScroll(page, 'remove person')
  // It erases what Pedro owed for the gift: it has to be acknowledged first.
  const confirm = panel.getByRole('button', { name: t('shared.group.removeResplit', { count: 3 }) })
  await expect(confirm).toBeDisabled()
  await panel.getByRole('checkbox', { name: t('shared.group.removeUnderstood', { name: 'Pedro Ficticio', count: 1 }) }).check()
  await confirm.click()
  await expect(panel).toHaveCount(0)
  await expect(people.getByRole('list', { name: t('shared.group.people') }).first()).not.toContainText('Pedro Ficticio')
  await page.keyboard.press('Escape')
  // Equal: RD$ 900 between the two left (Carola owes RD$ 450). Exact: Pedro's RD$ 300 goes 1:2 to
  // me and Carola (I owe RD$ 200).
  await expect(page.getByTestId('timeline-entry').filter({ hasText: 'Taxi de prueba' })).toContainText( // spanish-data
    t('shared.entry.lent', { amount: 'RD$ 450' }),
  )
  await expect(page.getByTestId('timeline-entry').filter({ hasText: 'Cine de prueba' })).toContainText( // spanish-data
    t('shared.entry.owe', { amount: 'RD$ 200' }),
  )
  // One change in the log, undone in one step.
  await page.goto('/log')
  const line = `Quitaste a Pedro Ficticio del grupo ${DINNER_GROUP} y de 3 gasto(s), divididos entre los demás` // spanish-data: backend log line
  await page.getByRole('button', { name: t('log.row.undoNamed', { name: line }), exact: true }).click()
  await expect(page.getByRole('button', { name: t('log.row.redoNamed', { name: line }), exact: true })).toBeVisible()
  await page.goto(`/shared/${group.id}`)
  await expect(page.getByTestId('timeline-entry').filter({ hasText: 'Taxi de prueba' })).toContainText( // spanish-data
    t('shared.entry.lent', { amount: 'RD$ 600' }),
  )
})

test('a payment on behalf of others settles both people in one go', async ({ page }) => {
  const group = await createGroup(page.request, DINNER_GROUP, [
    { name: 'Javier Ficticio' }, // spanish-data
    { name: 'Gordo Ficticio' }, // spanish-data
  ])
  await addEntry(page.request, group.id, {
    paid_by: group.members.find((m) => m.is_me)!.id,
    amount_cents: 90_000,
    description: 'Entradas', // spanish-data
    day: '2026-02-10',
    split: 'equal',
    people: group.members.map((m) => m.id),
  })
  await page.goto(`/shared/${group.id}`)
  await page
    .getByRole('list', { name: t('shared.group.cards') })
    .getByRole('button', { name: /^Javier Ficticio/ })
    .click()
  const pay = dialog(page, t('shared.pay.title'))
  const amount = pay.getByLabel(t('shared.pay.amount'))
  await expect(amount).toHaveValue('300.00')
  await pay.getByRole('checkbox', { name: t('shared.pay.coversLabel', { name: 'Gordo Ficticio' }) }).check()
  // Payer first: the RD$ 300 typed are all Javier's own balance, nothing is left for Gordo.
  await expect(amount).toHaveValue('300.00')
  const gordo = pay.getByLabel(t('shared.pay.allocationOf', { name: 'Gordo Ficticio' }))
  await expect(gordo).toHaveValue('0.00')
  // Paying RD$ 600 proposes Gordo's RD$ 300 after Javier's.
  await amount.fill('600')
  await expect(gordo).toHaveValue('300.00')
  await expect(pay.getByLabel(t('shared.pay.allocationOf', { name: 'Javier Ficticio' }))).toHaveValue('300.00')
  const shortfall = pay.getByTestId('allocation-shortfall')
  await expect(shortfall).toHaveText(t('shared.split.addsUp'))
  await gordo.fill('250')
  await expect(shortfall).toHaveText(t('shared.split.missing', { amount: 'RD$ 50' }))
  await expect(pay.getByRole('button', { name: t('shared.next') })).toBeDisabled()
  await gordo.fill('300')
  await noSidewaysScroll(page, 'paid for others')
  await pay.getByRole('button', { name: t('shared.next') }).click()
  await dialog(page, t('shared.pay.bankTitle')).getByRole('button', { name: t('shared.pay.notYet') }).click()
  const line = t('shared.payment.line', { from: 'Javier Ficticio', to: t('shared.you'), amount: 'RD$ 600' })
  await expect(page.getByTestId('timeline-payment')).toContainText(
    `${line} ${t('shared.payment.covers', { names: 'Gordo Ficticio' })}`,
  )
  await expect(page.getByTestId('group-sentence')).toHaveText(t('shared.group.sentence.settled'))
})

/** The synthetic case of tests/ledger_cover_case.py: two US$ expenses the user paid, split among
 * three; Ana paid three times in RD$ (really for herself and Beto) and Beto once. Each of Ana's
 * payments is hers alone, so the last one's excess is a RD$ claim the other way while Beto still
 * owes: owed US$ 629.31 and owing RD$ 40,108. The e2e server's rates: 63.10, 63.40, 63.70. */
async function coverCase(page: Page) {
  const group = await createGroup(page.request, COVER_GROUP, [
    { name: 'Ana Viajera' }, // spanish-data
    { name: 'Beto Viajero' }, // spanish-data
  ])
  const me = group.members.find((m) => m.is_me)!.id
  const ana = group.members.find((m) => m.name === 'Ana Viajera')!.id
  const beto = group.members.find((m) => m.name === 'Beto Viajero')!.id
  for (const [cents, day] of [
    [240_000, '2025-12-05'],
    [142_800, '2025-12-10'],
  ] as const) {
    await addEntry(page.request, group.id, {
      paid_by: me,
      amount_cents: cents,
      currency: 'USD',
      day,
      description: 'Hotel',
      split: 'equal',
      people: [me, ana, beto],
    })
  }
  let fresh = group
  for (const [from, cents, day] of [
    [ana, 4_000_000, '2025-12-20'],
    [ana, 4_000_000, '2026-01-15'],
    [beto, 4_100_000, '2026-01-20'],
    [ana, 4_082_000, '2026-02-10'],
  ] as const) {
    fresh = await addPayment(page.request, group.id, {
      from_contact: from,
      to_contact: me,
      amount_cents: cents,
      currency: 'DOP',
      day,
    })
  }
  return fresh
}

const COVER_GROUP = 'Viaje en dólares' // spanish-data
const COVER_SENTENCE = `${t('shared.group.sentence.owed', { amount: 'US$ 629.31' })} · ${t('shared.group.sentence.owe', { amount: 'RD$ 40,108' })}`

test('one person paid for several in RD$: To review proposes it and both end settled', async ({
  page,
}) => {
  const group = await coverCase(page)
  await page.goto(`/shared/${group.id}`)
  await expect(page.getByTestId('group-sentence')).toHaveText(COVER_SENTENCE)
  await expect(page.getByTestId('group-total')).toHaveText(t('shared.total.owe', { amount: 'RD$ 21' }))
  await expect(page.getByTestId('cover-notice')).toContainText('¿Ese pago también era por Beto Viajero?') // spanish-data

  // The review list lives on /review (the Summary only counts it).
  await page.goto(`/review?month=${FEBRUARY}`)
  const card = page.getByRole('region', { name: literal(t('summary.review.title')) })
  const yes = card.getByRole('button', { name: t('summary.review.coverLabel', { merchant: COVER_GROUP }) })
  const seeAll = card.getByRole('button', { name: new RegExp(escapeRegExp(t('summary.review.seeAll', { count: 0 }).split('(')[0])) })
  if ((await yes.count()) === 0 && (await seeAll.count()) > 0) await seeAll.click()
  await yes.click()

  await expect(page).toHaveURL(new RegExp(`/shared/${group.id}\\?cover=`))
  const sheet = dialog(page, t('shared.plan.title'))
  // Payer first: Ana's own US$ 11.18 (RD$ 712.17 at 63.70) and the rest is hers; Beto's US$ 629.31.
  const payments = sheet.getByTestId('plan-payment')
  await expect(payments).toHaveCount(1)
  await expect(payments.first()).toContainText('RD$ 733')
  await expect(payments.first()).toContainText(
    t('shared.rate.conversion', {
      amount: 'RD$ 40,087',
      converted: 'US$ 629.31',
      rate: t('shared.rate.line', { value: '63.70', month: 'feb' }),
    }),
  )
  const after = sheet.getByRole('list', { name: t('shared.plan.after') })
  await expect(after).toContainText(t('shared.leftover.settled', { amount: 'RD$ 21' }))
  await noSidewaysScroll(page, 'cover plan')
  await sheet.getByRole('button', { name: t('shared.plan.confirm') }).click()
  await expect(sheet).toHaveCount(0)

  // The payment's detail: who it covers and the rate it settled with.
  await page.getByTestId('timeline-payment').first().click()
  const detail = dialog(page, t('shared.detail.payment'))
  await expect(detail.getByRole('list', { name: t('shared.detail.coveredFor') })).toContainText('Beto Viajero')
  await expect(detail.getByTestId('payment-rate')).toHaveText(
    t('shared.detail.rateUsed', { rate: t('shared.rate.line', { value: '63.70', month: 'feb' }) }),
  )
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('group-sentence')).toHaveText(t('shared.group.sentence.settled'))
  await expect(page.getByTestId('cover-notice')).toHaveCount(0)
  const cards = page.getByRole('list', { name: t('shared.group.cards') })
  await expect(cards.getByRole('button', { name: /^Ana Viajera/ })).toContainText(
    t('shared.leftover.settled', { amount: 'RD$ 21' }),
  )
  await expect(cards.getByRole('button', { name: /^Beto Viajero/ })).toContainText(t('shared.balance.settled'))
})

/** One payer for two in three payments (made-up figures, tests/ledger_cover_case.py `spread_group`)
 * at the e2e server's February rate: Ana pays three times in RD$, really for herself and Beto,
 * who paid once; each of her payments is hers alone. */
async function spreadCase(page: Page) {
  const group = await createGroup(page.request, SPREAD_GROUP, [
    { name: 'Ana Viajera' }, // spanish-data
    { name: 'Beto Viajero' }, // spanish-data
  ])
  const me = group.members.find((m) => m.is_me)!.id
  const ana = group.members.find((m) => m.name === 'Ana Viajera')!.id
  const beto = group.members.find((m) => m.name === 'Beto Viajero')!.id
  for (const [cents, day] of [
    [300_000, '2026-01-10'],
    [150_030, '2026-01-20'],
  ] as const) {
    await addEntry(page.request, group.id, {
      paid_by: me,
      amount_cents: cents,
      currency: 'USD',
      day,
      description: 'Hotel',
      split: 'equal',
      people: [me, ana, beto],
    })
  }
  for (const [from, cents, day] of [
    [ana, 9_800_000, '2026-02-03'],
    [beto, 3_000_000, '2026-02-05'],
    [ana, 2_000_000, '2026-02-08'],
    [ana, 2_500_000, '2026-02-12'],
  ] as const) {
    await addPayment(page.request, group.id, { from_contact: from, to_contact: me, amount_cents: cents, currency: 'DOP', day })
  }
  return group
}

const SPREAD_GROUP = 'Viaje largo' // spanish-data

test('three payments for two people: one suggestion, one review and one change settle it', async ({
  page,
}) => {
  const group = await spreadCase(page)
  await page.goto(`/shared/${group.id}`)
  const notice = page.getByTestId('cover-notice')
  await expect(notice).toContainText('de más en 3 pagos') // spanish-data
  await expect(notice).toContainText('¿Esos pagos también eran por Beto Viajero?') // spanish-data
  await notice.getByRole('button', { name: t('shared.cover.yesLabel', { name: 'Ana Viajera' }) }).click()

  const sheet = dialog(page, t('shared.plan.title'))
  await expect(sheet.getByTestId('plan-payment')).toHaveCount(3)
  await expect(sheet.getByTestId('plan-payment').first()).toContainText(
    t('shared.plan.payment', { day: '3 feb', amount: 'RD$ 98,000' }),
  )
  await noSidewaysScroll(page, 'three payments plan')
  const mark = await logMark(page.request)
  await sheet.getByRole('button', { name: t('shared.plan.confirm') }).click()
  await expect(sheet).toHaveCount(0)

  // One change in the log; the user owes Ana nothing and Beto owes what her payments did not cover.
  const response = await page.request.get('/api/log?limit=20')
  const items = ((await response.json()) as { items: { id: number }[] }).items
  expect(items.filter((e) => e.id > mark)).toHaveLength(1)
  const fresh = (await (await page.request.get(`/api/shared/groups/${group.id}`)).json()) as Group
  expect(fresh.i_owe).toEqual([])
  expect(fresh.owed_to_me).toHaveLength(1)
  const left = fresh.owed_to_me[0]
  expect(left.currency).toBe('USD')
  await expect(page.getByTestId('group-sentence')).toHaveText(
    t('shared.group.sentence.owed', { amount: `US$ ${(left.cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}` }),
  )
  await expect(page.getByTestId('cover-notice')).toHaveCount(0)
})

test('«No» keeps the payment as it was; the leftover toggle brings the RD$ 21 back', async ({ page }) => {
  const group = await coverCase(page)
  await page.goto(`/shared/${group.id}`)
  const notice = page.getByTestId('cover-notice')
  await notice.getByRole('button', { name: t('shared.cover.noLabel', { name: 'Ana Viajera' }) }).click()
  await expect(notice).toHaveCount(0)
  await expect(page.getByTestId('group-sentence')).toHaveText(COVER_SENTENCE)

  // Covering Beto from the payment's detail, then counting Ana's exchange leftover again.
  await page.getByTestId('timeline-payment').first().click()
  const detail = dialog(page, t('shared.detail.payment'))
  await detail.getByRole('button', { name: t('shared.detail.alsoPaidFor') }).click()
  const sheet = dialog(page, t('shared.detail.alsoPaidFor'))
  await sheet.getByRole('checkbox', { name: t('shared.pay.coversLabel', { name: 'Beto Viajero' }) }).check()
  await expect(sheet.getByLabel(t('shared.pay.allocationOf', { name: 'Beto Viajero' }))).toHaveValue('40087.05')
  await sheet.getByRole('button', { name: t('shared.detail.saveCovers') }).click()
  await expect(dialog(page, t('shared.detail.payment'))).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('group-sentence')).toHaveText(t('shared.group.sentence.settled'))

  await page.getByRole('button', { name: t('shared.menuOf', { name: COVER_GROUP }) }).click()
  const menu = dialog(page, COVER_GROUP)
  await menu.getByRole('button', { name: t('shared.group.leftover') }).click()
  const toggle = dialog(page, t('shared.group.leftover')).getByRole('checkbox', {
    name: new RegExp(escapeRegExp(t('shared.group.leftoverPerson', { name: 'Ana Viajera' }))),
  })
  await expect(toggle).toBeChecked()
  await toggle.click() // saved at once (and logged): it shows unchecked when the group is back
  await expect(toggle).not.toBeChecked()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('group-sentence')).toHaveText(
    t('shared.group.sentence.owe', { amount: 'RD$ 21' }),
  )
})

test('the log: one row per change, a sentence that links to the group, undo and redo toggle it', async ({
  page,
}) => {
  // Its own name per project and run: the log keeps the (undone) rows of earlier runs.
  const name = `${NEW_GROUP} ${test.info().project.name} ${Date.now()}`
  const group = await createGroup(page.request, name, [{ name: 'Javier Ficticio' }]) // spanish-data
  const added = await page.request.post(`/api/shared/groups/${group.id}/members`, {
    headers: { 'X-Michelito': '1' },
    data: { name: 'Gordo Ficticio' }, // spanish-data
  })
  expect(added.ok()).toBe(true)
  await page.goto('/log')
  await page.getByRole('searchbox', { name: t('log.filter.search') }).fill(name)
  const line = `Agregaste a Gordo Ficticio al grupo ${name}` // spanish-data: backend log line
  const row = page.getByRole('listitem').filter({ hasText: line })
  await expect(row).toHaveCount(1)
  await expect(row).not.toContainText(t('log.affected', { count: 0 }))
  await expect(row.getByRole('link', { name: t('log.row.viewGroup') })).toHaveAttribute('href', `/shared/${group.id}`)
  await expect(row.getByRole('link', { name: t('log.row.viewTransaction') })).toHaveCount(0)
  const items = page.getByRole('main').getByRole('listitem')
  const rows = await items.count()
  await row.getByRole('button', { name: t('log.row.undoNamed', { name: line }), exact: true }).click()
  const redo = row.getByRole('button', { name: t('log.row.redoNamed', { name: line }), exact: true })
  await expect(redo).toBeVisible()
  await expect(row.getByText(t('log.row.undoneBadge'), { exact: true })).toBeVisible()
  await expect(page.getByRole('main')).not.toContainText(t('log.undone', { line: '' }).trim())
  await redo.click()
  await expect(row.getByRole('button', { name: t('log.row.undoNamed', { name: line }), exact: true })).toBeVisible()
  await expect(row.getByTestId('log-toggled')).toHaveText(t('log.row.toggled', { count: 2 }))
  await expect(items).toHaveCount(rows)
  await noSidewaysScroll(page, 'log')
})

test('register a payment: linked to a bank candidate with a difference, then one "Not yet"', async ({
  page,
}) => {
  const group = await owingGroup(page)
  await page.goto(`/shared/${group.id}`)
  await expect(page.getByTestId('group-sentence')).toHaveText(
    t('shared.group.sentence.owed', { amount: 'RD$ 1,500' }),
  )
  // The person's card opens the payment prefilled with them and what they owe.
  await page
    .getByRole('list', { name: t('shared.group.cards') })
    .getByRole('button', { name: /^Persona Ficticia/ })
    .click()
  const pay = dialog(page, t('shared.pay.title'))
  await expect(pay.getByTestId('payment-direction')).toHaveText(
    t('shared.pay.paidYou', { name: 'Persona Ficticia' }),
  )
  await expect(pay.getByLabel(t('shared.pay.amount'))).toHaveValue('1500.00')
  // She says she sent RD$ 1,050 on Feb 5; the bank got RD$ 1,000 on the 4th.
  await pay.getByLabel(t('shared.pay.amount')).fill('1050')
  await pay.getByLabel(t('shared.add.day')).fill('2026-02-05')
  await pay.getByRole('button', { name: t('shared.next') }).click()
  const bank = dialog(page, t('shared.pay.bankTitle'))
  const toke = bank.getByRole('button', { name: /TOKE DE PERSONA/ })
  await expect(toke).toBeVisible()
  await toke.click()
  await expect(bank.getByTestId('payment-difference')).toHaveText(
    t('shared.detail.difference', { sent: 'RD$ 1,050', received: 'RD$ 1,000', difference: 'RD$ 50' }),
  )
  await bank.getByRole('button', { name: t('shared.detail.acceptDifference') }).click()
  await expect(bank).toHaveCount(0)
  const linked = page.getByTestId('timeline-payment').filter({ hasText: 'RD$ 1,000' })
  await expect(linked).toContainText(
    t('shared.payment.line', { from: 'Persona Ficticia', to: t('shared.you'), amount: 'RD$ 1,000' }),
  )
  await expect(linked).toContainText(t('shared.payment.inBank'))

  // Another one, not in the bank yet: saved unlinked, with «Enlazar».
  await page.getByRole('button', { name: t('shared.group.recordPayment'), exact: true }).click()
  const second = dialog(page, t('shared.pay.title'))
  await second.getByLabel(t('shared.pay.amount')).fill('200')
  await second.getByRole('button', { name: t('shared.next') }).click()
  await dialog(page, t('shared.pay.bankTitle')).getByRole('button', { name: t('shared.pay.notYet') }).click()
  const loose = page.getByTestId('timeline-payment').filter({ hasText: 'RD$ 200' })
  await expect(loose).toContainText(t('shared.payment.unlinked'))
  await expect(
    loose.getByRole('button', {
      name: t('shared.payment.linkLabel', { from: 'Persona Ficticia', to: t('shared.you') }),
    }),
  ).toBeVisible()
})

test('To review proposes the credit as her payment; one tap records and links it', async ({
  page,
}) => {
  const group = await owingGroup(page)
  await page.goto(`/review?month=${FEBRUARY}`)
  const card = page.getByRole('region', { name: literal(t('summary.review.title')) })
  const yes = card.getByRole('button', {
    name: new RegExp(`^${escapeRegExp(t('summary.review.paymentLabel', { merchant: '' }))}TOKE DE PERSONA`),
  })
  const seeAll = card.getByRole('button', { name: new RegExp(escapeRegExp(t('summary.review.seeAll', { count: 0 }).split('(')[0])) })
  if ((await yes.count()) === 0 && (await seeAll.count()) > 0) await seeAll.click()
  await expect(yes).toBeVisible()
  await yes.click()
  await expect(yes).toHaveCount(0)

  await page.goto(`/shared/${group.id}`)
  const payment = page.getByTestId('timeline-payment')
  await expect(payment).toContainText(
    t('shared.payment.line', { from: 'Persona Ficticia', to: t('shared.you'), amount: 'RD$ 1,000' }),
  )
  await expect(payment).toContainText(t('shared.payment.inBank'))
  await expect(page.getByTestId('group-sentence')).toHaveText(
    t('shared.group.sentence.owed', { amount: 'RD$ 500' }),
  )
})

test('an unattributed payment shows a band; «Asignar» gives it to a person in one tap', async ({
  page,
}) => {
  const group = await tripGroup(page)
  const me = group.members.find((m) => m.is_me)!
  await addPayment(page.request, group.id, {
    from_contact: null,
    to_contact: me.id,
    amount_cents: 50_000,
    currency: 'DOP',
    day: '2026-02-10',
  })
  await page.goto(`/shared/${group.id}`)
  const band = page.getByTestId('unattributed-band')
  await expect(band).toContainText(t('shared.unattributed.band', { count: 1 }))
  await band.getByRole('button', { name: t('shared.unattributed.assign') }).click()
  const sheet = dialog(page, t('shared.unattributed.title'))
  await sheet.getByRole('button', { name: t('shared.unattributed.from', { name: 'Carola Ficticia' }) }).click()
  await expect(sheet).toHaveCount(0)
  await expect(band).toHaveCount(0)
  await expect(page.getByTestId('timeline-payment')).toContainText(
    t('shared.payment.line', { from: 'Carola Ficticia', to: t('shared.you'), amount: 'RD$ 500' }),
  )
})

test('a payment given to the wrong person: «change who paid» gives it to the right one', async ({
  page,
}) => {
  const group = await tripGroup(page)
  const me = group.members.find((m) => m.is_me)!
  const carola = group.members.find((m) => m.name === 'Carola Ficticia')!
  const pedro = group.members.find((m) => m.name === 'Pedro Ficticio')!
  await addPayment(page.request, group.id, {
    from_contact: carola.id,
    to_contact: me.id,
    amount_cents: 75_000,
    currency: 'DOP',
    day: '2026-02-10',
    allocations: [{ contact_id: pedro.id, cents: 75_000 }],
  })
  await page.goto(`/shared/${group.id}`)
  await page.getByTestId('timeline-payment').click()
  const detail = dialog(page, t('shared.detail.payment'))
  await detail.getByRole('button', { name: t('shared.detail.changePayer') }).click()
  await expect(detail).toContainText(t('shared.detail.changePayerHint'))
  await expect(
    detail.getByRole('button', { name: t('shared.unattributed.from', { name: 'Carola Ficticia' }) }),
  ).toHaveCount(0)
  await noSidewaysScroll(page, 'change payer')
  await detail.getByRole('button', { name: t('shared.unattributed.from', { name: 'Pedro Ficticio' }) }).click()
  await expect(detail.getByRole('button', { name: t('shared.detail.changePayer') })).toBeVisible()
  await expect(detail).toContainText(
    t('shared.payment.line', { from: 'Pedro Ficticio', to: t('shared.you'), amount: 'RD$ 750' }),
  )
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('timeline-payment')).toContainText(
    t('shared.payment.line', { from: 'Pedro Ficticio', to: t('shared.you'), amount: 'RD$ 750' }),
  )
})

test('a row opens its detail with only what applies; deleting it can be undone', async ({ page }) => {
  const group = await tripGroup(page)
  const carola = group.members.find((m) => m.name === 'Carola Ficticia')!
  await addEntry(page.request, group.id, {
    paid_by: carola.id,
    amount_cents: 90_000,
    currency: 'DOP',
    day: '2026-02-12',
    description: 'Pizza',
    split: 'equal',
    people: group.members.map((m) => m.id),
  })
  await page.goto(`/shared/${group.id}`)
  await page.getByTestId('timeline-entry').filter({ hasText: 'Pizza' }).click()
  const detail = dialog(page, t('shared.detail.entry'))
  await expect(detail.getByRole('list', { name: t('shared.detail.split') })).toContainText('RD$ 300')
  // Paid by someone else: nothing in the user's bank, so no «Abrir».
  await expect(detail.getByRole('link', { name: new RegExp(escapeRegExp(t('shared.detail.open'))) })).toHaveCount(0)
  await detail.getByRole('button', { name: t('shared.detail.delete') }).click()
  await detail.getByRole('button', { name: t('shared.detail.deleteConfirm') }).click()
  await expect(detail.getByRole('status')).toHaveText(t('shared.detail.deleted'))
  await expect(page.getByTestId('timeline-entry')).toHaveCount(0)
  await detail.getByRole('button', { name: t('shared.detail.undo') }).click()
  await expect(detail.getByRole('status')).toHaveText(t('shared.detail.undone'))
  await expect(page.getByTestId('timeline-entry').filter({ hasText: 'Pizza' })).toHaveCount(1)
})

test('empty: suggestions from the data with «Dividir», otherwise a designed empty state', async ({
  page,
}) => {
  const asador = await fingerprintOf(page.request, FEBRUARY, /ASADOR FICTICIO/)
  const suggestion = {
    fingerprint: asador,
    day: '2026-02-09',
    merchant: 'ASADOR FICTICIO',
    account_label: 'VISA DEMO ···4242',
    amount_cents: 520_000,
    currency: 'DOP',
  }
  let suggestions = [suggestion]
  await page.route('**/api/shared', (route) =>
    route.fulfill({
      json: { totals: [], people: [], groups: [], review_people: false, suggestions },
    }),
  )
  await page.goto('/shared')
  const block = page.getByRole('region', { name: t('shared.suggestions.title') })
  await expect(block).toContainText('ASADOR FICTICIO')
  await block.getByRole('button', { name: t('shared.suggestions.splitLabel', { merchant: 'ASADOR FICTICIO' }) }).click()
  const mine = dialog(page, t('shared.add.mine'))
  await expect(mine).toContainText('ASADOR FICTICIO')
  await expect(mine).toContainText(t('shared.add.noGroups'))
  await page.keyboard.press('Escape')

  suggestions = []
  await page.reload()
  const empty = page.getByRole('region', { name: t('shared.empty.title') })
  await expect(empty).toContainText(t('shared.empty.text'))
  await empty.getByRole('button', { name: t('shared.empty.action') }).click()
  await expect(dialog(page, t('shared.newGroup.title'))).toBeVisible()
  await noSidewaysScroll(page, 'empty')
})

test('«Revisa tus personas» shows once after the migration and «Listo» closes it', async ({ page }) => {
  await page.route('**/api/shared', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({ response, json: { ...body, review_people: true } })
  })
  await page.route('**/api/shared/review-people/done', (route) => route.fulfill({ status: 204 }))
  await page.goto('/shared')
  const sheet = dialog(page, t('shared.review.title'))
  await expect(sheet.getByRole('textbox', { name: t('shared.person.nameLabel') }).first()).toBeVisible()
  await expect(sheet.getByRole('combobox', { name: t('shared.review.mergeLabel', { name: 'Luis' }) })).toBeVisible()
  await sheet.getByRole('button', { name: t('shared.review.done') }).click()
  await expect(sheet).toHaveCount(0)
})

// The Summary fetches the months around in the background: a request still on its way through a
// route of this file when a test ends is dropped, not reported as that test's failure.
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})
