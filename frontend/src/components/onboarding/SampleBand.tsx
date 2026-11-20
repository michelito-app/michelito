import { ArrowLeft } from 'lucide-react'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { cn } from '@/lib/utils'

/** The demo reached from the hosted gate: a fixed band in its own color, always on top (on the
 * phone too, so it never meets the bottom bar), that cannot be closed. It is shown because
 * `/api/mode` says this is the demo with a way back (`return_url`), never by a guess of a
 * component, so sample data cannot render without it. */
export function SampleBand({ returnUrl }: { returnUrl: string }) {
  return (
    <div
      role="region"
      aria-label={t('onboarding.band.label')}
      data-sample-band=""
      className="sticky top-0 z-50 flex min-h-11 w-full flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-foreground px-4 py-1.5 text-sm text-background"
    >
      <span className="font-semibold">{t('onboarding.band.text')}</span>
      <span aria-hidden="true">·</span>
      <a
        href={returnUrl}
        className={cn('inline-flex min-h-11 items-center gap-1.5 font-semibold underline', FOCUS)}
      >
        <ArrowLeft size={16} aria-hidden="true" />
        {t('onboarding.band.back')}
      </a>
    </div>
  )
}
