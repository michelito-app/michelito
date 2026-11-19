import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  LOCAL,
  fetchMode,
  opinionBody,
  opinionProblem,
  productName,
  refFrom,
} from '@/lib/demo'

describe('productName', () => {
  it('usa el nombre de la demo solo en la demo', () => {
    expect(productName(LOCAL)).toBe('Finanzas')
    expect(productName({ modo: 'demo', sesion: true, nombre: 'Michelito' })).toBe('Michelito')
  })
})

describe('refFrom', () => {
  it('acepta un ref corto y limpio', () => {
    expect(refFrom('?ref=foro-1')).toBe('foro-1')
    expect(refFrom('?mes=2026-01&ref=a.b_c')).toBe('a.b_c')
  })
  it('ignora lo ausente o raro', () => {
    expect(refFrom('')).toBeNull()
    expect(refFrom('?ref=<script>')).toBeNull()
    expect(refFrom(`?ref=${'x'.repeat(65)}`)).toBeNull()
  })
})

describe('opinionProblem', () => {
  it('pide texto y un correo con forma de correo', () => {
    expect(opinionProblem('  ', '')).toBe('Escribe tu opinión.')
    expect(opinionProblem('hola', 'no')).toBe('El correo no parece válido.')
    expect(opinionProblem('x'.repeat(2001), '')).toBe('Máximo 2,000 letras.')
    expect(opinionProblem('hola', '')).toBeNull()
    expect(opinionProblem('hola', 'a@example.com')).toBeNull()
  })
})

describe('opinionBody', () => {
  it('agrega el contexto y deja el correo vacío en null', () => {
    const body = opinionBody(' bien ', ' ', { path: '/', width: 390.4, ref: null })
    expect(body).toEqual({
      texto: 'bien',
      correo: null,
      pagina: '/',
      ancho: 390,
      version: null,
      ref: null,
    })
  })
})

describe('fetchMode', () => {
  const answer = (status: number, body: unknown) =>
    vi.fn(async () => new Response(JSON.stringify(body), { status }))

  afterEach(() => vi.unstubAllGlobals())

  it('un servidor sin /api/modo (404) es local', async () => {
    vi.stubGlobal('fetch', answer(404, { detail: 'no existe' }))
    expect(await fetchMode()).toEqual(LOCAL)
  })

  it('otro error no se disfraza de local', async () => {
    vi.stubGlobal('fetch', answer(503, { detail: 'la demo está llena' }))
    await expect(fetchMode()).rejects.toThrow('la demo está llena')
  })
})
