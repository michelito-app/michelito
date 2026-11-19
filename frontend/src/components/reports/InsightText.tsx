import { markdownBlocks } from '@/lib/insights'

/** An analysis's text (simple Markdown) as headings, lists and paragraphs: all plain text, never
 * inserted HTML. */
export function InsightText({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-2 text-sm leading-relaxed break-words text-ink-2">
      {markdownBlocks(text).map((block, index) => {
        if (block.kind === 'heading') {
          return (
            <p key={index} className="font-semibold text-foreground">
              {block.text}
            </p>
          )
        }
        if (block.kind === 'list') {
          return (
            <ul key={index} className="flex list-disc flex-col gap-1 pl-5">
              {block.items.map((item, at) => (
                <li key={at}>{item}</li>
              ))}
            </ul>
          )
        }
        return <p key={index}>{block.text}</p>
      })}
    </div>
  )
}
