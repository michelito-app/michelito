import type { ReactNode } from 'react'

/** The title of a part of the loan card. */
export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="text-[13px] font-semibold tracking-[0.04em] text-muted-foreground uppercase">{children}</h3>
}
