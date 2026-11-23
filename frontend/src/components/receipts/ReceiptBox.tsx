import { ExternalLink, Mail } from 'lucide-react'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { Receipt, Tx } from '@/lib/api'
import { formatUsd } from '@/lib/money'
import { useDecideReceipt } from '@/lib/queries'
import { itemLine, receiptHeading, safeLink } from '@/lib/receipts'
import { cn } from '@/lib/utils'

const LINK = cn(
  'inline-flex min-h-11 items-center gap-1.5 rounded-[10px] px-2.5 text-[13px] font-semibold text-primary no-underline hover:bg-muted',
  FOCUS,
)

/** In the detail: what the merchant's emails say about this transaction (order number, the
 * merchant's own summary, the amount the email names) with a way to the email and to the order,
 * and "it is not this charge" to take a receipt off. Nothing here changes what counts. */
export function ReceiptBox({ tx }: { tx: Tx }) {
  const decide = useDecideReceipt()
  const receipts = tx.receipts ?? []
  if (!receipts.length) return null
  return (
    <section
      data-testid="receipt-box"
      aria-label={t('receipts.box.title')}
      className="flex flex-col gap-2 rounded-xl border border-[#EFEFEA] bg-[#FAFAF8] px-3.5 py-3"
    >
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase">
        {t('receipts.box.title')}
      </h3>
      <ul className="flex flex-col divide-y divide-[#EFEFEA]">
        {receipts.map((receipt) => (
          <ReceiptLine
            key={receipt.id}
            receipt={receipt}
            busy={decide.isPending}
            onRemove={() =>
              decide.mutate({ receipt_id: receipt.id, fingerprint: tx.fingerprint, linked: false })
            }
          />
        ))}
      </ul>
      {decide.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('receipts.box.saveError', { message: decide.error.message })}
        </p>
      )}
    </section>
  )
}

interface ReceiptLineProps {
  receipt: Receipt
  busy: boolean
  onRemove: () => void
}

function ReceiptLine({ receipt, busy, onRemove }: ReceiptLineProps) {
  const order = receipt.orders[0] ?? ''
  const emailLink = safeLink(receipt.email_link)
  const orderLink = safeLink(receipt.order_link)
  return (
    <li className="flex flex-col gap-1 py-2 first:pt-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold">{receiptHeading(receipt)}</span>
        <span className="text-sm whitespace-nowrap text-ink-2 tabular-nums">
          {amountText(receipt)}
        </span>
      </div>
      {receipt.items?.length ? (
        <ul aria-label={t('receipts.box.items')} data-testid="receipt-items" className="flex flex-col gap-0.5">
          {receipt.items.map((item, index) => (
            <li key={index} className="text-[13px] break-words text-ink-2">
              {itemLine(item)}
            </li>
          ))}
        </ul>
      ) : (
        receipt.summary && <span className="text-[13px] text-ink-2">{receipt.summary}</span>
      )}
      <span className="font-mono text-[12px] break-all text-muted-foreground">
        {receipt.orders.map((number) => t('receipts.box.order', { order: number })).join(' · ')}
      </span>
      <span className="text-[12px] text-muted-foreground">
        {receipt.origin === 'confirmed'
          ? t('receipts.box.confirmed')
          : t('receipts.box.automatic')}
      </span>
      <div className="-mx-2.5 flex flex-wrap items-center gap-x-1">
        {emailLink && (
          <a
            href={emailLink}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={t('receipts.box.openEmailLabel', { merchant: receipt.merchant })}
            className={LINK}
          >
            <Mail size={15} aria-hidden="true" />
            {t('receipts.box.openEmail')}
          </a>
        )}
        {orderLink && (
          <a
            href={orderLink}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={t('receipts.box.openOrderLabel', { order, merchant: receipt.merchant })}
            className={LINK}
          >
            <ExternalLink size={15} aria-hidden="true" />
            {t('receipts.box.openOrder')}
          </a>
        )}
        <button
          type="button"
          disabled={busy}
          aria-label={t('receipts.box.removeLabel', { order })}
          onClick={onRemove}
          className={cn(
            'ml-auto inline-flex min-h-11 items-center rounded-[10px] px-2.5 text-[13px] font-semibold text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-60',
            FOCUS,
          )}
        >
          {t('receipts.box.remove')}
        </button>
      </div>
    </li>
  )
}

/** The amount the email names (US$ for now: the only currency a reader gives). */
function amountText(receipt: Receipt): string {
  return receipt.currency === 'USD' ? formatUsd(receipt.amount_cents) : ''
}
