// Catalog messages with React elements inside (a link or <strong> in the middle of a sentence):
// the same templates as `t`, with placeholders filled by nodes.
import { Fragment, type ReactNode } from 'react'
import { es } from './es'
import { type Message, type MessageKey, pieces, template } from './index'

type NodeParams = Readonly<Record<string, ReactNode>>

/** The message for `key` with each `{name}` replaced by `params[name]` (text or an element). */
export function tn(key: MessageKey, params: NodeParams): ReactNode {
  const text = template(es[key] as Message, params)
  return pieces(text).map((piece, index) => (
    <Fragment key={index}>
      {piece.name !== null && Object.hasOwn(params, piece.name) ? params[piece.name] : piece.text}
    </Fragment>
  ))
}
