import { Skeleton } from '@/components/ui/skeleton'
import { Link } from 'react-router'
import { t } from '@/i18n'
import { type Selection, transactionsHref } from '@/lib/accountFilter'
import { latest, txHref } from '@/lib/home'
import { shortDay } from '@/lib/months'
import { useTransactions } from '@/lib/queries'
import { AMOUNT_TONE_CLASS, amountLines, amountTone, type ListFilters } from '@/lib/transactions'
import { cn } from '@/lib/utils'
import { Card, ROW_LINK } from './Card'
import { CardError } from './CardError'

interface LatestCardProps {
  month: string
  selection: Selection
}

/** «Latest transactions»: the month's five newest, each opening its own detail; the title
 * opens the month's list. */
export function LatestCard({ month, selection }: LatestCardProps) {
  const filters: ListFilters = {
    accounts: selection,
    category: null,
    q: '',
    kind: null,
    shared: null,
    provisional: false,
  }
  const list = useTransactions(month, filters)
  const rows = list.data ? latest(list.data.items) : []
  return (
    <Card
      id="latest"
      title={t('home.latest.title')}
      titleHref={transactionsHref({ month }, selection)}
    >
      {list.isPending ? (
        <Skeleton className="h-[200px] rounded-xl" />
      ) : list.isError ? (
        <CardError what={t('home.what.latest')} error={list.error} onRetry={() => list.refetch()} />
      ) : rows.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('home.latest.none')}</p>
      ) : (
        <ul className="-my-1 flex flex-col">
          {rows.map((tx) => {
            const amount = amountLines(tx)
            return (
              <li key={tx.fingerprint}>
                <Link to={txHref(tx, selection)} className={ROW_LINK}>
                  <span className="flex min-w-0 flex-1 flex-col py-1.5">
                    <span className="truncate text-[14px] font-medium">{tx.merchant}</span>
                    <span className="truncate text-[12px] text-muted-foreground">
                      {shortDay(tx.day)} · {tx.category}
                    </span>
                  </span>
                  <span
                    className={cn(
                      'shrink-0 text-[14px] font-semibold whitespace-nowrap tabular-nums',
                      AMOUNT_TONE_CLASS[amountTone(tx)],
                    )}
                  >
                    {amount.main}
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
