import {
  ArrowLeft,
  ArrowLeftRight,
  ChevronDown,
  ChevronRight,
  History,
  PiggyBank,
  Repeat,
  Search,
  Share2,
  Sprout,
  StickyNote,
  Tag,
  Undo2,
  Vault,
  Zap,
} from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { HistorySection } from '@/components/log/HistorySection'
import { FOCUS } from '@/components/summary/styles'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { Category, Tx } from '@/lib/api'
import { useTxReserve } from '@/lib/budgetQueries'
import { detailPlan, type SheetKind } from '@/lib/detailPlan'
import { categoryLocked, showShared } from '@/lib/links'
import { useTxRecurring } from '@/lib/queries'
import {
  AMOUNT_TONE_CLASS,
  amountLines,
  amountTone,
  dayLabel,
  originText,
} from '@/lib/transactions'
import { cn } from '@/lib/utils'
import { AddExpenseSheet } from '@/components/shared/AddExpenseSheet'
import { DebitPaymentSheet } from '@/components/shared/DebitPaymentSheet'
import { CreditPaymentSheet, SharedTxPanel } from '@/components/shared/TxShared'
import { CashBoxSection } from './CashBoxSection'
import { ExchangeSection } from './ExchangeSection'
import { InvestmentSection } from './InvestmentSection'
import { ProvisionalNote } from './ProvisionalNote'
import { ReceiptBox } from '@/components/receipts/ReceiptBox'
import { bankName, receiptTitle } from '@/lib/receipts'
import { RecurringSection } from './RecurringSection'
import { ReserveSection } from './ReserveSection'
import {
  CategoryField,
  DETAIL_TITLE_ID,
  NoteField,
  OneOffField,
  OneOffHint,
  SaveError,
  SavedStatus,
  ScopeField,
} from './TransactionDetail'
import { type Correction, useCorrection } from './useCorrection'

const SHEET_TITLE: Record<SheetKind, () => string> = {
  category: () => t('transactions.actions.category'),
  note: () => t('transactions.actions.note'),
  oneOff: () => t('transactions.actions.oneOff'),
  shared: () => t('transactions.actions.share'),
  reimbursement: () => t('shared.credit.title'),
  debitPayment: () => t('shared.debit.title'),
  exchange: () => t('transactions.actions.exchange'),
  investment: () => t('transactions.actions.investment'),
  cashBox: () => t('transactions.actions.cashBox'),
  reserve: () => t('transactions.actions.reserve'),
  recurring: () => t('transactions.actions.recurring'),
  history: () => t('transactions.actions.history'),
}

const ICONS: Record<SheetKind, ReactNode> = {
  category: <Tag size={18} aria-hidden="true" />,
  note: <StickyNote size={18} aria-hidden="true" />,
  oneOff: <Zap size={18} aria-hidden="true" />,
  shared: <Share2 size={18} aria-hidden="true" />,
  reimbursement: <Undo2 size={18} aria-hidden="true" />,
  debitPayment: <Undo2 size={18} aria-hidden="true" className="-scale-x-100" />,
  exchange: <ArrowLeftRight size={18} aria-hidden="true" />,
  investment: <Sprout size={18} aria-hidden="true" />,
  cashBox: <Vault size={18} aria-hidden="true" />,
  reserve: <PiggyBank size={18} aria-hidden="true" />,
  recurring: <Repeat size={18} aria-hidden="true" />,
  history: <History size={18} aria-hidden="true" />,
}

interface MobileDetailProps {
  tx: Tx
  categories: Category[]
  inList: boolean
  onSaved: (tx: Tx) => void
  onClose: () => void
  onShowMerchant: (merchant: string) => void
}

/** The phone's transaction detail (full screen): "Back", the amount, merchant, date, account
 * and category (one tap changes it), its links on top with "Open", three quick actions and the
 * rest as a list. Every form opens in a bottom sheet, never inline. */
export function MobileDetail({
  tx,
  categories,
  inList,
  onSaved,
  onClose,
  onShowMerchant,
}: MobileDetailProps) {
  const heading = useRef<HTMLHeadingElement>(null)
  const correction = useCorrection(tx, categories, onSaved)
  const [sheet, setSheet] = useState<SheetKind | null>(null)
  const debit = tx.kind === 'expense' && tx.amount_cents > 0
  const reserveState = useTxReserve(tx.fingerprint, debit)
  const recurringState = useTxRecurring(tx.fingerprint, debit)
  const reserve = debit ? reserveState.data : undefined
  const recurring = debit ? recurringState.data : undefined
  const plan = detailPlan({
    tx,
    reserve: {
      linked: reserve?.reserve?.name ?? null,
      canLink: !!reserve?.can_link,
      // As on a wider screen: a reason only matters when there are reserves to link to.
      reason:
        reserve?.reason && reserve.options.length > 0
          ? t('transactions.reserve.cannotLink', { reason: reserve.reason })
          : '',
    },
    recurring: {
      linked: recurring?.recurring ? recurring.name : null,
      available: !!recurring && !recurring.recurring && recurring.eligible,
    },
  })
  const amount = amountLines(tx)

  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [])

  function close() {
    correction.discard()
    setSheet(null)
  }

  return (
    <div
      className="flex flex-col gap-5"
      onKeyDown={(event) => {
        // Escape inside a sheet belongs to the sheet.
        if (event.key === 'Escape' && sheet === null) onClose()
      }}
    >
      <div className="sticky top-0 z-10 -mx-4 flex items-center border-b border-border bg-card/95 px-2 py-1 backdrop-blur">
        <button
          type="button"
          onClick={onClose}
          className={cn(
            'inline-flex min-h-11 items-center gap-1.5 rounded-xl px-2 text-[15px] font-semibold text-primary',
            FOCUS,
          )}
        >
          <ArrowLeft size={18} aria-hidden="true" />
          {t('transactions.detail.back')}
        </button>
      </div>

      <header className="flex flex-col items-start gap-1.5">
        <span
          className={cn(
            'text-[34px] leading-tight font-bold tracking-[-0.02em] tabular-nums',
            AMOUNT_TONE_CLASS[amountTone(tx)],
          )}
        >
          {amount.main}
        </span>
        <h2
          id={DETAIL_TITLE_ID}
          ref={heading}
          tabIndex={-1}
          className="max-w-full text-[20px] leading-tight font-bold tracking-[-0.01em] break-words outline-none"
        >
          {receiptTitle(tx) ?? tx.merchant}
        </h2>
        {bankName(tx) && (
          <span data-testid="bank-name" className="text-[13px] text-muted-foreground">
            {t('receipts.list.bankName', { name: tx.merchant })}
          </span>
        )}
        <span className="text-[13px] text-muted-foreground">
          {dayLabel(tx.day)} · {tx.account_label}
        </span>
        <span className="text-[13px] text-muted-foreground">{originText(tx)}</span>
        <ProvisionalNote tx={tx} />
        <button
          type="button"
          aria-label={t('transactions.detail.changeCategory', { category: tx.category })}
          onClick={() => setSheet('category')}
          className={cn(
            'mt-1 inline-flex min-h-11 max-w-full items-center gap-1.5 rounded-full border border-border bg-muted px-3.5 text-sm font-semibold text-ink-2',
            FOCUS,
          )}
        >
          <span className="truncate">{tx.category}</span>
          {!categoryLocked(tx) && <ChevronDown size={16} aria-hidden="true" />}
        </button>
        <span className="font-mono text-[12px] break-all text-muted-foreground">
          {tx.description}
        </span>
      </header>

      {!inList && (
        <p className="text-[13px] text-muted-foreground">{t('transactions.detail.notInList')}</p>
      )}
      {correction.savedNote && <SavedStatus note={correction.savedNote} />}

      <ReceiptBox tx={tx} />

      {plan.links.length > 0 && (
        <section aria-label={t('transactions.links.label')} className="flex flex-col gap-2">
          {plan.links.map((line) => (
            <div
              key={line.kind}
              data-testid={`mobile-link-${line.kind}`}
              className="flex items-center gap-3 rounded-xl border border-border bg-card px-3.5 py-2.5"
            >
              <span className="shrink-0 text-muted-foreground">{ICONS[line.kind]}</span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase">
                  {line.title}
                </span>
                <span className="text-[13px] text-ink-2">{line.text}</span>
              </span>
              <Button
                variant="outline"
                aria-label={t('transactions.links.openLabel', { what: line.title })}
                className="h-11 shrink-0 rounded-xl px-3.5 text-sm font-semibold"
                onClick={() => setSheet(line.kind)}
              >
                {t('transactions.links.open')}
              </Button>
            </div>
          ))}
        </section>
      )}

      <div
        role="group"
        aria-label={t('transactions.actions.label')}
        className="grid auto-cols-fr grid-flow-col gap-2"
      >
        <QuickAction icon={ICONS.category} onClick={() => setSheet('category')}>
          {t('transactions.actions.category')}
        </QuickAction>
        <QuickAction icon={ICONS.note} onClick={() => setSheet('note')}>
          {t('transactions.actions.note')}
        </QuickAction>
        {showShared(tx) && (
          <QuickAction icon={ICONS.shared} onClick={() => setSheet('shared')}>
            {t('transactions.actions.share')}
          </QuickAction>
        )}
      </div>
      {tx.note && <p className="text-[13px] break-words text-ink-2">{tx.note}</p>}

      <section aria-labelledby="tx-more-actions" className="flex flex-col">
        <h3
          id="tx-more-actions"
          className="pb-1 text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase"
        >
          {t('transactions.actions.more')}
        </h3>
        <ul className="flex flex-col overflow-hidden rounded-xl border border-border bg-card">
          {plan.actions.map((kind) => (
            <ActionRow key={kind} icon={ICONS[kind]} onClick={() => setSheet(kind)}>
              {SHEET_TITLE[kind]()}
            </ActionRow>
          ))}
          <ActionRow icon={<Search size={18} aria-hidden="true" />} onClick={() => onShowMerchant(tx.merchant)}>
            {t('transactions.actions.merchant')}
          </ActionRow>
        </ul>
        {plan.reserveNote && (
          <p data-testid="reserve-note" className="truncate pt-2 text-[13px] text-muted-foreground">
            {plan.reserveNote}
          </p>
        )}
      </section>

      {/* Sharing an expense not in a group goes straight to "I paid it" with it; a credit not in
          a group can be recorded as a payment received. Both are sheets of their own. */}
      {sheet === 'shared' && tx.ledger === null && (
        <AddExpenseSheet tx={tx} onClose={close} onSaved={() => setSheet(null)} />
      )}
      {sheet === 'reimbursement' && <CreditPaymentSheet tx={tx} onClose={close} />}
      {sheet === 'debitPayment' && <DebitPaymentSheet tx={tx} onClose={close} />}
      {sheet !== null &&
        !(sheet === 'shared' && tx.ledger === null) &&
        sheet !== 'reimbursement' &&
        sheet !== 'debitPayment' && (
        <BottomSheet title={SHEET_TITLE[sheet]()} onClose={close}>
          <SheetBody
            kind={sheet}
            tx={tx}
            correction={correction}
            onSaved={onSaved}
            onDone={() => setSheet(null)}
            onCloseDetail={onClose}
          />
        </BottomSheet>
      )}
    </div>
  )
}

interface QuickActionProps {
  icon: ReactNode
  onClick: () => void
  children: string
}

function QuickAction({ icon, onClick, children }: QuickActionProps) {
  return (
    <button
      type="button"
      aria-haspopup="dialog"
      onClick={onClick}
      className={cn(
        'flex min-h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-xl border border-border bg-card px-2 py-2 text-[13px] font-semibold text-ink-2',
        FOCUS,
      )}
    >
      {icon}
      <span className="max-w-full truncate">{children}</span>
    </button>
  )
}

function ActionRow({ icon, onClick, children }: QuickActionProps) {
  return (
    <li className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={onClick}
        className={cn(
          'flex min-h-12 w-full items-center gap-3 px-3.5 text-left text-sm font-medium text-foreground',
          FOCUS,
          'focus-visible:ring-inset',
        )}
      >
        <span className="shrink-0 text-muted-foreground">{icon}</span>
        <span className="min-w-0 flex-1">{children}</span>
        <ChevronRight size={16} aria-hidden="true" className="shrink-0 text-muted-foreground" />
      </button>
    </li>
  )
}

interface SheetBodyProps {
  kind: SheetKind
  tx: Tx
  correction: Correction
  onSaved: (tx: Tx) => void
  /** Closes the sheet (after saving). */
  onDone: () => void
  onCloseDetail: () => void
}

function SheetBody({ kind, tx, correction, onSaved, onDone, onCloseDetail }: SheetBodyProps) {
  switch (kind) {
    case 'category':
      return (
        <CorrectionSheet correction={correction} onDone={onDone}>
          <CategoryField tx={tx} correction={correction} />
          <ScopeField tx={tx} correction={correction} />
          {tx.corrected && (
            <p className="rounded-[10px] bg-secondary px-3 py-2.5 text-[13px] text-secondary-foreground">
              {t('transactions.detail.corrected', { category: tx.original_category })}
            </p>
          )}
        </CorrectionSheet>
      )
    case 'note':
      return (
        <CorrectionSheet correction={correction} onDone={onDone}>
          <NoteField correction={correction} />
        </CorrectionSheet>
      )
    case 'oneOff':
      return (
        <>
          <CorrectionSheet correction={correction} onDone={onDone}>
            <OneOffField correction={correction} />
          </CorrectionSheet>
          <OneOffHint tx={tx} />
        </>
      )
    case 'shared':
      return <SharedTxPanel tx={tx} />
    case 'reimbursement':
    case 'debitPayment':
      return null
    case 'exchange':
      return <ExchangeSection tx={tx} />
    case 'investment':
      return <InvestmentSection tx={tx} />
    case 'cashBox':
      return <CashBoxSection tx={tx} onSaved={onSaved} onClose={onCloseDetail} />
    case 'reserve':
      return <ReserveSection tx={tx} />
    case 'recurring':
      return <RecurringSection tx={tx} />
    case 'history':
      return <HistorySection fingerprint={tx.fingerprint} />
  }
}

interface CorrectionSheetProps {
  correction: Correction
  onDone: () => void
  children: ReactNode
}

/** A correction field (or several) with its save button; saving closes the sheet. */
function CorrectionSheet({ correction, onDone, children }: CorrectionSheetProps) {
  const { body, edit } = correction
  return (
    <div className="flex flex-col gap-4">
      {children}
      <SaveError correction={correction} />
      <Button
        className="h-11 rounded-xl text-sm font-semibold"
        disabled={body === null || edit.isPending}
        onClick={() => correction.save(onDone)}
      >
        {edit.isPending ? t('transactions.saving') : t('transactions.save')}
      </Button>
    </div>
  )
}
