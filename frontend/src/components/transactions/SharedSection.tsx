import { useId, useState } from 'react'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import type { EditBody, GroupRef, Tx } from '@/lib/api'
import { formatMoney, grossCents, groupLabel } from '@/lib/links'
import { useEditTransaction, useOpenGroups } from '@/lib/queries'
import { GroupPanel } from './GroupPanel'
import {
  Action,
  ConfirmBox,
  Failure,
  FIELD,
  LoadFailure,
  SECTION,
  SECTION_TITLE,
} from './linkParts'
import { SplitForm } from './SplitForm'

interface SharedSectionProps {
  tx: Tx
  onSaved: (tx: Tx) => void
}

/** An expense's Shared section: when it is already in a group, the group's management;
 * otherwise share it in a new group or add it to a group with something pending. */
export function SharedSection({ tx, onSaved }: SharedSectionProps) {
  const ids = useId()
  const edit = useEditTransaction()
  const [confirming, setConfirming] = useState(false)

  function patch(body: EditBody) {
    edit.mutate({ fingerprint: tx.fingerprint, body }, { onSuccess: onSaved })
  }

  if (tx.shared && tx.link === 'shared') {
    return <GroupPanel group={tx.shared} current={tx.fingerprint} />
  }

  if (tx.link === 'shared') {
    // Dormant: still in a group, but no longer a positive expense (it was recategorized): it is
    // not split.
    return (
      <section aria-labelledby={`${ids}-title`} className={SECTION}>
        <h2 id={`${ids}-title`} className={SECTION_TITLE}>
          {t('links.summary.sharedTitle')}
        </h2>
        <p className="text-[13px] text-ink-2">{t('links.share.dormant')}</p>
        {confirming ? (
          <ConfirmBox
            label={t('links.share.stop')}
            confirmLabel={t('links.share.stopConfirm')}
            busy={edit.isPending}
            onConfirm={() => patch({ shared: null })}
            onCancel={() => setConfirming(false)}
          >
            {t('links.share.stopHint')}
          </ConfirmBox>
        ) : (
          <div>
            <Action onClick={() => setConfirming(true)}>{t('links.share.stop')}</Action>
          </div>
        )}
        <Failure error={edit.error} />
      </section>
    )
  }

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        {t('links.share.title')}
      </h2>
      <p className="text-[13px] text-muted-foreground">
        {t('links.share.intro', { amount: formatMoney(grossCents(tx), tx.currency) })}
      </p>
      <ShareStart tx={tx} saving={edit.isPending} onPatch={patch} />
      <Failure error={edit.error} />
    </section>
  )
}

interface ShareStartProps {
  tx: Tx
  saving: boolean
  onPatch: (body: EditBody) => void
}

/** A new group (split and people) or add it to a group with something pending (offering the
 * split of that group's last expense). */
function ShareStart({ tx, saving, onPatch }: ShareStartProps) {
  const ids = useId()
  const [mode, setMode] = useState<'new' | 'join'>('new')
  const [withWhom, setWithWhom] = useState('')
  const [joining, setJoining] = useState<GroupRef | null>(null)
  const groups = useOpenGroups(true)
  const open = groups.data ?? []

  return (
    <div className="flex flex-col gap-3">
      {groups.isError && <LoadFailure what={t('links.what.groups')} error={groups.error} />}
      {open.length > 0 && (
        <div role="tablist" aria-label={t('links.share.how')} className="flex flex-wrap gap-2">
          <Action
            primary={mode === 'new'}
            tab={{ selected: mode === 'new' }}
            onClick={() => setMode('new')}
          >
            {t('links.share.newGroup')}
          </Action>
          <Action
            primary={mode === 'join'}
            tab={{ selected: mode === 'join' }}
            onClick={() => setMode('join')}
          >
            {t('links.share.joinGroup')}
          </Action>
        </div>
      )}
      {mode === 'new' && (
        <SplitForm
          currency={tx.currency}
          amountCents={grossCents(tx)}
          initial={null}
          saving={saving}
          submitLabel={t('links.share.mark')}
          onSave={(split) => onPatch({ shared: { ...split, with_whom: withWhom.trim() || null } })}
        >
          <label className="flex flex-col gap-1 text-[13px] font-semibold text-ink-2">
            {t('links.share.withWhom')}
            <input
              id={`${ids}-with`}
              maxLength={80}
              placeholder={t('links.share.withWhomPlaceholder')}
              value={withWhom}
              onChange={(event) => setWithWhom(event.target.value)}
              className={FIELD}
            />
          </label>
        </SplitForm>
      )}
      {mode === 'join' && joining === null && (
        <ul aria-label={t('links.share.openGroups')} className="flex flex-col gap-2">
          {open.map((group) => (
            <li
              key={group.id}
              className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[13px]"
            >
              <span className="min-w-0 font-semibold break-words">{groupLabel(group)}</span>
              <Action
                label={t('links.share.joinTo', { title: group.title })}
                onClick={() => setJoining(group)}
              >
                {t('links.share.join')}
              </Action>
            </li>
          ))}
        </ul>
      )}
      {mode === 'join' && joining !== null && (
        <JoinForm
          tx={tx}
          group={joining}
          saving={saving}
          onPatch={onPatch}
          onCancel={() => setJoining(null)}
        />
      )}
    </div>
  )
}

interface JoinFormProps extends ShareStartProps {
  group: GroupRef
  onCancel: () => void
}

function JoinForm({ tx, group, saving, onPatch, onCancel }: JoinFormProps) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13px] text-ink-2">
        {tn('links.share.joinQuestion', {
          title: <span className="font-semibold">{group.title}</span>,
        })}
      </p>
      <SplitForm
        currency={tx.currency}
        amountCents={grossCents(tx)}
        initial={group.last_split}
        saving={saving}
        submitLabel={t('links.group.addToGroup')}
        onCancel={onCancel}
        onSave={(split) => onPatch({ shared: { ...split, link_id: group.id } })}
      />
    </div>
  )
}
