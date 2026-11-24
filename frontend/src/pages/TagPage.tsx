import { Plus, Users } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { AddTransactions } from '@/components/tags/AddTransactions'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { formatDop } from '@/lib/money'
import { shortDay } from '@/lib/months'
import {
  useDeleteTag,
  useRenameTag,
  useTag,
  useTagOneOff,
  useTagTarget,
  useUntagTransactions,
} from '@/lib/tagQueries'
import { type Tag, type TagMember, type TagVia, canRemove, spanLabel, targetNote } from '@/lib/tags'
import { cn } from '@/lib/utils'
import { TagTotals } from './TagsPage'

const VIA_LABEL: Record<TagVia, string> = {
  manual: '',
  group: t('tags.detail.viaGroup'),
  loan: t('tags.detail.viaLoan'),
  installment: t('tags.detail.viaInstallment'),
}

/** One tag: its total (the user's own share), the members newest first, by category, and the
 * actions: add transactions, mark all as one-off, rename and delete (a group tag: from its
 * group). */
export function TagPage() {
  const { id = '' } = useParams()
  const tag = useTag(Number(id), id !== '')
  if (tag.isPending) return <Skeleton aria-label={t('tags.detail.loading')} className="h-64 max-w-[960px] rounded-xl" />
  if (tag.error) {
    return <LoadError what={t('tags.detail.loadWhat')} error={tag.error} onRetry={() => void tag.refetch()} />
  }
  return <TagView tag={tag.data} />
}

function TagView({ tag }: { tag: Tag }) {
  const [adding, setAdding] = useState(false)
  const span = spanLabel(tag.first, tag.last)
  return (
    <div className="flex max-w-[960px] flex-col gap-6">
      <TagHeader tag={tag} />
      {span && <p className="-mt-4 text-[13px] text-muted-foreground">{span}</p>}
      <TagTotals tag={tag} />
      <TagActions tag={tag} onAdd={() => setAdding(true)} />
      {adding && <AddTransactions tagId={tag.id} onClose={() => setAdding(false)} />}
      <Targets tag={tag} />
      <Members tag={tag} />
      {tag.by_category.length > 0 && (
        <section aria-label={t('tags.detail.byCategory')} className="flex flex-col gap-2">
          <h2 className="text-lg font-bold tracking-tight">{t('tags.detail.byCategory')}</h2>
          <ul className={cn(PANEL, 'flex flex-col px-5 py-3 text-[13px]')}>
            {tag.by_category.map((row) => (
              <li key={row.category} className="flex justify-between py-1">
                <span>{row.category}</span>
                <span className="tabular-nums">{formatDop(row.amount_cents)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function TagHeader({ tag }: { tag: Tag }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(tag.name)
  const rename = useRenameTag()
  if (editing) {
    return (
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          rename.mutate({ id: tag.id, name: name.trim() }, { onSuccess: () => setEditing(false) })
        }}
      >
        <Input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} className="h-11 max-w-md" />
        <Button type="submit" disabled={name.trim() === '' || rename.isPending} className="h-11 rounded-xl">
          {t('tags.action.rename')}
        </Button>
        {rename.error && (
          <p role="alert" className="w-full text-[13px] text-destructive">
            {rename.error.message}
          </p>
        )}
      </form>
    )
  }
  return (
    <header className="flex flex-wrap items-center gap-3">
      <h1 className="flex items-center gap-2 text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">
        {tag.group_id !== null && <Users size={22} aria-label={t('tags.list.group')} />}
        {tag.name}
      </h1>
      {tag.group_id === null ? (
        <Button type="button" variant="outline" onClick={() => setEditing(true)} className="h-9 rounded-lg">
          {t('tags.action.rename')}
        </Button>
      ) : (
        <Link to={`/shared/${tag.group_id}`} className="text-[13px] font-medium text-primary underline-offset-4 hover:underline">
          {t('tags.detail.openGroup')}
        </Link>
      )}
    </header>
  )
}

function TagActions({ tag, onAdd }: { tag: Tag; onAdd: () => void }) {
  const oneOff = useTagOneOff()
  const remove = useDeleteTag()
  const navigate = useNavigate()
  const markAll = () => {
    if (window.confirm(t('tags.action.oneOffConfirm'))) oneOff.mutate({ id: tag.id, oneOff: true })
  }
  const deleteTag = () => {
    if (window.confirm(t('tags.action.deleteConfirm'))) {
      remove.mutate(tag.id, { onSuccess: () => void navigate('/tags') })
    }
  }
  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" onClick={onAdd} className="h-11 gap-1.5 rounded-xl px-4">
        <Plus size={16} aria-hidden="true" />
        {t('tags.action.add')}
      </Button>
      <Button
        type="button"
        variant="outline"
        disabled={tag.count === 0 || oneOff.isPending}
        onClick={markAll}
        className="h-11 rounded-xl"
      >
        {t('tags.action.oneOff')}
      </Button>
      {tag.group_id === null && (
        <Button type="button" variant="ghost" onClick={deleteTag} className="h-11 rounded-xl text-destructive">
          {t('tags.action.delete')}
        </Button>
      )}
      {oneOff.data && (
        <p role="status" className="w-full text-[13px] text-muted-foreground">
          {t('tags.action.oneOffDone', { count: oneOff.data.changed })}
        </p>
      )}
    </div>
  )
}

function Members({ tag }: { tag: Tag }) {
  const untag = useUntagTransactions()
  if (tag.members.length === 0) {
    return <p className="text-[13px] text-muted-foreground">{t('tags.detail.empty')}</p>
  }
  return (
    <section aria-label={t('tags.detail.members')} className="flex flex-col gap-2">
      <h2 className="text-lg font-bold tracking-tight">{t('tags.detail.members')}</h2>
      <ul className={cn(PANEL, 'flex flex-col px-5 py-2')}>
        {tag.members.map((member) => (
          <MemberRow
            key={member.fingerprint}
            member={member}
            onRemove={() => untag.mutate({ id: tag.id, fingerprints: [member.fingerprint] })}
          />
        ))}
      </ul>
    </section>
  )
}

function MemberRow({ member, onRemove }: { member: TagMember; onRemove: () => void }) {
  return (
    <li className="flex min-h-11 items-center gap-3 border-b border-border/60 py-2 text-[13px] last:border-0">
      <span className="w-14 shrink-0 text-muted-foreground tabular-nums">{shortDay(member.day)}</span>
      <span className="min-w-0 flex-1 truncate">
        {member.description}
        {member.derived && <span className="ml-2 text-[11px] text-muted-foreground">{VIA_LABEL[member.via]}</span>}
      </span>
      <span className="hidden text-muted-foreground sm:inline">{member.category}</span>
      <span className={cn('tabular-nums', !member.counted && 'text-muted-foreground line-through')}>
        {member.amount_dop_cents === null ? '' : formatDop(member.amount_dop_cents)}
      </span>
      {canRemove(member) ? (
        <Button
          type="button"
          variant="ghost"
          onClick={onRemove}
          aria-label={t('tags.detail.removeLabel', { name: member.description })}
          className="h-9 px-2 text-[12px]"
        >
          {t('tags.detail.remove')}
        </Button>
      ) : (
        <span className="w-[58px]" aria-hidden="true" />
      )}
    </li>
  )
}

/** The loans and plans the tag holds as a whole: what is left (or why it adds nothing), and
 * a control to take them out. */
function Targets({ tag }: { tag: Tag }) {
  const target = useTagTarget()
  if (tag.targets.length === 0) return null
  return (
    <section aria-label={t('tags.target.title')} className="flex flex-col gap-2">
      <h2 className="text-lg font-bold tracking-tight">{t('tags.target.title')}</h2>
      <ul className={cn(PANEL, 'flex flex-col px-5 py-2')}>
        {tag.targets.map((item) => (
          <li
            key={`${item.kind}-${item.id}`}
            className="flex min-h-11 items-center gap-3 border-b border-border/60 py-2 text-[13px] last:border-0"
          >
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-medium">{item.name}</span>
              <span className="text-muted-foreground">{targetNote(item)}</span>
            </span>
            <Button
              type="button"
              variant="ghost"
              aria-label={t('tags.target.removeLabel', { name: item.name })}
              onClick={() =>
                target.mutate({
                  id: tag.id,
                  kind: item.kind === 'loan' ? 'loans' : 'installments',
                  targetId: item.id,
                  on: false,
                })
              }
              className="h-9 px-2 text-[12px]"
            >
              {t('tags.detail.remove')}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}
