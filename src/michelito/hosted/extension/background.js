// The extension's worker: links to Michelito with the one-time code and walks the last 12 months
// of the order history when the popup asks (never on its own). It talks only to the person's
// Michelito (MICHELITO) and reads only the order-history pages, in a tab it opens in the
// person's own signed-in browser. It keeps only the token and the last run's counts.
importScripts('walk.js')

const MICHELITO = 'https://michelito.app'
const LINK_URL = `${MICHELITO}/api/extension/link`
const ORDERS_URL = `${MICHELITO}/api/extension/orders`
const PAGES_MAX = 60 // per year: a safety stop
const LOAD_SECONDS = 45
const walk = globalThis.michelitoWalk
let running = false

async function saveRun(run) {
  await chrome.storage.local.set({ run: { ...run, at: new Date().toISOString() } })
}

async function post(url, method, body, token) {
  const headers = { 'Content-Type': 'application/json', 'X-Michelito': '1' }
  if (token) headers.Authorization = `Bearer ${token}`
  return fetch(url, { method, headers, body: JSON.stringify(body), credentials: 'omit' })
}

async function link(code) {
  const answer = await post(LINK_URL, 'POST', { code })
  if (!answer.ok) return { ok: false, error: answer.status === 429 ? 'rate_limited' : 'bad_code' }
  const { token } = await answer.json()
  if (typeof token !== 'string' || !token.startsWith('mchx_')) return { ok: false, error: 'bad_code' }
  await chrome.storage.local.set({ token })
  await chrome.storage.local.remove('run')
  return { ok: true }
}

/** Load an address in the walk's tab and wait until it finished loading. */
function load(tabId, url) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => finish(new Error('timeout')), LOAD_SECONDS * 1000)
    function listener(id, change) {
      if (id === tabId && change.status === 'complete') finish(null)
    }
    function finish(error) {
      clearTimeout(timer)
      chrome.tabs.onUpdated.removeListener(listener)
      if (error) reject(error)
      else resolve()
    }
    chrome.tabs.onUpdated.addListener(listener)
    chrome.tabs.update(tabId, { url }).catch(finish)
  })
}

/** Read the page in the tab, only if it is still an order-history page (not a sign-in). */
async function readTab(tabId) {
  const tab = await chrome.tabs.get(tabId)
  if (!walk.isOrdersPage(tab.url ?? '')) throw new Error('signed_out')
  await chrome.scripting.executeScript({ target: { tabId }, files: ['reader.js'] })
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    // Checked again inside the page: it may have navigated since the check above.
    func: () =>
      location.origin === 'https://www.amazon.com' && location.pathname === '/your-orders/orders'
        ? globalThis.michelitoReader.read(document, location.href)
        : null,
  })
  if (!result?.result) throw new Error('signed_out')
  return result.result
}

async function send(token, orders, totals) {
  for (const batch of walk.batches(walk.payload(orders))) {
    const answer = await post(ORDERS_URL, 'PUT', { orders: batch }, token)
    if (answer.status === 401) {
      await chrome.storage.local.remove('token')
      throw new Error('unlinked')
    }
    if (!answer.ok) throw new Error(answer.status === 429 ? 'rate_limited' : 'server')
    const found = await answer.json()
    totals.orders += found.orders
    totals.withReceipt += found.with_receipt
  }
}

async function walkYear(tabId, start, since, token, totals) {
  let url = start
  for (let page = 0; url && page < PAGES_MAX; page += 1) {
    await load(tabId, url)
    const found = await readTab(tabId)
    const { kept, older } = walk.recent(found.orders, since)
    await send(token, kept, totals)
    totals.pages += 1
    totals.failed += found.failed.length
    await saveRun({ state: 'running', ...totals })
    if (older || !found.next) return
    url = found.next
    await new Promise((resolve) => setTimeout(resolve, walk.pause()))
  }
}

async function lastYear() {
  if (running) return { ok: false, error: 'running' }
  const { token } = await chrome.storage.local.get('token')
  if (!token) return { ok: false, error: 'unlinked' }
  running = true
  const totals = { pages: 0, orders: 0, withReceipt: 0, failed: 0 }
  const today = new Date()
  const since = walk.cutoff(today)
  const [first, ...rest] = walk.startPages(today)
  let tabId = null
  try {
    await saveRun({ state: 'running', ...totals })
    const tab = await chrome.tabs.create({ url: 'about:blank', active: false })
    tabId = tab.id
    for (const start of [first, ...rest]) await walkYear(tabId, start, since, token, totals)
    await saveRun({ state: 'done', ...totals })
    return { ok: true }
  } catch (error) {
    const known = ['signed_out', 'unlinked', 'rate_limited', 'timeout', 'server']
    const reason = known.includes(error?.message) ? error.message : 'failed'
    await saveRun({ state: 'error', error: reason, ...totals })
    return { ok: false, error: reason }
  } finally {
    running = false
    if (tabId !== null) chrome.tabs.remove(tabId).catch(() => {})
  }
}

async function unlink() {
  await chrome.storage.local.remove(['token', 'run'])
  return { ok: true }
}

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  // Only the popup: never a script running in a page (not even this extension's own reader).
  const fromPopup =
    sender.id === chrome.runtime.id && !sender.tab && (sender.url ?? '').startsWith(chrome.runtime.getURL('popup.html'))
  if (!fromPopup || typeof message !== 'object' || message === null) return false
  const actions = {
    link: () => link(String(message.code ?? '').slice(0, 40)),
    walk: () => lastYear(),
    unlink: () => unlink(),
  }
  const action = actions[message.type]
  if (!action) return false
  action().then(reply, () => reply({ ok: false, error: 'failed' }))
  return true // the reply comes later
})
