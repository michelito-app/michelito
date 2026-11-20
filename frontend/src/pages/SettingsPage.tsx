import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Laptop, Smartphone } from 'lucide-react'
import { useState } from 'react'
import { StepUpSheet } from '@/components/hosted/StepUpSheet'
import { LoadError } from '@/components/LoadError'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { LOCALE, t } from '@/i18n'
import { SIGNED_OUT_EVENT } from '@/lib/api'
import {
  type Device,
  deviceLabel,
  fetchDevices,
  fetchMe,
  needsStepUp,
  signOut,
  signOutEverywhere,
} from '@/lib/hosted'

const DAY = new Intl.DateTimeFormat(LOCALE, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})
const PHONES = new Set(['Android', 'iOS', 'iPadOS'])

function signedOut() {
  window.dispatchEvent(new Event(SIGNED_OUT_EVENT))
}

/** Hosted mode only: the account and its devices (sign out this one, or everywhere after a
 * fresh verification). */
export function SettingsPage() {
  const me = useQuery({ queryKey: ['auth', 'me'], queryFn: fetchMe })
  const devices = useQuery({ queryKey: ['auth', 'devices'], queryFn: fetchDevices })
  const client = useQueryClient()
  const [stepUp, setStepUp] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function everywhere() {
    setError(null)
    try {
      await signOutEverywhere()
      signedOut()
    } catch (failure) {
      if (needsStepUp(failure)) setStepUp(true)
      else setError(failure instanceof Error ? failure.message : String(failure))
    }
  }

  async function thisOne() {
    setError(null)
    try {
      await signOut()
      signedOut()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    }
  }

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <h1 className="text-3xl font-bold tracking-tight">{t('auth.settings.title')}</h1>
      <section aria-labelledby="settings-account" className="flex flex-col gap-2">
        <h2 id="settings-account" className="text-lg font-semibold">
          {t('auth.settings.account')}
        </h2>
        {me.data && (
          <p className="text-sm text-ink-2">
            {t('auth.settings.signedInAs', { email: me.data.email })}
          </p>
        )}
      </section>
      <section aria-labelledby="settings-devices" className="flex flex-col gap-3">
        <h2 id="settings-devices" className="text-lg font-semibold">
          {t('auth.devices.title')}
        </h2>
        <p className="text-sm text-muted-foreground">{t('auth.devices.lead')}</p>
        {devices.error ? (
          <LoadError what={t('auth.devices.what')} error={devices.error} onRetry={() => void devices.refetch()} />
        ) : (
          <ul className="flex flex-col gap-2">
            {(devices.data ?? []).map((device) => (
              <DeviceRow key={device.id} device={device} />
            ))}
          </ul>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="outline" className="h-11 px-4" onClick={() => void thisOne()}>
            {t('auth.devices.signOut')}
          </Button>
          <Button variant="destructive" className="h-11 px-4" onClick={() => void everywhere()}>
            {t('auth.devices.signOutEverywhere')}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">{t('auth.devices.everywhereHint')}</p>
      </section>
      {stepUp && me.data && (
        <StepUpSheet
          email={me.data.email}
          onClose={() => setStepUp(false)}
          onVerified={() => {
            setStepUp(false)
            void client.invalidateQueries({ queryKey: ['auth', 'me'] })
            void everywhere()
          }}
        />
      )}
    </div>
  )
}

function DeviceRow({ device }: { device: Device }) {
  const Icon = PHONES.has(device.os) ? Smartphone : Laptop
  const lastSeen = DAY.format(new Date(`${device.last_seen}T00:00:00Z`))
  return (
    <li>
      <Card className="flex flex-row items-center gap-3 px-4 py-3">
        <Icon size={20} aria-hidden="true" className="shrink-0 text-muted-foreground" />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">{deviceLabel(device)}</span>
          <span className="text-xs text-muted-foreground">
            {t('auth.devices.lastSeen', { date: lastSeen })}
          </span>
        </div>
        {device.current && <Badge variant="secondary">{t('auth.devices.thisOne')}</Badge>}
      </Card>
    </li>
  )
}
