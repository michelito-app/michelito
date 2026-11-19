import { useQueryClient } from '@tanstack/react-query'
import { FileUp } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { PANEL, WIDGET_ACTION } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { type SampleResult, importSample, isDemo, useMode } from '@/lib/demo'
import { cn } from '@/lib/utils'

/** Importar estados. En la demo el archivo está deshabilitado (nunca se suben estados reales) y
 * se prueba con un estado de ejemplo; en local se importa con `finanzas importar` y la subida
 * desde aquí queda para la fase 2. */
export function ImportPage() {
  const mode = useMode()
  const demo = isDemo(mode)
  const hint = useId()
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">Importar</h1>
      <section aria-label="Subir un estado" className={cn(PANEL, 'flex flex-col gap-3 px-6 py-5')}>
        <label className="flex flex-col gap-2 text-sm font-semibold">
          Estado de cuenta en PDF
          <input
            type="file"
            accept="application/pdf"
            disabled
            aria-describedby={hint}
            className="text-sm font-normal disabled:cursor-not-allowed disabled:opacity-60"
          />
        </label>
        <p id={hint} className="text-[13px] text-muted-foreground">
          {demo
            ? 'En la demo no se suben archivos: tus estados reales nunca salen de tu máquina. Prueba con uno de ejemplo.'
            : 'Por ahora los estados se importan desde la terminal: finanzas importar ARCHIVO.pdf'}
        </p>
      </section>
      {demo && <SampleSection />}
    </div>
  )
}

function SampleSection() {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<SampleResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      const found = await importSample()
      setResult(found)
      await queryClient.invalidateQueries()
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      aria-labelledby="sample-title"
      className={cn(PANEL, 'flex flex-col gap-3 px-6 py-5')}
    >
      <h2 id="sample-title" className="text-[17px] font-[650] tracking-tight">
        Estado de ejemplo
      </h2>
      <p className="text-sm text-ink-2">
        Importa el siguiente corte de la tarjeta inventada, por el mismo camino que un PDF: se
        interpreta, se valida contra sus totales y solo entra si cuadra.
      </p>
      <Button className="h-11 self-start px-4" disabled={busy} onClick={() => void run()}>
        <FileUp size={16} aria-hidden="true" />
        {busy ? 'Importando…' : 'Probar con un estado de ejemplo'}
      </Button>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {result && <SampleOutcome result={result} />}
    </section>
  )
}

function SampleOutcome({ result }: { result: SampleResult }) {
  const first = result.meses[0]
  const last = result.meses[result.meses.length - 1]
  return (
    <div role="status" className="flex flex-col gap-1 rounded-xl bg-muted/60 px-4 py-3 text-sm">
      <p className="font-semibold">
        {result.cuadra
          ? `Cuadra: ${result.transacciones} transacciones nuevas`
          : `No entró (${result.estado}): ${result.detalle ?? 'sin detalle'}`}
      </p>
      <p className="text-ink-2">
        {result.cuenta} · del {result.desde} al {result.hasta}
      </p>
      {result.cuadra && (
        <div className="flex flex-wrap gap-x-4">
          <Link to={`/?mes=${first}`} className={WIDGET_ACTION}>
            Ver «Para revisar»
          </Link>
          <Link to={`/transacciones?mes=${last}`} className={WIDGET_ACTION}>
            Ver las transacciones
          </Link>
        </div>
      )}
    </div>
  )
}
