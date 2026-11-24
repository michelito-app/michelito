import { type APIRequestContext, expect, request as api, test, type Page, type TestInfo } from '@playwright/test'
import { createHash, randomBytes } from 'node:crypto'
import { codeIn, emailsTo, invite, syntheticPdfs } from './hostedServer'
import { t } from './text'

// Hosted mode, the AI connector: the test plays Claude (registration, the consent screen in the
// browser, the code exchange and MCP calls) with a synthetic account; Claude's callback is
// answered here, so nothing leaves the machine. Desktop and phone (projects `hosted` and
// `hosted-mobile`).
const PDFS = syntheticPdfs()
const CALLBACK = 'https://claude.ai/api/mcp/auth_callback'

async function signInPastTheGate(page: Page, info: TestInfo): Promise<void> {
  const email = `${info.project.name}-connector-${Date.now()}@example.com`
  invite(email)
  await page.goto('/')
  await page.getByRole('button', { name: t('auth.landing.enter') }).click()
  await page.getByLabel(t('auth.signIn.email')).fill(email)
  await page.getByRole('button', { name: t('auth.signIn.sendCode') }).click()
  await expect.poll(() => emailsTo(email).length, { timeout: 10_000 }).toBeGreaterThan(0)
  await page.getByLabel(t('auth.signIn.code')).fill(codeIn(emailsTo(email).at(-1)!))
  await page.getByRole('button', { name: t('auth.signIn.verify'), exact: true }).click()
  await page.locator('input[type="file"]').setInputFiles([PDFS['popular-card']])
  await page.getByRole('button', { name: t('onboarding.result.open') }).click()
  await expect(page.getByRole('navigation', { name: t('shell.nav.label') }).first()).toBeAttached()
}

function pkce(): { verifier: string; challenge: string } {
  const verifier = randomBytes(32).toString('base64url')
  return { verifier, challenge: createHash('sha256').update(verifier).digest('base64url') }
}

type Tool = (name: string, args?: object) => Promise<Record<string, unknown>>

/** Play Claude: register, consent in the person's browser, exchange the code; a tool caller. */
async function connectClaude(page: Page, baseURL: string): Promise<{ claude: APIRequestContext; token: string; tool: Tool }> {
  const claude = await api.newContext({ baseURL }) // no cookies: what Claude's servers send
  const registered = await claude.post('/oauth/register', {
    data: { client_name: 'Claude', redirect_uris: [CALLBACK] },
  })
  expect(registered.status()).toBe(201)
  const { client_id: clientId } = (await registered.json()) as { client_id: string }
  const { verifier, challenge } = pkce()

  // The consent screen, in the person's browser; Claude's callback answered here.
  let back = ''
  await page.route('https://claude.ai/**', async (route) => {
    back = route.request().url()
    await route.fulfill({ status: 200, body: 'ok' })
  })
  const query = new URLSearchParams({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: CALLBACK,
    code_challenge: challenge,
    code_challenge_method: 'S256',
    state: 'e2e',
    resource: `${baseURL}/api/mcp`,
  })
  await page.goto(`/oauth/authorize?${query}`)
  await expect(page.getByRole('heading', { name: t('connector.consent.title', { client: 'Claude' }) })).toBeVisible()
  await expect(page.getByTestId('connect-host')).toContainText('claude.ai')
  await page.getByRole('button', { name: t('connector.consent.allow') }).click()
  await expect.poll(() => back).toContain('code=')
  const code = new URL(back).searchParams.get('code')!

  const tokens = await claude.post('/oauth/token', {
    form: { grant_type: 'authorization_code', code, redirect_uri: CALLBACK, client_id: clientId, code_verifier: verifier },
  })
  expect(tokens.status()).toBe(200)
  const { access_token: token } = (await tokens.json()) as { access_token: string }

  async function tool(name: string, args: object = {}) {
    const answer = await claude.post('/api/mcp', {
      headers: { Authorization: `Bearer ${token}` },
      data: { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } },
    })
    expect(answer.status()).toBe(200)
    const { result } = (await answer.json()) as { result: { content: { text: string }[]; isError?: boolean } }
    expect(result.isError ?? false, result.content[0].text).toBe(false)
    return JSON.parse(result.content[0].text) as Record<string, unknown>
  }
  return { claude, token, tool }
}

/** The ISO day `n` days before today (the server's own today). */
function daysAgo(n: number): string {
  const day = new Date(Date.now() - n * 86_400_000)
  return day.toISOString().slice(0, 10)
}

/** Open the link Claude gives (only its path: the test server's own). */
async function openLink(page: Page, link: unknown) {
  const url = new URL(String(link))
  await page.goto(url.pathname + url.search)
}

test('connect Claude, read, propose and approve the change in Review', async ({ page, baseURL }, info) => {
  await signInPastTheGate(page, info)
  const { claude, token, tool } = await connectClaude(page, baseURL!)

  const listed = (await tool('list_transactions', { kind: 'expense' })).data as {
    items: { fingerprint: string; category_id: number; link: string; merchant: string }[]
  }
  const row = listed.items.find((r) => r.link === '')!
  const categories = (await tool('list_categories')).data as { id: number; kind: string; hidden?: boolean }[]
  const target = categories.find((c) => c.kind === 'expense' && c.id !== row.category_id && !c.hidden)!
  const sent = await tool('propose_category_changes', {
    title: 'Move one expense',
    explanation: 'End to end',
    changes: [{ fingerprint: row.fingerprint, category_id: target.id, scope: 'transaction' }],
  })

  // The person approves it in Review, from the link Claude gives.
  await openLink(page, sent.link)
  const proposal = page.getByTestId('proposal')
  await expect(proposal.getByRole('heading', { name: 'Move one expense' })).toBeVisible()
  await expect(proposal.getByTestId('proposal-item')).toHaveCount(1)
  await proposal.getByRole('button', { name: t('connector.proposals.apply', { count: 1 }) }).click()
  await expect(page.getByTestId('proposals').getByRole('status')).toContainText(
    t('connector.proposals.outcome.applied', { count: 1 }),
  )
  const changed = await page.request.get(`/api/transactions/${row.fingerprint}`)
  expect(((await changed.json()) as { category_id: number }).category_id).toBe(target.id)

  // Settings lists the connection and disconnects it.
  await page.goto('/settings')
  const section = page.locator('#connector')
  await expect(section.getByTestId('connector-url')).toContainText('/api/mcp')
  await expect(section.getByTestId('connector-connections')).toContainText('Claude')
  await section.getByRole('button', { name: t('connector.revoke') }).click()
  await section.getByRole('button', { name: t('connector.revokeYes') }).click()
  await expect(section.getByText(t('connector.none'))).toBeVisible()
  const after = await claude.post('/api/mcp', {
    headers: { Authorization: `Bearer ${token}` },
    data: { jsonrpc: '2.0', id: 1, method: 'ping' },
  })
  expect(after.status()).toBe(401)
  await claude.dispose()
})

test('import cash, pending charges and a statement through Claude, approved in Review', async ({ page, baseURL }, info) => {
  await signInPastTheGate(page, info)
  const { claude, tool } = await connectClaude(page, baseURL!)
  const accounts = (await tool('list_accounts')).data as { key: string; kind: string }[]
  const card = accounts.find((a) => a.kind === 'credit_card')!.key

  // Cash: approved as it comes.
  const cash = await tool('import_cash_entries', {
    title: 'Paper receipts',
    entries: [{ day: '2026-06-03', description: 'MADE UP KIOSK', amount_cents: 15000, currency: 'DOP', direction: 'out' }],
  })
  await openLink(page, cash.link)
  let proposal = page.getByTestId('proposal').filter({ hasText: 'Paper receipts' })
  await expect(proposal.getByTestId('proposal-row')).toHaveCount(1)
  await proposal.getByRole('button', { name: t('connector.proposals.importRows', { count: 1 }) }).click()
  await expect(page.getByTestId('proposals').getByRole('status').first()).toContainText(
    t('connector.proposals.outcome.applied', { count: 1 }),
  )

  // Pending charges of the card, ticked (none repeats a stored transaction).
  const charges = await tool('import_provisional_charges', {
    title: 'From a CSV',
    account: card,
    charges: [
      { day: daysAgo(10), description: 'MADE UP BOOKS', amount_cents: 99000, currency: 'DOP' },
      { day: daysAgo(10), description: 'MADE UP CAFE', amount_cents: 45000, currency: 'DOP' },
    ],
  })
  expect(charges.rows).toBe(2)
  await openLink(page, charges.link)
  proposal = page.getByTestId('proposal').filter({ hasText: 'From a CSV' })
  await expect(proposal.getByTestId('proposal-row')).toHaveCount(2)
  await proposal.getByRole('button', { name: t('connector.proposals.importRows', { count: 2 }) }).click()
  await expect(page.getByTestId('proposals').getByRole('status').first()).toContainText(
    t('connector.proposals.outcome.applied', { count: 2 }),
  )
  const pending = await page.request.get('/api/transactions', {
    params: { month: daysAgo(10).slice(0, 7), provisional: 'true' },
  })
  expect(((await pending.json()) as { items: unknown[] }).items).toHaveLength(2)

  // A whole statement that squares (a card: closing = previous + charges - payments).
  const statement = await tool('import_statement', {
    title: 'July statement',
    account: card,
    period_start: '2026-07-01',
    period_end: '2026-07-31',
    sections: [
      {
        currency: 'DOP',
        previous_balance_cents: 0,
        closing_balance_cents: 30000,
        printed_debits_cents: 30000,
        printed_credits_cents: 0,
        transactions: [{ day: '2026-07-10', description: 'MADE UP GROCER', amount_cents: 30000, direction: 'debit' }],
      },
    ],
  })
  await openLink(page, statement.link)
  proposal = page.getByTestId('proposal').filter({ hasText: 'July statement' })
  await expect(proposal.getByTestId('proposal-statement')).toBeVisible()
  await expect(proposal.getByTestId('proposal-section')).toContainText('DOP')
  await proposal.getByRole('button', { name: t('connector.proposals.saveStatement') }).click()
  await expect(page.getByTestId('proposals').getByRole('status').first()).toContainText(
    t('connector.proposals.statementSaved'),
  )
  const july = await page.request.get('/api/transactions', { params: { month: '2026-07', q: 'MADE UP GROCER' } })
  expect(((await july.json()) as { items: unknown[] }).items).toHaveLength(1)
  await claude.dispose()
})
