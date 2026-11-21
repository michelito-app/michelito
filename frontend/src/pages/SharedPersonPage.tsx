import { useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { LoadError } from '@/components/LoadError'
import { Avatar, BackButton, MenuButton, PageTitle } from '@/components/shared/parts'
import { LIST_CARD, ROW_BUTTON, TONE_CLASS } from '@/components/shared/styles'
import { PaymentSheet } from '@/components/shared/PaymentSheet'
import { PersonMenu } from '@/components/shared/PersonMenu'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { ApiError } from '@/lib/api'
import { approxText, balanceTone, groupBalanceText, leftoverText, personBalanceText } from '@/lib/ledger'
import { groupPath } from '@/lib/links'
import type { Person } from '@/lib/sharedApi'
import { useGroup, usePerson } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'

/** A person across groups (`/shared/people/<id>`): the balance, the per-group breakdown,
 * "Record payment" and "⋯" (rename, merge, aliases). */
export function SharedPersonPage() {
  const { id = '' } = useParams()
  const query = usePerson(Number(id))
  const navigate = useNavigate()
  const location = useLocation()
  const [menu, setMenu] = useState(false)
  const [paying, setPaying] = useState(false)

  if (query.isPending) {
    return (
      <div aria-busy="true" aria-label={t('shared.loading')} className="flex flex-col gap-5">
        <BackButton fallback="/shared" />
        <Skeleton className="h-40 rounded-2xl" />
      </div>
    )
  }
  if (query.isError) {
    const missing = query.error instanceof ApiError && query.error.status === 404
    return (
      <div className="flex flex-col gap-4">
        <BackButton fallback="/shared" />
        {missing ? (
          <p className={cn(PANEL, 'px-6 py-10 text-center text-sm')}>{t('shared.person.notFound')}</p>
        ) : (
          <LoadError what={t('shared.load')} error={query.error} onRetry={() => query.refetch()} />
        )}
      </div>
    )
  }
  const person = query.data
  const tone = balanceTone(person.balance)
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div className="flex items-center justify-between gap-2">
        <BackButton fallback="/shared" />
        <MenuButton label={t('shared.menuOf', { name: person.name })} onClick={() => setMenu(true)} />
      </div>
      <header className="flex items-center gap-3">
        <Avatar name={person.name} />
        <div className="flex min-w-0 flex-col">
          <PageTitle key={person.id}>{person.name}</PageTitle>
          <p data-testid="person-balance" className={cn('text-[15px] font-semibold', TONE_CLASS[tone])}>
            {personBalanceText(person.balance)}
          </p>
          {person.total && (
            <p data-testid="person-total" className="text-[13px] text-muted-foreground">
              {approxText(person.total)}
            </p>
          )}
        </div>
      </header>
      {person.groups.length > 0 && (
        <button
          type="button"
          aria-haspopup="dialog"
          onClick={() => setPaying(true)}
          className={cn(
            'inline-flex min-h-11 items-center justify-center self-start rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/85',
            FOCUS,
          )}
        >
          {t('shared.person.recordPayment')}
        </button>
      )}
      <section aria-labelledby="person-groups" className="flex flex-col gap-2">
        <h2 id="person-groups" className="text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase">
          {t('shared.person.groups')}
        </h2>
        <ul className={LIST_CARD}>
          {person.groups.map((row) => (
            <li key={row.group_id}>
              <button
                type="button"
                onClick={() =>
                  navigate(groupPath(row.group_id), {
                    state: { from: `${location.pathname}${location.search}` },
                  })
                }
                className={ROW_BUTTON}
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-[15px] font-semibold">{row.group_name}</span>
                  {(row.written_off || row.archived) && (
                    <span className="text-[13px] text-muted-foreground">
                      {row.written_off ? t('shared.person.writtenOff') : t('shared.groups.archived')}
                    </span>
                  )}
                  {row.leftover.length > 0 && (
                    <span data-testid="person-leftover" className="text-[13px] text-muted-foreground">
                      {leftoverText(row.leftover, true)}
                    </span>
                  )}
                </span>
                <span className={cn('shrink-0 text-sm font-semibold', TONE_CLASS[balanceTone(row.balance)])}>
                  {groupBalanceText(row.balance)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      {menu && <PersonMenu person={person} onClose={() => setMenu(false)} />}
      {paying && <PersonPayment person={person} onClose={() => setPaying(false)} />}
    </div>
  )
}

/** "Record payment" from a person: in their only group with a balance, or after choosing one. */
function PersonPayment({ person, onClose }: { person: Person; onClose: () => void }) {
  const owing = person.groups.filter((g) => !g.archived && balanceTone(g.balance) !== 'settled')
  const [chosen, setChosen] = useState<number | null>(
    owing.length === 1 ? owing[0].group_id : person.groups.length === 1 ? person.groups[0].group_id : null,
  )
  const group = useGroup(chosen)
  if (chosen === null) {
    return (
      <BottomSheet title={t('shared.person.chooseGroup')} onClose={onClose}>
        <ul className={LIST_CARD}>
          {person.groups.map((row) => (
            <li key={row.group_id}>
              <button type="button" onClick={() => setChosen(row.group_id)} className={ROW_BUTTON}>
                <span className="min-w-0 flex-1 truncate text-sm font-semibold">{row.group_name}</span>
                <span className="shrink-0 text-sm text-muted-foreground">{groupBalanceText(row.balance)}</span>
              </button>
            </li>
          ))}
        </ul>
      </BottomSheet>
    )
  }
  if (!group.data) return null
  return <PaymentSheet group={group.data} personId={person.id} onClose={onClose} />
}
