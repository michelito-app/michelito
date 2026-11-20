import { useState } from 'react'
import { Link } from 'react-router'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import { BANK_SENDERS, useForwarding } from '@/lib/forwarding'
import { cn } from '@/lib/utils'

const FILTER = BANK_SENDERS.join(' OR ')

/** One screen: how to forward only the banks' emails from Gmail (a filter, never everything),
 * and that Gmail's confirmation code shows up in Settings for the person to use. */
export function ForwardingGuidePage() {
  const forwarding = useForwarding()
  const [copied, setCopied] = useState(false)
  const address = forwarding.data?.address

  async function copy() {
    try {
      await navigator.clipboard.writeText(FILTER)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <Link to="/settings#automate" className={cn('min-h-11 self-start text-sm font-semibold text-primary', FOCUS)}>
        {t('forwarding.guide.back')}
      </Link>
      <h1 className="text-3xl font-bold tracking-tight">{t('forwarding.guide.title')}</h1>
      {address && (
        <p data-forwarding-address className={cn(PANEL, 'break-all px-4 py-3 font-mono text-[15px]')}>
          {address}
        </p>
      )}
      <ol className="flex list-decimal flex-col gap-3 pl-5 text-sm leading-relaxed text-ink-2">
        <li>{t('forwarding.guide.step1')}</li>
        <li>{t('forwarding.guide.step2')}</li>
        <li>{t('forwarding.guide.step3')}</li>
        <li>{t('forwarding.guide.step4')}</li>
        <li className="flex flex-col gap-2">
          {t('forwarding.guide.step5')}
          <code className={cn(PANEL, 'break-all px-3 py-2 font-mono text-[13px] text-foreground')}>{FILTER}</code>
          <Button variant="outline" className="h-11 self-start px-4" onClick={() => void copy()}>
            {copied ? t('forwarding.address.copied') : t('forwarding.guide.copySenders')}
          </Button>
        </li>
        <li>{t('forwarding.guide.step6')}</li>
      </ol>
      <p className="text-sm text-muted-foreground">{t('forwarding.guide.done')}</p>
    </div>
  )
}
