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

test('an exact split shows the shortfall live and only saves when it adds up', async ({ page }) => {
  const group = await tripGroup(page)
  await page.goto(`/shared/${group.id}`)
  await page.getByRole('button', { name: t('shared.addExpense') }).click()
  await dialog(page, t('shared.add.title'))
    .getByRole('button', { name: new RegExp(escapeRegExp(t('shared.add.other'))) })
    .click()
  const form = dialog(page, t('shared.add.other'))
  await form.getByLabel(t('shared.add.amount')).fill('1000')
  await form.getByLabel(t('shared.add.description')).fill('Supermercado') // spanish-data
  await form.getByTestId('split-summary').click()

  const split = dialog(page, t('shared.split.title'))
  await split.getByLabel(t('shared.split.exact')).check()
  const done = split.getByRole('button', { name: t('shared.done') })
  const shortfall = split.getByTestId('split-shortfall')
  await split.getByLabel(t('shared.split.amountOf', { name: t('shared.you') })).fill('300')
  await expect(shortfall).toHaveText(t('shared.split.missing', { amount: 'RD$ 700' }))
  await expect(done).toBeDisabled()
  await split.getByLabel(t('shared.split.amountOf', { name: 'Carola Ficticia' })).fill('500')
  await expect(shortfall).toHaveText(t('shared.split.missing', { amount: 'RD$ 200' }))
  await split.getByLabel(t('shared.split.amountOf', { name: 'Pedro Ficticio' })).fill('300')
  await expect(shortfall).toHaveText(t('shared.split.over', { amount: 'RD$ 100' }))
  await expect(done).toBeDisabled()
  await split.getByLabel(t('shared.split.amountOf', { name: 'Pedro Ficticio' })).fill('200')
  await expect(shortfall).toHaveText(t('shared.split.addsUp'))
  await noSidewaysScroll(page, 'split sheet')
  await done.click()
  await expect(split).toHaveCount(0)
  await expect(form.getByTestId('split-summary')).toHaveText(t('shared.add.splitExact'))
  await form.getByRole('button', { name: t('shared.add.save') }).click()
  await expect(form).toHaveCount(0)
  await expect(page.getByTestId('timeline-entry').filter({ hasText: 'Supermercado' })).toContainText( // spanish-data
    t('shared.entry.owe', { amount: 'RD$ 300' }),
  )
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
  await page.goto(`/?month=${FEBRUARY}`)
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
