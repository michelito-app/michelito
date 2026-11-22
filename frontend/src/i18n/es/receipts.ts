// Spanish UI text: merchant receipts. Keys start with "receipts.".
import type { Catalog } from '../index'

export const receipts = {
  'receipts.items': {
    one: '{count} artículo',
    other: '{count} artículos',
  },
  'receipts.kind.order': 'Pedido',
  'receipts.kind.shipment': 'Envío',
  'receipts.box.title': 'Según el correo del comercio',
  'receipts.box.order': 'Pedido {order}',
  'receipts.box.automatic': 'Vinculado solo',
  'receipts.box.confirmed': 'Vinculado por ti',
  'receipts.box.openEmail': 'Ver correo',
  'receipts.box.openEmailLabel': 'Ver el correo de {merchant} en Gmail',
  'receipts.box.openOrder': 'Ver pedido',
  'receipts.box.openOrderLabel': 'Ver el pedido {order} en {merchant}',
  'receipts.box.remove': 'No es de este cargo',
  'receipts.box.removeLabel': 'Quitar el vínculo con el pedido {order}',
  'receipts.box.saveError': 'No se pudo guardar: {message}',
  'receipts.review.yes': 'Sí, es este',
  'receipts.review.yesLabel': 'Sí, {merchant} es el cargo de ese pedido',
  'receipts.review.no': 'No',
  'receipts.review.noLabel': 'No, {merchant} no es el cargo de ese pedido',
  'receipts.list.bankName': 'En el estado: {name}',
} as const satisfies Catalog
