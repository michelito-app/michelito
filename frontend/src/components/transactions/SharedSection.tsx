import { useId, useState } from 'react'
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

/** "Compartido" de un gasto: si ya está en un grupo, la gestión del grupo; si no,
 * «Compartir…» en un grupo nuevo o «Sumarlo a un grupo» con pendiente. */
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
    // Dormido: sigue en un grupo, pero ya no es un gasto positivo (se recategorizó): no se
    // reparte.
    return (
      <section aria-labelledby={`${ids}-title`} className={SECTION}>
        <h2 id={`${ids}-title`} className={SECTION_TITLE}>
          Compartido
        </h2>
        <p className="text-[13px] text-ink-2">
          Estaba en un grupo compartido, pero ya no es un gasto: no se reparte. Los reembolsos del
          grupo siguen enlazados.
        </p>
        {confirming ? (
          <ConfirmBox
            label="Dejar de compartir"
            confirmLabel="Sí, dejar de compartir"
            busy={edit.isPending}
            onConfirm={() => patch({ shared: null })}
            onCancel={() => setConfirming(false)}
          >
            Sale del grupo. Si era su último gasto, se borra el grupo: los créditos enlazados
            vuelven a su categoría y se borran los anotados a mano.
          </ConfirmBox>
        ) : (
          <div>
            <Action onClick={() => setConfirming(true)}>Dejar de compartir</Action>
          </div>
        )}
        <Failure error={edit.error} />
      </section>
    )
  }

  return (
    <section aria-labelledby={`${ids}-title`} className={SECTION}>
      <h2 id={`${ids}-title`} className={SECTION_TITLE}>
        Compartir
      </h2>
      <p className="text-[13px] text-muted-foreground">
        Cuenta solo tu parte; lo demás queda como «te deben». Gasto de{' '}
        {formatMoney(grossCents(tx), tx.currency)}.
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

/** Grupo nuevo (reparto y «Con quién») o sumarlo a un grupo con pendiente (se propone el
 * reparto del último gasto de ese grupo). */
function ShareStart({ tx, saving, onPatch }: ShareStartProps) {
  const ids = useId()
  const [mode, setMode] = useState<'new' | 'join'>('new')
  const [withWhom, setWithWhom] = useState('')
  const [joining, setJoining] = useState<GroupRef | null>(null)
  const groups = useOpenGroups(true)
  const open = groups.data ?? []

  return (
    <div className="flex flex-col gap-3">
      {groups.isError && <LoadFailure what="los grupos" error={groups.error} />}
      {open.length > 0 && (
        <div role="tablist" aria-label="Cómo compartir" className="flex flex-wrap gap-2">
          <Action
            primary={mode === 'new'}
            tab={{ selected: mode === 'new' }}
            onClick={() => setMode('new')}
          >
            Grupo nuevo
          </Action>
          <Action
            primary={mode === 'join'}
            tab={{ selected: mode === 'join' }}
            onClick={() => setMode('join')}
          >
            Sumarlo a un grupo
          </Action>
        </div>
      )}
      {mode === 'new' && (
        <SplitForm
          currency={tx.currency}
          amountCents={grossCents(tx)}
          initial={null}
          saving={saving}
          submitLabel="Marcar compartido"
          onSave={(split) => onPatch({ shared: { ...split, with_whom: withWhom.trim() || null } })}
        >
          <label className="flex flex-col gap-1 text-[13px] font-semibold text-ink-2">
            Con quién (opcional)
            <input
              id={`${ids}-with`}
              maxLength={80}
              placeholder="Ana y Luis"
              value={withWhom}
              onChange={(event) => setWithWhom(event.target.value)}
              className={FIELD}
            />
          </label>
        </SplitForm>
      )}
      {mode === 'join' && joining === null && (
        <ul aria-label="Grupos con pendiente" className="flex flex-col gap-2">
          {open.map((group) => (
            <li
              key={group.id}
              className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[13px]"
            >
              <span className="min-w-0 font-semibold break-words">{groupLabel(group)}</span>
              <Action label={`Sumarlo a ${group.title}`} onClick={() => setJoining(group)}>
                Sumarlo
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
        Sumarlo a <span className="font-semibold">{group.title}</span>: ¿cómo se reparte este
        gasto?
      </p>
      <SplitForm
        currency={tx.currency}
        amountCents={grossCents(tx)}
        initial={group.last_split}
        saving={saving}
        submitLabel="Sumar al grupo"
        onCancel={onCancel}
        onSave={(split) => onPatch({ shared: { ...split, link_id: group.id } })}
      />
    </div>
  )
}
