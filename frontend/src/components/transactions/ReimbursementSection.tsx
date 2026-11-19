import { useId, useState } from 'react'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import type { GroupCandidate, Tx } from '@/lib/api'
import { expenseCount, groupLabel, linkedLabel } from '@/lib/links'
import { useChangeGroup, useReimbursementCandidates, useUnlinkCredit } from '@/lib/queries'
import { Action, Failure, LoadFailure, SECTION, SECTION_TITLE } from './linkParts'

interface ReimbursementSectionProps {
  tx: Tx
}

/** A credit: which shared group it reimburses, the suggestion and the group picker. */
export function ReimbursementSection({ tx }: ReimbursementSectionProps) {
  const ids = useId()
  const change = useChangeGroup()
  const unlink = useUnlinkCredit()
  const unlinked = tx.link !== 'reimbursement'
  const candidates = useReimbursementCandidates(tx.fingerprint, unlinked)
  const of = tx.reimbursement_of
  const suggested = tx.suggested_group

  function link(id: number) {
    change.mutate({ action: 'add-credit', id, credit: tx.fingerprint })
  }

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        {t('links.summary.reimbursementTitle')}
      </h2>
      {tx.link === 'reimbursement' ? (
        <>
          <p className="text-[13px] text-ink-2">
            {tx.shared ? (
              tn('links.reimbursement.of', {
                what: <span className="font-semibold">{tx.shared.title}</span>,
              })
            ) : of ? (
              tn('links.reimbursement.of', {
                what: <span className="font-semibold">{linkedLabel(of)}</span>,
              })
            ) : (
              t('links.reimbursement.gone')
            )}
          </p>
          <div>
            <Action disabled={unlink.isPending} onClick={() => unlink.mutate(tx.fingerprint)}>
              {t('links.reimbursement.unlink')}
            </Action>
          </div>
        </>
      ) : (
        <>
          {suggested && (
            <div className="flex flex-col gap-2 rounded-lg border border-dashed border-primary/40 px-3 py-2.5">
              <p className="text-[13px] text-ink-2">
                {tn('links.shortcut.reimbursement', {
                  what: <span className="font-semibold">{suggested.title}</span>,
                })}
              </p>
              <div className="flex flex-wrap gap-2">
                <Action primary disabled={change.isPending} onClick={() => link(suggested.id)}>
                  {t('links.shortcut.link')}
                </Action>
              </div>
            </div>
          )}
          <div className="flex flex-col gap-2">
            <h3 className="text-[13px] font-semibold text-ink-2">
              {t('links.reimbursement.pick')}
            </h3>
            {candidates.isError ? (
              <LoadFailure what={t('links.what.groups')} error={candidates.error} />
            ) : candidates.isPending ? (
              <p className="text-[13px] text-muted-foreground">{t('links.searching')}</p>
            ) : (candidates.data?.groups ?? []).length === 0 ? (
              <p className="text-[13px] text-muted-foreground">
                {t('links.reimbursement.noGroups')}
              </p>
            ) : (
              <GroupPicker
                groups={candidates.data?.groups ?? []}
                disabled={change.isPending}
                onPick={link}
              />
            )}
          </div>
        </>
      )}
      <Failure error={change.error ?? unlink.error} />
    </section>
  )
}

interface GroupPickerProps {
  groups: GroupCandidate[]
  disabled: boolean
  onPick: (id: number) => void
}

/** The groups the server marked (their pending amount covers the credit) and the rest behind
 * "see more". */
function GroupPicker({ groups, disabled, onPick }: GroupPickerProps) {
  const [expanded, setExpanded] = useState(false)
  const primary = groups.filter((g) => g.primary)
  const more = groups.filter((g) => !g.primary)
  const shown = expanded ? groups : primary
  return (
    <div className="flex flex-col gap-2">
      {shown.length === 0 && (
        <p className="text-[13px] text-muted-foreground">
          {t('links.noFullMatch')}
        </p>
      )}
      <ul aria-label={t('links.reimbursement.groups')} className="flex flex-col gap-2">
        {shown.map((group) => (
          <li
            key={group.id}
            className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[13px]"
          >
            <span className="flex min-w-0 flex-col">
              <span className="font-semibold break-words">{groupLabel(group)}</span>
              <span className="text-muted-foreground">{expenseCount(group.expense_count)}</span>
            </span>
            <Action
              label={t('links.reimbursement.linkTo', { title: group.title })}
              disabled={disabled}
              onClick={() => onPick(group.id)}
            >
              {t('links.link')}
            </Action>
          </li>
        ))}
      </ul>
      {more.length > 0 && (
        <div>
          <Action onClick={() => setExpanded((v) => !v)}>
            {expanded ? t('links.seeLess') : t('links.seeMore', { count: more.length })}
          </Action>
        </div>
      )}
    </div>
  )
}
