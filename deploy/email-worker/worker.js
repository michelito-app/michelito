// Michelito's Cloudflare Email Worker: receives the mail forwarded to <prefix>.<token>@<domain>
// (Email Routing's catch-all sends it here) and hands it to the hosted app.
//
// For every message it:
// 1. accepts only recipients shaped like a forwarding address (anything else is rejected);
// 2. enforces a size cap (MAX_BYTES, 10 MB by default) before reading the message;
// 3. takes Cloudflare's own authentication verdict, and **fails closed** (no verdict, so the app
//    quarantines the message) unless all of this holds (`cloudflareVerdict`):
//    - exactly one ARC-Authentication-Results names AUTH_SERV (mx.cloudflare.net);
//    - its instance (i=) is the highest of every ARC-Seal, ARC-Message-Signature and
//      ARC-Authentication-Results in the message, and that instance has exactly one of each;
//    - the ARC-Seal of that instance has d=SEAL_DOMAIN (cloudflare.net) and no cv=fail;
//    - with ARC_VERIFY=1 (the default), that seal's signature verifies (RFC 8617: over every ARC
//      set from i=1 up, relaxed header canonicalization), with the public key published in DNS
//      (`<s>._domainkey.<d>` TXT, read over DNS-over-HTTPS), rsa-sha256 or ed25519-sha256.
//    A sender can write any header into a message, including a whole fake ARC set naming
//    Cloudflare, but cannot sign it with Cloudflare's key. The hosted app reads nothing else
//    as proof (see src/michelito/hosted/inbox.py);
// 4. POSTs {"recipient", "raw" (base64), "auth"} to INBOUND_URL, signed with
//    HMAC-SHA256(INBOUND_SECRET, "<timestamp>.<nonce>." + body) in X-Michelito-Signature, with
//    X-Michelito-Timestamp (Unix seconds) and X-Michelito-Nonce (random), plus
//    X-Michelito-Preauth = HMAC-SHA256(INBOUND_SECRET, "pre\0<timestamp>\0<nonce>\0<length>"),
//    which the app checks before reading any of the body (with the body's exact length). The
//    app refuses a tag or signature that does not match, a time more than 5 minutes off, a body
//    of another length and a repeated nonce.
//
// The answer decides the message's fate: 2xx accepted; 404/413/422 rejected for good (the
// sender gets a bounce: unknown address, too large, malformed); anything else (429, 5xx, a
// network error) throws, so Email Routing reports a temporary failure and the sending server
// retries later.
//
// It logs only outcomes and, with DIAGNOSE=1, the *names* of the first headers and why a verdict
// was not passed on (never a value, an address, a subject or a body). No build step, no
// dependencies: deploy this file as is.

const DEFAULTS = {
  INBOUND_URL: 'https://michelito.app/api/inbound-email',
  DOMAIN: 'michelito.app',
  PREFIX: 'estados', // spanish-data
  MAX_BYTES: String(10 * 1024 * 1024),
  AUTH_SERV: 'mx.cloudflare.net',
  SEAL_DOMAIN: 'cloudflare.net',
  ARC_VERIFY: '1',
  DOH_URL: 'https://cloudflare-dns.com/dns-query',
}
const TOKEN = /^[a-z2-7]{32}$/
const REJECT = new Map([
  [404, 'Unknown address'],
  [413, 'Message too large'],
  [422, 'Message not accepted'],
])
const MAX_HEADER = 8000
const MAX_INSTANCE = 50 // RFC 8617: at most 50 ARC sets
const AAR = 'arc-authentication-results'
const AMS = 'arc-message-signature'
const SEAL = 'arc-seal'

export function settings(env = {}) {
  const value = (name) => String(env[name] ?? DEFAULTS[name] ?? '').trim()
  const secret = value('INBOUND_SECRET')
  if (secret.length < 32) throw new Error('INBOUND_SECRET is missing or shorter than 32 characters')
  return {
    url: value('INBOUND_URL'),
    domain: value('DOMAIN').toLowerCase(),
    prefix: value('PREFIX').toLowerCase(),
    maxBytes: Number(value('MAX_BYTES')),
    authServ: value('AUTH_SERV').toLowerCase(),
    sealDomain: value('SEAL_DOMAIN').toLowerCase(),
    verify: value('ARC_VERIFY') !== '0',
    doh: value('DOH_URL'),
    secret,
    diagnose: value('DIAGNOSE') === '1',
  }
}

/** Whether `recipient` is `<prefix>.<token>@<domain>` (lowercase). */
export function isForwardingAddress(recipient, config) {
  const text = String(recipient).trim().toLowerCase()
  const at = text.lastIndexOf('@')
  if (at < 0 || text.slice(at + 1) !== config.domain) return false
  const local = text.slice(0, at)
  const dot = local.indexOf('.')
  return dot > 0 && local.slice(0, dot) === config.prefix && TOKEN.test(local.slice(dot + 1))
}

/** The message's bytes, or null once it grows past `limit`. */
export async function readAll(stream, limit) {
  const reader = stream.getReader()
  const chunks = []
  let size = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    size += value.byteLength
    if (size > limit) {
      await reader.cancel()
      return null
    }
    chunks.push(value)
  }
  const out = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) {
    out.set(chunk, offset)
    offset += chunk.byteLength
  }
  return out
}

/** The header block's fields in order, unfolded: [name (lowercase), value]. */
export function headerFields(raw) {
  let text = ''
  const limit = Math.min(raw.length, 256 * 1024)
  for (let i = 0; i < limit; i += 1) text += String.fromCharCode(raw[i])
  const end = text.search(/\r?\n\r?\n/)
  const block = end < 0 ? text : text.slice(0, end)
  const fields = []
  for (const line of block.split(/\r?\n/)) {
    if (/^[ \t]/.test(line) && fields.length) {
      fields[fields.length - 1][1] += ` ${line.trim()}`
      continue
    }
    const colon = line.indexOf(':')
    if (colon <= 0) continue
    fields.push([line.slice(0, colon).trim().toLowerCase(), line.slice(colon + 1).trim()])
  }
  return fields
}

/** A tag list (`k=v; k=v`) as a Map; null if malformed or a tag repeats. */
export function tagList(value) {
  const tags = new Map()
  for (const part of value.split(';')) {
    if (!part.trim()) continue
    const equal = part.indexOf('=')
    if (equal <= 0) return null
    const name = part.slice(0, equal).trim().toLowerCase()
    if (tags.has(name)) return null
    tags.set(name, part.slice(equal + 1).trim())
  }
  return tags
}

function instanceOf(value) {
  const found = /^\s*i\s*=\s*(\d{1,2})\s*(;|$)/i.exec(value)
  if (!found) return null
  const number = Number(found[1])
  return number >= 1 && number <= MAX_INSTANCE ? number : null
}

/** RFC 6376 "relaxed" header canonicalization of one (unfolded) field. */
function relaxed(name, value) {
  return `${name}:${value.replace(/[ \t]+/g, ' ').trim()}`
}

function base64Bytes(text) {
  const clean = text.replace(/\s+/g, '')
  const binary = atob(clean)
  const out = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i)
  return out
}

/** The TXT record of `name` over DNS-over-HTTPS (null on any failure). */
export function dohResolver(config, fetcher = fetch) {
  return async (name) => {
    try {
      const url = `${config.doh}?name=${encodeURIComponent(name)}&type=TXT`
      const answer = await fetcher(url, { headers: { accept: 'application/dns-json' } })
      if (!answer.ok) return null
      const data = await answer.json()
      const records = (data.Answer ?? []).filter((item) => item.type === 16)
      if (records.length !== 1) return null
      return records[0].data.replace(/"\s*"/g, '').replace(/^"|"$/g, '')
    } catch {
      return null
    }
  }
}

/** Whether the ARC-Seal of instance `top` verifies over the ARC sets 1..top. */
async function sealVerifies(sets, top, seal, resolver) {
  const algorithm = (seal.tags.get('a') ?? '').toLowerCase()
  const selector = seal.tags.get('s') ?? ''
  const domain = seal.tags.get('d') ?? ''
  const signature = seal.tags.get('b') ?? ''
  if (!selector || !signature || !/^[a-z0-9._-]+$/i.test(selector)) return false
  const record = await resolver(`${selector}._domainkey.${domain}`)
  const key = record === null ? null : tagList(record)
  const published = key?.get('p') ?? ''
  if (!published) return false
  const lines = []
  for (let i = 1; i <= top; i += 1) {
    const set = sets.get(i)
    for (const name of [AAR, AMS, SEAL]) {
      const [field] = set[name]
      if (name === SEAL && i === top) {
        // The seal being checked: its b= value emptied, and no CRLF after it.
        const emptied = field.value.replace(/(^|;)(\s*b\s*=)[^;]*/i, '$1$2')
        lines.push(relaxed(name, emptied))
      } else {
        lines.push(`${relaxed(name, field.value)}\r\n`)
      }
    }
  }
  const data = new TextEncoder().encode(lines.join(''))
  try {
    if (algorithm === 'rsa-sha256' && (key.get('k') ?? 'rsa').toLowerCase() === 'rsa') {
      const imported = await crypto.subtle.importKey(
        'spki',
        base64Bytes(published),
        { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
        false,
        ['verify'],
      )
      return await crypto.subtle.verify('RSASSA-PKCS1-v1_5', imported, base64Bytes(signature), data)
    }
    if (algorithm === 'ed25519-sha256' && (key.get('k') ?? '').toLowerCase() === 'ed25519') {
      const imported = await crypto.subtle.importKey('raw', base64Bytes(published), { name: 'Ed25519' }, false, ['verify'])
      const digest = await crypto.subtle.digest('SHA-256', data)
      return await crypto.subtle.verify('Ed25519', imported, base64Bytes(signature), digest)
    }
  } catch {
    return false
  }
  return false
}

/** Cloudflare's ARC-Authentication-Results value (without its `i=N;`), or "" with the reason
 * (`why`) when any check fails. See the top of this file. */
export async function cloudflareVerdict(raw, config, resolver) {
  const why = (reason) => ({ auth: '', reason })
  const sets = new Map()
  const sealedBy = []
  for (const [name, value] of headerFields(raw)) {
    if (![AAR, AMS, SEAL].includes(name)) continue
    if (value.length > MAX_HEADER) return why('arc header too long')
    const number = instanceOf(name === AAR ? value : `i=${tagList(value)?.get('i') ?? ''}`)
    if (number === null) return why('arc instance unreadable')
    const set = sets.get(number) ?? { [AAR]: [], [AMS]: [], [SEAL]: [] }
    const field = { value, tags: name === AAR ? null : tagList(value) }
    if (name !== AAR && field.tags === null) return why('arc tags unreadable')
    set[name].push(field)
    sets.set(number, set)
    if (name === AAR) {
      const rest = value.replace(/^\s*i\s*=\s*\d+\s*;\s*/i, '')
      const id = rest.split(';', 1)[0].trim().split(/\s+/, 1)[0].toLowerCase()
      if (id === config.authServ) sealedBy.push({ number, rest })
    }
  }
  if (sealedBy.length !== 1) return why(sealedBy.length ? 'several cloudflare verdicts' : 'no cloudflare verdict')
  const top = Math.max(...sets.keys())
  const [mine] = sealedBy
  if (mine.number !== top) return why('cloudflare is not the newest arc set')
  for (let i = 1; i <= top; i += 1) {
    const set = sets.get(i)
    if (!set || set[AAR].length !== 1 || set[AMS].length !== 1 || set[SEAL].length !== 1) {
      return why('incomplete arc chain')
    }
  }
  const [seal] = sets.get(top)[SEAL]
  if ((seal.tags.get('d') ?? '').toLowerCase() !== config.sealDomain) return why('seal not by cloudflare')
  if ((seal.tags.get('cv') ?? '').toLowerCase() === 'fail') return why('arc chain failed')
  if (config.verify && !(await sealVerifies(sets, top, seal, resolver))) return why('seal does not verify')
  return { auth: mine.rest, reason: 'ok' }
}

function base64(bytes) {
  let text = ''
  const step = 0x8000
  for (let i = 0; i < bytes.length; i += step) {
    text += String.fromCharCode(...bytes.subarray(i, i + step))
  }
  return btoa(text)
}

function hex(buffer) {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

function nonce() {
  const bytes = crypto.getRandomValues(new Uint8Array(18))
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_')
}

/** The signed request for one message: { body (bytes), headers }. */
export async function signedRequest(config, recipient, raw, auth, now = Date.now()) {
  const encoder = new TextEncoder()
  const body = encoder.encode(JSON.stringify({ recipient, raw: base64(raw), auth }))
  const timestamp = String(Math.floor(now / 1000))
  const chosen = nonce()
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(config.secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  )
  const prefix = encoder.encode(`${timestamp}.${chosen}.`)
  const message = new Uint8Array(prefix.length + body.length)
  message.set(prefix)
  message.set(body, prefix.length)
  const signature = hex(await crypto.subtle.sign('HMAC', key, message))
  // Checked before the app reads any of the body (only the Worker can make it): the app gives
  // a read slot only to a request with a valid one, and reads exactly this many bytes.
  const preauth = encoder.encode(`pre\0${timestamp}\0${chosen}\0${body.length}`)
  const tag = hex(await crypto.subtle.sign('HMAC', key, preauth))
  return {
    body,
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': String(body.length),
      'X-Michelito': '1',
      'X-Michelito-Timestamp': timestamp,
      'X-Michelito-Nonce': chosen,
      'X-Michelito-Signature': signature,
      'X-Michelito-Preauth': tag,
    },
  }
}

/** Handle one message (`fetcher`: the global fetch, `resolver`: the DNS TXT lookup; both
 * replaceable in tests). */
export async function handle(message, env, fetcher = fetch, resolver = null) {
  const config = settings(env)
  const recipient = String(message.to).trim().toLowerCase()
  if (!isForwardingAddress(recipient, config)) {
    console.log('rejected: not a forwarding address')
    message.setReject('Unknown address')
    return 'rejected'
  }
  if (Number(message.rawSize) > config.maxBytes) {
    console.log('rejected: too large')
    message.setReject('Message too large')
    return 'rejected'
  }
  const raw = await readAll(message.raw, config.maxBytes)
  if (raw === null) {
    console.log('rejected: too large')
    message.setReject('Message too large')
    return 'rejected'
  }
  if (config.diagnose) {
    console.log(`header names: ${headerFields(raw).slice(0, 15).map(([name]) => name).join(', ')}`)
  }
  const verdict = await cloudflareVerdict(raw, config, resolver ?? dohResolver(config, fetcher))
  if (config.diagnose) console.log(`verdict: ${verdict.reason}`)
  const request = await signedRequest(config, recipient, raw, verdict.auth)
  const answer = await fetcher(config.url, { method: 'POST', ...request })
  if (answer.status >= 200 && answer.status < 300) {
    console.log(`accepted (verdict ${verdict.auth ? 'present' : 'missing'})`)
    return 'accepted'
  }
  const reason = REJECT.get(answer.status)
  if (reason) {
    console.log(`rejected: ${answer.status}`)
    message.setReject(reason)
    return 'rejected'
  }
  throw new Error(`the hosted app answered ${answer.status}; Email Routing will retry`)
}

export default {
  async email(message, env) {
    await handle(message, env)
  },
}
