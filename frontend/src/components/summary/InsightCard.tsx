import { useState } from 'react'
import { Link } from 'react-router'
import { ClaudeButton } from '@/components/claude/ClaudeButton'
import { InsightText } from '@/components/reports/InsightText'
import type { Selection } from '@/lib/accountFilter'
import type { Insight } from '@/lib/api'
import { analyzeCommand, STALE_NOTE, savedText } from '@/lib/insights'
import { monthTitle } from '@/lib/months'
import { cn } from '@/lib/utils'
import { FOCUS } from './styles'

/** «Análisis» (pestaña de «Lectura del mes»): el análisis guardado del mes (Claude Code). Se
 * edita en Reportes. */
export function InsightBody({ insight }: { insight: Insight }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13px] text-muted-foreground">
        {savedText(insight)}
        {insight.stale && <span className="font-semibold text-up"> · {STALE_NOTE}</span>}
        {' · '}
        <Link to="/reportes" className={cn('rounded-sm font-semibold text-primary', FOCUS)}>
          Editar en Reportes
        </Link>
      </p>
      <InsightText text={insight.text} />
    </div>
  )
}

/** Sin nada que leer: el comando para pedir el análisis del mes, con un botón para copiarlo, y
 * «Copiar para Claude». */
export function NoReading({ month, selection }: { month: string; selection: Selection }) {
  const [copied, setCopied] = useState(false)
  const command = analyzeCommand(month)

  async function copy() {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
    } catch {
      setCopied(false) // sin portapapeles: el comando sigue a la vista para copiarlo a mano
    }
  }

  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
      <span>Aún no hay lectura de este mes ·</span>
      <button
        type="button"
        onClick={copy}
        aria-label={`Copiar el comando ${command}`}
        className={cn(
          'relative rounded-sm font-semibold text-primary hover:text-secondary-foreground',
          'before:absolute before:-inset-x-1 before:-inset-y-3 before:content-[""]',
          FOCUS,
        )}
      >
        {copied ? 'Copiado' : 'copiar'}
      </button>
      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12px] text-foreground">
        {command}
      </code>
      <ClaudeButton month={month} label={monthTitle(month)} selection={selection} className="ml-auto" />
    </p>
  )
}
