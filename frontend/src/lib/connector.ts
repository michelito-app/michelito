// The AI connector in hosted mode (src/michelito/hosted/connector_routes.py, mcp_routes.py):
// the consent screen an MCP client (Claude) sends the person to, the connections in Settings and
// the address to paste in Claude. Tokens never reach the interface. Pure helpers apart from the
// calls.
import { useQuery } from '@tanstack/react-query'
import { LOCALE, t } from '@/i18n'
import { request } from '@/lib/api'

export const connectionsKey = ['connector', 'connections'] as const
export const MCP_PATH = '/api/mcp'

export interface ConnectRequest {
  client_name: string
  redirect_host: string
}

export interface Connection {
  id: number
  client_name: string
  created_at: string
  last_used_at: string
}

const DAY = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short', year: 'numeric' })

function day(value: string): string {
  const found = new Date(value)
  return Number.isNaN(found.getTime()) ? '' : DAY.format(found)
}

/** The address to paste in Claude: this server's MCP endpoint. */
export function connectorUrl(origin: string = window.location.origin): string {
  return origin.replace(/\/$/, '') + MCP_PATH
}

/** "Connected on 20 nov. 2026 · last used 23 nov. 2026". */
export function connectionLine(connection: Connection): string {
  return t('connector.connectedOn', { created: day(connection.created_at), used: day(connection.last_used_at) })
}

export function fetchRequest(id: string): Promise<ConnectRequest> {
  return request<ConnectRequest>(`/api/connector/requests/${encodeURIComponent(id)}`)
}

/** Answer the request: where to send the person back (Claude, with a code or a refusal). */
export async function decide(id: string, approve: boolean): Promise<string> {
  const found = await request<{ redirect: string }>(`/api/connector/requests/${encodeURIComponent(id)}`, {
    method: 'POST',
    body: JSON.stringify({ approve }),
  })
  return found.redirect
}

export function useConnections() {
  return useQuery({ queryKey: connectionsKey, queryFn: () => request<Connection[]>('/api/connector/connections') })
}

export function revokeConnection(id: number): Promise<void> {
  return request<void>(`/api/connector/connections/${id}`, { method: 'DELETE' })
}
