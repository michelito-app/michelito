// Merchant receipts on a transaction (pure logic; the rules live on the server:
// src/michelito/analysis/receipt_match.py). A receipt only adds detail: the statement's own
// text is never replaced, it moves under the title.
import { t } from '@/i18n'
import type { Receipt, Tx } from './api'
import { shortDay } from './months'

type WithReceipts = Pick<Tx, 'merchant' | 'receipts'>

/** The receipt that names the transaction: a shipment says what was charged; else the first. */
function leading(tx: WithReceipts): Receipt | null {
  const receipts = tx.receipts ?? []
  return receipts.find((receipt) => receipt.kind === 'shipment') ?? receipts[0] ?? null
}

/** Merchant, item count and the merchant's own summary, as the email says them; null
 * without receipts. */
export function receiptTitle(tx: WithReceipts): string | null {
  const receipt = leading(tx)
  if (!receipt) return null
  const parts = [
    receipt.item_count == null ? '' : t('receipts.items', { count: receipt.item_count }),
    receipt.summary,
  ].filter(Boolean)
  return parts.length ? `${receipt.merchant}: ${parts.join(', ')}` : receipt.merchant
}

/** The statement's merchant, to show under the title a receipt gave; null without receipts. */
export function bankName(tx: WithReceipts): string | null {
  return leading(tx) ? tx.merchant : null
}

/** A link the server gave, only if it is an https address (they are built there from fixed
 * origins; anything else is not shown as a link). */
export function safeLink(address: string): string | null {
  return address.startsWith('https://') ? address : null
}

/** The kind of email and the day it arrived. */
export function receiptHeading(receipt: Receipt): string {
  const kind = receipt.kind === 'order' ? t('receipts.kind.order') : t('receipts.kind.shipment')
  return `${kind} · ${shortDay(receipt.day)}`
}
