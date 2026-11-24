import { expect, request as api, test, type Page, type TestInfo } from '@playwright/test'
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

test('connect Claude, read, propose and approve the change in Review', async ({ page, baseURL }, info) => {
  await signInPastTheGate(page, info)
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
    expect(result.isError ?? false).toBe(false)
    return JSON.parse(result.content[0].text) as Record<string, unknown>
  }

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
  await page.goto(new URL(String(sent.link)).pathname + new URL(String(sent.link)).search)
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
