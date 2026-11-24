import { Plus, Tags, Users } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { formatDop } from '@/lib/money'
import { useCreateTag, useTags } from '@/lib/tagQueries'
import { type TagSummary, spanLabel } from '@/lib/tags'
import { cn } from '@/lib/utils'

const NEW_TAG_INPUT = 'new-tag-name'

/** "Tags": every tag with what it has spent; a new one opens its page to fill it. */
export function TagsPage() {
  return (
    <div className="flex max-w-[960px] flex-col gap-6">
      <header className="flex min-w-0 flex-col gap-1">
        <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">
          {t('tags.page.title')}
        </h1>
        <p className="text-[13px] text-muted-foreground">{t('tags.page.subtitle')}</p>
      </header>
      <NewTag />
      <TagList />
    </div>
  )
}

function NewTag() {
  const [name, setName] = useState('')
  const create = useCreateTag()
  const navigate = useNavigate()
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim() === '') return
    create.mutate(name.trim(), {
      onSuccess: (made) => {
        setName('')
        void navigate(`/tags/${made.id}`)
      },
    })
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2" aria-label={t('tags.new.label')}>
      <label className="flex min-w-[240px] flex-1 flex-col gap-1 text-[13px] font-medium">
        {t('tags.new.label')}
        <Input
          id={NEW_TAG_INPUT}
          value={name}
          maxLength={80}
          placeholder={t('tags.new.placeholder')}
          onChange={(event) => setName(event.target.value)}
          className="h-11"
        />
      </label>
      <Button type="submit" disabled={create.isPending || name.trim() === ''} className="h-11 gap-1.5 rounded-xl px-4">
        <Plus size={16} aria-hidden="true" />
        {t('tags.new.create')}
      </Button>
      {create.error && (
        <p role="alert" className="w-full text-[13px] text-destructive">
          {create.error.message}
        </p>
      )}
    </form>
  )
}

function TagList() {
  const tags = useTags()
  if (tags.isPending) {
    return (
      <div aria-busy="true" aria-label={t('tags.page.loading')} className="grid gap-3 md:grid-cols-2">
        {[0, 1].map((i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
    )
  }
  if (tags.error) {
    return <LoadError what={t('tags.page.loadWhat')} error={tags.error} onRetry={() => void tags.refetch()} />
  }
  if (tags.data.length === 0) {
    return (
      <EmptyState
        icon={<Tags size={48} aria-hidden="true" />}
        title={t('tags.empty.title')}
        text={t('tags.empty.hint')}
        action={{ label: t('tags.new.label'), onClick: () => document.getElementById(NEW_TAG_INPUT)?.focus() }}
      />
    )
  }
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {tags.data.map((tag) => (
        <li key={tag.id}>
          <TagCard tag={tag} />
        </li>
      ))}
    </ul>
  )
}

export function TagTotals({ tag }: { tag: TagSummary }) {
  return (
    <p className="text-[13px] text-muted-foreground">
      <span className="font-semibold text-foreground tabular-nums">
        {t('tags.summary.spent', { amount: formatDop(tag.spent_cents) })}
      </span>
      {tag.still_to_pay_cents > 0 && (
        <> · {t('tags.summary.stillToPay', { amount: formatDop(tag.still_to_pay_cents) })}</>
      )}
      {' · '}
      {t('tags.summary.count', { count: tag.count })}
      {tag.unconverted > 0 && <> · {t('tags.summary.unconverted', { count: tag.unconverted })}</>}
    </p>
  )
}

function TagCard({ tag }: { tag: TagSummary }) {
  const span = spanLabel(tag.first, tag.last)
  return (
    <Link
      to={`/tags/${tag.id}`}
      aria-label={t('tags.list.open', { name: tag.name })}
      className={cn(PANEL, 'flex flex-col gap-1.5 px-5 py-4 transition-colors hover:bg-accent/40')}
    >
      <span className="flex items-center gap-2 text-[15px] font-semibold">
        {tag.group_id !== null && <Users size={15} aria-label={t('tags.list.group')} />}
        {tag.name}
      </span>
      {span && <span className="text-[12px] text-muted-foreground">{span}</span>}
      <TagTotals tag={tag} />
    </Link>
  )
}
