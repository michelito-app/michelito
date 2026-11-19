import { describe, expect, it } from 'vitest'
import { FLOW_COLORS, TONE_COLORS } from './colors'
import {
  BUILTIN,
  builtinName,
  canonicalCategory,
  CATEGORY_PALETTE,
  categoryColor,
  categoryGroups,
  choosable,
  colorFor,
  conflictText,
  countText,
  customColors,
  isLinkOnly,
  isNewCategoryOption,
  NEW_CATEGORY,
  NEW_CATEGORY_ACTION,
  NO_COLOR,
  parseKeywords,
  previewText,
  THIRD_PARTY,
} from './categories'

describe('categoryColor', () => {
  it('da los colores del diseño por puesto de gasto y repite al acabarse', () => {
    expect(categoryColor(0)).toBe(CATEGORY_PALETTE[0])
    expect(categoryColor(10)).toBe(CATEGORY_PALETTE[0])
  })
})

describe('colorFor', () => {
  it('usa el puesto de la categoría en el Resumen del mes, como en su tabla', () => {
    const ranking = ['Supermercado', 'Restaurantes']
    expect(colorFor(ranking, 'Restaurantes')).toBe(CATEGORY_PALETTE[1])
    expect(colorFor(ranking, 'Viajes')).toBe(NO_COLOR)
  })
})

describe('categoryGroups', () => {
  const all = [
    { name: 'Supermercado', kind: 'gasto' },
    { name: 'Salario', kind: 'ingreso' },
    { name: 'Restaurantes', kind: 'gasto' },
    { name: 'Entre mis cuentas', kind: 'transferencia' },
  ] as const

  it('agrupa por tipo en el orden Gastos, Ingresos, Transferencias', () => {
    expect(categoryGroups(all)).toEqual([
      { label: 'Gastos', names: ['Supermercado', 'Restaurantes'] },
      { label: 'Ingresos', names: ['Salario'] },
      { label: 'Transferencias', names: ['Entre mis cuentas'] },
    ])
  })

  it('omite los grupos vacíos', () => {
    expect(categoryGroups(all.slice(0, 1))).toEqual([
      { label: 'Gastos', names: ['Supermercado'] },
    ])
  })
})

describe('THIRD_PARTY', () => {
  it('es el nombre de la categoría del servidor y cae en el grupo de transferencias', () => {
    expect(THIRD_PARTY).toBe('Transferencias a terceros')
    const groups = categoryGroups([
      { name: 'Préstamos', kind: 'gasto' },
      { name: THIRD_PARTY, kind: 'transferencia' },
    ])
    expect(groups).toEqual([
      { label: 'Gastos', names: ['Préstamos'] },
      { label: 'Transferencias', names: [THIRD_PARTY] },
    ])
  })
})

describe('canonicalCategory', () => {
  it('da el nombre actual de una categoría renombrada, como `categories.canonical`', () => {
    expect(canonicalCategory('Efectivo y transferencias')).toBe('Efectivo')
    expect(canonicalCategory('Salud')).toBe('Salud')
  })
})

describe('categorías editables', () => {
  it('categoryGroups deja fuera las ocultas, salvo la que se pide conservar', () => {
    const list = [
      { name: 'Supermercado', kind: 'gasto', hidden: false },
      { name: 'Vieja', kind: 'gasto', hidden: true },
    ] as const
    expect(categoryGroups(list)).toEqual([{ label: 'Gastos', names: ['Supermercado'] }])
    expect(categoryGroups(list, 'Vieja')).toEqual([
      { label: 'Gastos', names: ['Supermercado', 'Vieja'] },
    ])
  })

  it('builtinName da el nombre de hoy por la identidad estable', () => {
    const list = [{ name: 'Envíos', builtin_key: 'THIRD_PARTY' }]
    expect(builtinName(list, BUILTIN.thirdParty, THIRD_PARTY)).toBe('Envíos')
    expect(builtinName([], BUILTIN.thirdParty, THIRD_PARTY)).toBe(THIRD_PARTY)
  })

  it('colorFor usa el color elegido antes que el puesto', () => {
    const custom = customColors([
      { name: 'Viajes', color: '#C2702E' },
      { name: 'Salud', color: null },
    ])
    expect(custom).toEqual({ Viajes: '#C2702E' })
    expect(colorFor(['Salud'], 'Viajes', custom)).toBe('#C2702E')
    expect(colorFor(['Salud'], 'Salud', custom)).toBe(CATEGORY_PALETTE[0])
  })

  it('la opción "+ Nueva categoría…" no puede ser el nombre de una categoría', () => {
    // El servidor quita espacios de los bordes y junta los de en medio: este valor no sale.
    expect(NEW_CATEGORY).not.toBe(NEW_CATEGORY.trim().split(/\s+/).join(' '))
    expect(isNewCategoryOption({ dataset: { action: NEW_CATEGORY_ACTION } })).toBe(true)
    expect(isNewCategoryOption({ dataset: {} })).toBe(false)
    expect(isNewCategoryOption(undefined)).toBe(false)
  })

  it('parseKeywords separa por coma o renglón y quita vacías', () => {
    expect(parseKeywords(' taller, ,LAVADO DE AUTO\nGOMERA ')).toEqual([
      'taller',
      'LAVADO DE AUTO',
      'GOMERA',
    ])
  })

  it('textos de la previsualización y de la cuenta del año', () => {
    expect(previewText(3, 'RD$ 1,250', null)).toBe('Esto moverá 3 transacciones (RD$ 1,250)')
    expect(previewText(1, 'RD$ 0', 'US$ 25.00')).toBe(
      'Esto moverá 1 transacción (RD$ 0 y US$ 25.00 sin tasa)',
    )
    expect(previewText(0, 'RD$ 0', null)).toBe('Esto no mueve ninguna transacción')
    expect(conflictText(0)).toBeNull()
    expect(conflictText(2)).toMatch(/^2 transacciones coinciden también/)
    expect(countText(1)).toBe('1 transacción este año')
    expect(countText(0)).toBe('Sin transacciones este año')
  })
})

describe('paleta de categorías', () => {
  // Ninguna categoría puede confundirse con los colores del flujo ni con el azul de antes.
  const RESERVED = [
    ...Object.values(FLOW_COLORS).flatMap((c) => [c.strong, c.light]),
    ...Object.values(TONE_COLORS),
    '#5B7DB8', // azul de ingresos de antes
    '#2F5FA8', // azul de "menos gasto" de antes
  ]

  function distance(a: string, b: string): number {
    const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
    const [x, y] = [rgb(a), rgb(b)]
    return Math.hypot(...x.map((value, i) => value - y[i]))
  }

  it('no usa el verde de ingresos, la terracota, el gris de terceros ni el azul de antes', () => {
    for (const color of CATEGORY_PALETTE) {
      for (const reserved of RESERVED) {
        expect(distance(color.toUpperCase(), reserved.toUpperCase())).toBeGreaterThan(48)
      }
    }
  })

  it('los colores son distintos entre sí', () => {
    expect(new Set(CATEGORY_PALETTE.map((c) => c.toUpperCase())).size).toBe(CATEGORY_PALETTE.length)
  })
})

describe('categorías que solo pone su vínculo', () => {
  it('no se eligen a mano; Rendimientos sí', () => {
    const items = [
      { name: 'Caja fuerte', builtin_key: 'CASH_BOX' },
      { name: 'Inversiones', builtin_key: 'INVESTMENT' },
      { name: 'Devolución de capital', builtin_key: 'INVESTMENT_CAPITAL' },
      { name: 'Rendimientos', builtin_key: 'INVESTMENT_RETURN' },
      { name: 'Mía', builtin_key: null },
    ]
    expect(choosable(items).map((c) => c.name)).toEqual(['Rendimientos', 'Mía'])
    expect(isLinkOnly({ builtin_key: 'CASH_BOX' })).toBe(true)
    expect(isLinkOnly({ builtin_key: null })).toBe(false)
  })
})
