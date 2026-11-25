// Merchant receipts on a transaction (pure logic; the rules live on the server:
// src/michelito/analysis/receipt_match.py). A receipt only adds detail: the statement's own
// text is never replaced, it moves under the title.
import { t } from '@/i18n'
import type { Receipt, ReceiptItem, Tx } from './api'
import { formatUsd } from './money'
import { shortDay } from './months'

type WithReceipts = Pick<Tx, 'merchant' | 'receipts'>

/** The receipt that names the transaction: a shipment says what was charged; else the first. */
function leading(tx: WithReceipts): Receipt | null {
  const receipts = tx.receipts ?? []
  return receipts.find((receipt) => receipt.kind === 'shipment') ?? receipts[0] ?? null
}

const TITLE_WORDS = 3 // words of each item name in a transaction's title
const LINE_WORDS = 5 // words of each item name in the order's list
const TITLE_NAMES_MAX = 45 // characters of item names a title lists before "and N more"
// Where a product title stops naming the product and starts listing its specs.
const SPEC_START = /\s[-–|]\s|[,;([]/
const TRAILING_PUNCTUATION = /[\s.:;,!?/&+-]+$/

/** The words that identify a product: its title up to the first spec separator (comma,
 * parenthesis, bracket, spaced dash), at most `words` of them. */
export function shortName(title: string, words: number): string {
  const kept = (text: string) => text.trim().split(/\s+/).slice(0, words).join(' ').replace(TRAILING_PUNCTUATION, '')
  return kept(title.split(SPEC_START)[0]) || kept(title)
}

/** The items under their short names, those sharing one joined: quantities add up (an item
 * without one counts once) and the price stays only when all of them cost the same. */
function grouped(items: ReceiptItem[], words: number): ReceiptItem[] {
  return items.reduce<ReceiptItem[]>((groups, item) => {
    const title = shortName(item.title, words)
    const index = groups.findIndex((group) => group.title === title)
    if (index < 0) return [...groups, { ...item, title }]
    const group = groups[index]
    const joined: ReceiptItem = {
      title,
      quantity: (group.quantity ?? 1) + (item.quantity ?? 1),
      price_cents: group.price_cents === item.price_cents ? group.price_cents : null,
    }
    return groups.map((other, position) => (position === index ? joined : other))
  }, [])
}

function withQuantity(item: ReceiptItem): string {
  return item.quantity && item.quantity > 1 ? `${item.title} (${item.quantity})` : item.title
}

/** The short item names that fit the title ("kettle, mug and 2 more"); the first always does. */
function namedItems(items: ReceiptItem[]): string {
  const names = grouped(items, TITLE_WORDS).map(withQuantity)
  const overflow = names.findIndex(
    (_, index) => index > 0 && names.slice(0, index + 1).join(', ').length > TITLE_NAMES_MAX,
  )
  const shown = overflow < 0 ? names : names.slice(0, overflow)
  const name = shown.join(', ')
  const rest = names.length - shown.length
  return rest ? t('receipts.itemsMore', { name, count: rest }) : name
}

/** The item names the extension sent ("Amazon: kettle and 2 more"); else the merchant, item
 * count and the merchant's own summary, as the email says them; null without receipts. */
export function receiptTitle(tx: WithReceipts): string | null {
  const receipt = leading(tx)
  if (!receipt) return null
  if (receipt.items?.length) return `${receipt.merchant}: ${namedItems(receipt.items)}`
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

/** The order's items as its list shows them: short names, the same one joined. */
export function itemLines(items: ReceiptItem[]): string[] {
  return grouped(items, LINE_WORDS).map(itemLine)
}

/** One item as the detail lists it: "2 × Mug · US$ 12.50" (quantity and price when known). */
export function itemLine(item: ReceiptItem): string {
  const name = item.quantity && item.quantity > 1 ? `${item.quantity} × ${item.title}` : item.title
  return item.price_cents == null ? name : `${name} · ${formatUsd(item.price_cents)}`
}
