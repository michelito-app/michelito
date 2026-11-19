import { useId, useState } from 'react'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import { LoadError } from '@/components/LoadError'
import { ApiError, type CreditRole, type InvestmentRef, type Tx } from '@/lib/api'
import { STATUS_LABELS } from '@/lib/investments'
import { formatMoney, grossCents } from '@/lib/links'
import { useChangeInvestment, useInvestment, useOpenInvestments } from '@/lib/queries'
import { InvestmentPanel } from './InvestmentPanel'
import { Action, Failure, FIELD, LoadFailure, SECTION, SECTION_TITLE } from './linkParts'
import { RoleForm } from './RoleForm'

/** A transaction's Investment section: when it already belongs to one, the investment's
 * management; otherwise a debit can become an investment (new or existing) and a credit can
 * come from one (which, and of what role). */
export function InvestmentSection({ tx }: { tx: Tx }) {
  if (tx.link === 'investment') return <Linked tx={tx} />
  if (tx.can_invest) return <ContributionStart tx={tx} />
  if (tx.can_invest_credit) return <CreditStart tx={tx} />
  return null
}

function Linked({ tx }: { tx: Tx }) {
  const ids = useId()
  const id = tx.investment?.id ?? null
  const query = useInvestment(id)
  const change = useChangeInvestment()
  const missing = query.error instanceof ApiError && query.error.status === 404
  if (query.isError && !missing) {
    return (
      <LoadError what={t('links.what.investment')} error={query.error} onRetry={() => query.refetch()} />
    )
  }
  if (id === null || missing) {
    // Dormant: the investment has no visible contributions any more (a statement changed).
    return (
      <section aria-labelledby={`${ids}-title`} className={SECTION}>
        <h2 id={`${ids}-title`} className={SECTION_TITLE}>
          {t('links.summary.investmentTitle')}
        </h2>
        <p className="text-[13px] text-ink-2">{t('links.investment.dormant')}</p>
        {tx.link_id !== null && (
          <div>
            <Action
              disabled={change.isPending}
              onClick={() =>
                change.mutate({ action: 'remove', id: tx.link_id!, fingerprint: tx.fingerprint })
              }
            >
              {t('links.investment.remove')}
            </Action>
          </div>
        )}
        <Failure error={change.error} />
      </section>
    )
  }
  if (query.data === undefined) {
    return <p className="text-[13px] text-muted-foreground">{t('links.loading')}</p>
  }
  return <InvestmentPanel investment={query.data} current={tx.fingerprint} />
}

/** A debit: a new investment (optional name, and with whom) or added to an existing one. */
function ContributionStart({ tx }: { tx: Tx }) {
  const ids = useId()
  const change = useChangeInvestment()
  const [mode, setMode] = useState<'new' | 'join'>('new')
  const [name, setName] = useState('')
  const [withWhom, setWithWhom] = useState('')
  const open = useOpenInvestments(true)
  const existing = open.data ?? []
  const hint = tx.suggested_investment?.kind === 'possible_contribution' ? tx.suggested_investment : null
  const label = 'flex min-w-0 flex-col gap-1 text-[13px] font-semibold text-ink-2'

  const join = (investment: InvestmentRef) =>
    change.mutate({
      action: 'add',
      id: investment.id,
      fingerprint: tx.fingerprint,
      role: 'contribution',
    })

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        {t('links.investment.isOne')}
      </h2>
      <p className="text-[13px] text-muted-foreground">
        {t('links.investment.intro', { amount: formatMoney(grossCents(tx), tx.currency) })}
      </p>
      {hint && (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-primary/40 px-3 py-2.5">
          <p className="text-[13px] text-ink-2">
            {tn('links.investment.anotherContribution', {
              title: <span className="font-semibold">{hint.title}</span>,
            })}
          </p>
          <div>
            <Action primary disabled={change.isPending} onClick={() => join(hint)}>
              {t('links.investment.anotherContributionYes')}
            </Action>
          </div>
        </div>
      )}
      {open.isError && <LoadFailure what={t('links.what.investments')} error={open.error} />}
      {existing.length > 0 && (
        <div role="tablist" aria-label={t('links.investment.how')} className="flex flex-wrap gap-2">
          <Action
            primary={mode === 'new'}
            tab={{ selected: mode === 'new' }}
            onClick={() => setMode('new')}
          >
            {t('links.investment.new')}
          </Action>
          <Action
            primary={mode === 'join'}
            tab={{ selected: mode === 'join' }}
            onClick={() => setMode('join')}
          >
            {t('links.investment.join')}
          </Action>
        </div>
      )}
      {mode === 'new' && (
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2">
            <label className={label}>
              {t('links.investment.withWhom')}
              <input
                maxLength={80}
                placeholder={t('links.investment.withWhomPlaceholder')}
                value={withWhom}
                onChange={(event) => setWithWhom(event.target.value)}
                className={FIELD}
              />
            </label>
            <label className={label}>
              {t('links.investment.name')}
              <input
                maxLength={80}
                placeholder={t('links.investment.namePlaceholder')}
                value={name}
                onChange={(event) => setName(event.target.value)}
                className={FIELD}
              />
            </label>
          </div>
          <div>
            <Action
              primary
              disabled={change.isPending}
              onClick={() =>
                change.mutate({
                  action: 'create',
                  fingerprint: tx.fingerprint,
                  withWhom: withWhom.trim() || null,
                  name: name.trim() || null,
                })
              }
            >
              {t('links.investment.mark')}
            </Action>
          </div>
        </div>
      )}
      {mode === 'join' && (
        <ul aria-label={t('links.investment.list')} className="flex flex-col gap-2">
          {existing.map((investment) => (
            <li
              key={investment.id}
              className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[13px]"
            >
              <span className="min-w-0 font-semibold break-words">
                {investment.title} · {STATUS_LABELS[investment.status]}
              </span>
              <Action
                label={t('links.investment.addTo', { title: investment.title })}
                disabled={change.isPending}
                onClick={() => join(investment)}
              >
                {t('links.investment.add')}
              </Action>
            </li>
          ))}
        </ul>
      )}
      <Failure error={change.error} />
    </section>
  )
}

/** A credit: which investment it comes from, and its role (return, capital or mixed). */
function CreditStart({ tx }: { tx: Tx }) {
  const ids = useId()
  const change = useChangeInvestment()
  const open = useOpenInvestments(true, true) // written-off ones too
  const existing = open.data ?? []
  const hinted = tx.suggested_investment?.kind === 'possible_return' ? tx.suggested_investment : null
  const [chosen, setChosen] = useState<number | null>(hinted?.id ?? null)
  const picked = chosen ?? existing[0]?.id ?? null
  const amount = Math.abs(grossCents(tx))

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        {t('links.investment.fromOne')}
      </h2>
      {open.isError && <LoadFailure what={t('links.what.investments')} error={open.error} />}
      {hinted && (
        <p className="rounded-lg border border-dashed border-primary/40 px-3 py-2.5 text-[13px] text-ink-2">
          {tn('links.investment.isReturnOf', {
            title: <span className="font-semibold">{hinted.title}</span>,
          })}
        </p>
      )}
      {open.isSuccess && existing.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          {t('links.investment.none')}
        </p>
      ) : (
        <>
          <label className="flex flex-col gap-1 text-[13px] font-semibold text-ink-2">
            {t('links.summary.investmentTitle')}
            <select
              aria-label={t('links.summary.investmentTitle')}
              value={picked ?? ''}
              onChange={(event) => setChosen(Number(event.target.value))}
              className={FIELD}
            >
              {existing.map((investment) => (
                <option key={investment.id} value={investment.id}>
                  {investment.title} · {STATUS_LABELS[investment.status]}
                </option>
              ))}
            </select>
          </label>
          <RoleForm
            amountCents={amount}
            currency={tx.currency}
            saving={change.isPending || picked === null}
            submitLabel={t('links.investment.link')}
            onSave={(body) => {
              if (picked === null) return
              const role: CreditRole = body.role
              change.mutate({
                action: 'add',
                id: picked,
                fingerprint: tx.fingerprint,
                role,
                capitalCents: body.capital_cents,
              })
            }}
          />
        </>
      )}
      <Failure error={change.error} />
    </section>
  )
}
