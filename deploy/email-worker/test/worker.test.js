// The Email Worker with a fake `message`, a fake fetch and a fake DNS (node --test, no
// dependencies). Synthetic messages and a throwaway key only; nothing leaves the process.
import assert from 'node:assert/strict'
import { createHmac } from 'node:crypto'
import { test } from 'node:test'
import { cloudflareVerdict, handle, headerFields, isForwardingAddress, settings } from '../worker.js'
import { signer } from '../fixtures/arc.js'

const SECRET = 'made-up-inbound-secret-0123456789abcdef'
const ENV = { INBOUND_SECRET: SECRET, INBOUND_URL: 'https://app.example/api/inbound-email' }
const TOKEN = 'a'.repeat(16) + '2'.repeat(16)
const ADDRESS = `estados.${TOKEN}@michelito.app` // spanish-data
const VERDICT =
  'mx.cloudflare.net; dkim=pass header.d=popularenlinea.com; dmarc=pass header.from=popularenlinea.com'
const GMAIL = 'mx.google.com; dkim=pass header.d=popularenlinea.com'
const BODY_HEADERS = ['From: Bank <statements@bank.example>', 'Subject: Statement']
const CONFIG = settings(ENV)

function rawMessage(headers, body = 'Body text that must never be logged.') {
  return new TextEncoder().encode(`${headers.join('\r\n')}\r\n\r\n${body}\r\n`)
}

function fakeMessage(raw, to = ADDRESS, rawSize = raw.length) {
  return {
    to,
    from: 'forwarder@example.com',
    rawSize,
    raw: new ReadableStream({
      start(controller) {
        controller.enqueue(raw.subarray(0, 10))
        controller.enqueue(raw.subarray(10))
        controller.close()
      },
    }),
    rejected: null,
    setReject(reason) {
      this.rejected = reason
    },
  }
}

function fakeFetch(status) {
  const calls = []
  const fetcher = async (url, init) => {
    calls.push({ url, init })
    return new Response(null, { status })
  }
  return { calls, fetcher }
}

/** Gmail's set (i=1) then Cloudflare's (i=2), both sealed, as a forwarded message has them. */
async function forwarded(arc, extra = []) {
  const lines = await arc.headers([{ aar: GMAIL, sealDomain: 'google.com' }, { aar: VERDICT }])
  return rawMessage([...extra, ...lines, ...BODY_HEADERS])
}

test('only forwarding addresses are accepted', () => {
  assert.ok(isForwardingAddress(ADDRESS, CONFIG))
  assert.ok(isForwardingAddress(ADDRESS.toUpperCase(), CONFIG))
  assert.ok(!isForwardingAddress(ADDRESS.replace('michelito.app', 'other.example'), CONFIG))
  assert.ok(!isForwardingAddress(ADDRESS.replace(/^\w+\./, 'other.'), CONFIG))
  assert.ok(!isForwardingAddress(ADDRESS.replace(TOKEN, 'short'), CONFIG))
})

test('a missing or short secret stops the worker', () => {
  assert.throws(() => settings({}), /INBOUND_SECRET/)
  assert.throws(() => settings({ INBOUND_SECRET: 'short' }), /INBOUND_SECRET/)
})

test('headers are unfolded', () => {
  const raw = rawMessage(['ARC-Seal: i=1; a=rsa-sha256;', '\td=cloudflare.net', ...BODY_HEADERS])
  assert.deepEqual(headerFields(raw)[0], ['arc-seal', 'i=1; a=rsa-sha256; d=cloudflare.net'])
})

test('a sealed Cloudflare set on top gives its verdict', async () => {
  const arc = await signer()
  // The seal over Gmail's set too: Gmail's seal is checked as data, not with Google's key.
  const found = await cloudflareVerdict(await forwarded(arc), CONFIG, arc.resolver)
  assert.equal(found.reason, 'ok')
  assert.equal(found.auth, VERDICT)
  assert.deepEqual(arc.lookups, ['arc-2025._domainkey.cloudflare.net'])
})

test('no Cloudflare set and a forged i=1 on top: no verdict', async () => {
  const forged = rawMessage([`ARC-Authentication-Results: i=1; ${VERDICT}`, ...BODY_HEADERS])
  const arc = await signer()
  assert.equal((await cloudflareVerdict(forged, CONFIG, arc.resolver)).auth, '')
  // A whole forged set (seal included) that no Cloudflare key signed: no verdict either.
  const own = await signer() // the attacker's key, which DNS does not publish
  const lines = await own.headers([{ aar: VERDICT }])
  const unsigned = rawMessage([...lines, ...BODY_HEADERS])
  assert.equal((await cloudflareVerdict(unsigned, CONFIG, arc.resolver)).auth, '')
})

test('every other failed check gives no verdict', async () => {
  const arc = await signer()
  const cases = {
    // A forged Cloudflare verdict below the real one: two of them.
    'several cloudflare verdicts': await forwarded(arc, [`ARC-Authentication-Results: i=1; ${VERDICT}`]),
    // Cloudflare's set is not the newest (someone added i=3 on top).
    'cloudflare is not the newest arc set': rawMessage([
      'ARC-Seal: i=3; a=rsa-sha256; cv=pass; d=evil.example; s=x; b=AAAA',
      'ARC-Message-Signature: i=3; a=rsa-sha256; d=evil.example; s=x; b=AAAA',
      'ARC-Authentication-Results: i=3; mx.evil.example; dkim=pass header.d=popularenlinea.com',
      ...(await arc.headers([{ aar: GMAIL }, { aar: VERDICT }])),
      ...BODY_HEADERS,
    ]),
    'seal not by cloudflare': rawMessage([...(await arc.headers([{ aar: VERDICT, sealDomain: 'evil.example' }])), ...BODY_HEADERS]),
    'seal does not verify': rawMessage([...(await arc.headers([{ aar: VERDICT, sign: false }])), ...BODY_HEADERS]),
    'incomplete arc chain': rawMessage([...(await arc.headers([{ aar: GMAIL }, { aar: VERDICT }])).slice(0, 3), ...BODY_HEADERS]),
  }
  for (const [reason, raw] of Object.entries(cases)) {
    const found = await cloudflareVerdict(raw, CONFIG, arc.resolver)
    assert.equal(found.auth, '', reason)
    assert.equal(found.reason, reason)
  }
  // The verdict itself altered after sealing: the seal no longer verifies.
  const tampered = new TextDecoder()
    .decode(await forwarded(arc))
    .replace('dkim=pass header.d=popularenlinea.com; dmarc', 'dkim=pass header.d=popularenlinea.com ; dmarc=pass; x')
  const found = await cloudflareVerdict(new TextEncoder().encode(tampered), CONFIG, arc.resolver)
  assert.equal(found.auth, '')
  // DNS unavailable: no verdict.
  const offline = await cloudflareVerdict(await forwarded(arc), CONFIG, async () => null)
  assert.equal(offline.auth, '')
})

test('a message is signed with HMAC-SHA256 over timestamp, nonce and body', async () => {
  const arc = await signer()
  const raw = await forwarded(arc)
  const { calls, fetcher } = fakeFetch(202)
  const message = fakeMessage(raw)
  assert.equal(await handle(message, ENV, fetcher, arc.resolver), 'accepted')
  assert.equal(message.rejected, null)
  assert.equal(calls.length, 1)
  const { url, init } = calls[0]
  assert.equal(url, ENV.INBOUND_URL)
  assert.equal(init.method, 'POST')
  const headers = init.headers
  assert.equal(headers['X-Michelito'], '1')
  const expected = createHmac('sha256', SECRET)
    .update(`${headers['X-Michelito-Timestamp']}.${headers['X-Michelito-Nonce']}.`)
    .update(init.body)
    .digest('hex')
  assert.equal(headers['X-Michelito-Signature'], expected)
  // The pre-authentication tag: over timestamp, nonce and the exact body length.
  const preauth = createHmac('sha256', SECRET)
    .update(`pre\0${headers['X-Michelito-Timestamp']}\0${headers['X-Michelito-Nonce']}\0${init.body.length}`)
    .digest('hex')
  assert.equal(headers['X-Michelito-Preauth'], preauth)
  assert.equal(headers['Content-Length'], String(init.body.length))
  assert.match(headers['X-Michelito-Nonce'], /^[A-Za-z0-9_-]{16,64}$/)
  assert.ok(Math.abs(Number(headers['X-Michelito-Timestamp']) - Date.now() / 1000) < 5)
  const payload = JSON.parse(new TextDecoder().decode(init.body))
  assert.equal(payload.recipient, ADDRESS)
  assert.deepEqual(new Uint8Array(Buffer.from(payload.raw, 'base64')), raw)
  assert.equal(payload.auth, VERDICT)
})

test('every request has its own nonce', async () => {
  const { calls, fetcher } = fakeFetch(202)
  const none = async () => null
  await handle(fakeMessage(rawMessage(BODY_HEADERS)), ENV, fetcher, none)
  await handle(fakeMessage(rawMessage(BODY_HEADERS)), ENV, fetcher, none)
  const [a, b] = calls.map((c) => c.init.headers['X-Michelito-Nonce'])
  assert.notEqual(a, b)
  // Without a verdict the message still goes (the app quarantines it).
  assert.equal(JSON.parse(new TextDecoder().decode(calls[0].init.body)).auth, '')
})

test('the size cap rejects before reading, and while reading', async () => {
  const raw = rawMessage(BODY_HEADERS, 'x'.repeat(2000))
  const env = { ...ENV, MAX_BYTES: '1000' }
  const { calls, fetcher } = fakeFetch(202)
  const declared = fakeMessage(raw)
  assert.equal(await handle(declared, env, fetcher), 'rejected')
  assert.equal(declared.rejected, 'Message too large')
  const lying = fakeMessage(raw, ADDRESS, 10)
  assert.equal(await handle(lying, env, fetcher), 'rejected')
  assert.equal(lying.rejected, 'Message too large')
  assert.equal(calls.length, 0)
})

test('an unknown recipient is rejected without calling the app', async () => {
  const { calls, fetcher } = fakeFetch(202)
  const message = fakeMessage(rawMessage(BODY_HEADERS), 'someone@michelito.app')
  assert.equal(await handle(message, ENV, fetcher), 'rejected')
  assert.equal(message.rejected, 'Unknown address')
  assert.equal(calls.length, 0)
})

test('the app decides: 404 rejects for good, 5xx and 429 throw so the sender retries', async () => {
  const none = async () => null
  for (const status of [404, 413, 422]) {
    const message = fakeMessage(rawMessage(BODY_HEADERS))
    assert.equal(await handle(message, ENV, fakeFetch(status).fetcher, none), 'rejected')
    assert.ok(message.rejected)
  }
  for (const status of [409, 429, 500, 503]) {
    const message = fakeMessage(rawMessage(BODY_HEADERS))
    await assert.rejects(handle(message, ENV, fakeFetch(status).fetcher, none), /retry/)
    assert.equal(message.rejected, null)
  }
})

test('the DNS lookup goes over DNS-over-HTTPS when no resolver is given', async () => {
  const arc = await signer()
  const record = await arc.resolver('arc-2025._domainkey.cloudflare.net')
  const urls = []
  const fetcher = async (url) => {
    urls.push(String(url))
    if (String(url).startsWith('https://cloudflare-dns.com/')) {
      const data = `"${record.slice(0, 40)}" "${record.slice(40)}"`
      return new Response(JSON.stringify({ Answer: [{ type: 16, data }] }), { status: 200 })
    }
    return new Response(null, { status: 202 })
  }
  assert.equal(await handle(fakeMessage(await forwarded(arc)), ENV, fetcher), 'accepted')
  assert.ok(urls[0].includes('name=arc-2025._domainkey.cloudflare.net'))
})

test('nothing about the message is logged', async (t) => {
  const lines = []
  t.mock.method(console, 'log', (...args) => lines.push(args.join(' ')))
  const arc = await signer()
  await handle(fakeMessage(await forwarded(arc)), { ...ENV, DIAGNOSE: '1' }, fakeFetch(202).fetcher, arc.resolver)
  const logged = lines.join('\n')
  assert.ok(logged.includes('header names: arc-seal'))
  assert.ok(logged.includes('verdict: ok'))
  for (const secret of [TOKEN, 'popularenlinea', 'Statement', 'never be logged', SECRET]) {
    assert.ok(!logged.includes(secret), secret)
  }
})
