// The popup: paste the code from Michelito's Settings, then "Last 12 months". It only talks to
// the extension's own worker; the worker does the linking, browsing and sending.
const STALE_MS = 2 * 60 * 1000 // a "running" state this old was cut short (the worker stopped)
const message = (key, ...values) => chrome.i18n.getMessage(key, values.map(String))
const $ = (id) => document.getElementById(id)

function translate() {
  for (const element of document.querySelectorAll('[data-i18n]')) {
    element.textContent = message(element.dataset.i18n)
  }
  document.documentElement.lang = chrome.i18n.getUILanguage().startsWith('es') ? 'es' : 'en'
}

function say(text, isError = false) {
  const status = $('status')
  status.textContent = text
  status.classList.toggle('error', isError)
}

function errorText(reason) {
  return message(`error_${reason}`) || message('error_failed')
}

function describe(run) {
  if (!run) return say('')
  const age = Date.now() - Date.parse(run.at)
  if (run.state === 'running' && age > STALE_MS) return say(message('interrupted'), true)
  if (run.state === 'running') return say(message('running', run.pages + 1))
  if (run.state === 'error') return say(errorText(run.error), true)
  const lines = [message('done', run.orders, run.withReceipt)]
  if (run.failed) lines.push(message('doneFailed', run.failed))
  say(lines.join(' '))
}

async function render() {
  const { token, run } = await chrome.storage.local.get(['token', 'run'])
  $('unlinked').hidden = Boolean(token)
  $('linked').hidden = !token
  const busy = run?.state === 'running' && Date.now() - Date.parse(run.at) <= STALE_MS
  $('walk-button').disabled = busy
  describe(run)
}

async function ask(type, extra = {}) {
  try {
    return await chrome.runtime.sendMessage({ type, ...extra })
  } catch {
    return { ok: false, error: 'failed' }
  }
}

$('link-form').addEventListener('submit', async (event) => {
  event.preventDefault()
  const button = $('link-button')
  button.disabled = true
  button.textContent = message('linking')
  const answer = await ask('link', { code: $('code').value })
  button.disabled = false
  button.textContent = message('linkAction')
  if (!answer?.ok) return say(errorText(answer?.error), true)
  $('code').value = ''
  await render()
})

$('walk-button').addEventListener('click', () => {
  $('walk-button').disabled = true
  void ask('walk') // the worker saves its progress; the popup may close meanwhile
})

$('unlink-button').addEventListener('click', async () => {
  await ask('unlink')
  await render()
})

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local') void render()
})

translate()
void render()
