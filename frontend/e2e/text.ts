// The UI text the specs assert comes from the app's own catalog, so a spec checks the screen
// says what the catalog says (and the catalog itself is the single place with Spanish).
export { t } from '../src/i18n'

/** `text` as a literal inside a RegExp. */
export function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** A RegExp matching `text` literally (anchored with `^`/`$` when asked). */
export function literal(text: string, anchors: { start?: boolean; end?: boolean } = {}): RegExp {
  return new RegExp(`${anchors.start ? '^' : ''}${escapeRegExp(text)}${anchors.end ? '$' : ''}`)
}
