// The hosted-mode e2e server (tests/e2e_hosted_server.py) and its outbox: emails are JSON files
// in <dir>/outbox, read here to get the codes. Synthetic addresses only; nothing is sent.
import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

export const HOSTED_PORT = Number(process.env.E2E_HOSTED_PORT ?? 8636)
export const HOSTED_DIR = join(tmpdir(), `michelito-hosted-e2e-${HOSTED_PORT}`)
/** The demo the gate links to ("see sample data"), with its way back to this server. */
export const HOSTED_DEMO_PORT = HOSTED_PORT + 1
export const HOSTED_DEMO_URL = `http://127.0.0.1:${HOSTED_DEMO_PORT}`
/** Synthetic statement PDFs (tests/synthetic_pdf.py), written once per run. */
export const PDF_DIR = `${HOSTED_DIR}-pdfs`
/** The made-up password of the locked synthetic statement. */
export const PDF_PASSWORD = 'made-up-password-123'
const REPO = resolve(import.meta.dirname, '..', '..')
// The CLI runs with its own throwaway data folder setting: it never looks at a real one.
const ENV = { ...process.env, MICHELITO_DATA_DIR: `${HOSTED_DIR}-no-local-data` }

interface Sent {
  to: string
  subject: string
  text: string
}

/** The emails sent to `to`, oldest first. */
export function emailsTo(to: string): Sent[] {
  const folder = join(HOSTED_DIR, 'outbox')
  let names: string[]
  try {
    names = readdirSync(folder).filter((name) => name.endsWith('.json'))
  } catch {
    return []
  }
  // The mailer writes each email to a hidden temporary file and renames it: only complete
  // `<n>.json` files are read (a half-written one, from an older server, is skipped this time).
  const found: Sent[] = []
  for (const name of names.filter((n) => !n.startsWith('.')).sort()) {
    try {
      found.push(JSON.parse(readFileSync(join(folder, name), 'utf8')) as Sent)
    } catch {
      continue
    }
  }
  return found.filter((email) => email.to === to)
}

/** The 6-digit code of the newest email to `to`. */
export function codeIn(email: Sent): string {
  const match = /\b(\d{6})\b/.exec(email.text)
  if (!match) throw new Error('no code in the email')
  return match[1]
}

/** `michelito invite EMAIL` against the e2e server's folder, as on a server. */
export function invite(email: string): void {
  execFileSync(
    'uv',
    [
      'run',
      'michelito',
      'invite',
      email,
      '--data',
      HOSTED_DIR,
      '--mailer',
      'outbox',
      '--public-url',
      `http://127.0.0.1:${HOSTED_PORT}`,
    ],
    { cwd: REPO, env: ENV, stdio: 'pipe' },
  )
}

/** Make the last verification of `email`'s sessions older than the step-up window. */
export function expireStepUp(email: string): void {
  execFileSync(
    'uv',
    [
      'run',
      'python',
      '-m',
      'tests.e2e_hosted_server',
      'expire-step-up',
      '--dir',
      HOSTED_DIR,
      '--email',
      email,
    ],
    { cwd: REPO, env: ENV, stdio: 'pipe' },
  )
}

/** Play the Email Worker: sign and POST one synthetic forwarded email to `to`
 * (tests/e2e_hosted_server.py `deliver`). */
export function deliverEmail(to: string, kind: 'confirmation' | 'locked' | 'stranger'): void {
  execFileSync(
    'uv',
    [
      'run',
      'python',
      '-m',
      'tests.e2e_hosted_server',
      'deliver',
      '--dir',
      HOSTED_DIR,
      '--port',
      String(HOSTED_PORT),
      '--to',
      to,
      '--kind',
      kind,
    ],
    { cwd: REPO, env: ENV, stdio: 'pipe' },
  )
}

/** Write the synthetic statements (made up, from tests/samples.py) and return their paths. */
export function syntheticPdfs(): Record<string, string> {
  execFileSync('uv', ['run', 'python', '-m', 'tests.synthetic_pdf', '--out', PDF_DIR], {
    cwd: REPO,
    env: ENV,
    stdio: 'pipe',
  })
  const names = ['popular-card', 'bhd-card', 'bhd-savings', 'wrong-total', 'other-bank']
  return Object.fromEntries(names.map((name) => [name, join(PDF_DIR, `${name}.pdf`)]))
}
