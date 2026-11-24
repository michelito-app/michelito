import { useId, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { t } from '@/i18n'
import { useCreateTag, useTags } from '@/lib/tagQueries'
import { findTag } from '@/lib/tags'

interface TagPickerProps {
  /** What the button says ("Tag…", "Add tag"). */
  label: string
  /** Ids already applied: not offered again. */
  exclude?: ReadonlySet<number>
  busy?: boolean
  onPick: (tagId: number) => void
}

/** Choose a manual tag by typing its name (suggestions from the list) or create it on the way. */
export function TagPicker({ label, exclude, busy, onPick }: TagPickerProps) {
  const [name, setName] = useState('')
  const list = useId()
  const tags = useTags()
  const create = useCreateTag()
  const options = (tags.data ?? []).filter((tag) => tag.group_id === null && !exclude?.has(tag.id))
  const submit = () => {
    const text = name.trim()
    if (text === '') return
    const found = findTag(options, text)
    if (found) {
      onPick(found.id)
      setName('')
      return
    }
    create.mutate(text, {
      onSuccess: (made) => {
        onPick(made.id)
        setName('')
      },
    })
  }
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-2">
        <Input
          aria-label={t('tags.chip.pick')}
          placeholder={t('tags.chip.pick')}
          list={list}
          value={name}
          maxLength={80}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              submit()
            }
          }}
          className="h-11 min-w-0 flex-[1_1_200px]"
        />
        <datalist id={list}>
          {options.map((tag) => (
            <option key={tag.id} value={tag.name} />
          ))}
        </datalist>
        <Button
          type="button"
          variant="outline"
          disabled={name.trim() === '' || busy || create.isPending}
          onClick={submit}
          className="h-11 rounded-xl"
        >
          {label}
        </Button>
      </div>
      {create.error && (
        <p role="alert" className="text-[13px] text-destructive">
          {create.error.message}
        </p>
      )}
    </div>
  )
}
