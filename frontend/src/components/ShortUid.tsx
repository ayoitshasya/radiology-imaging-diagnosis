import { useState } from 'react'
import { Link } from 'react-router'

export const SHORT_UID_LENGTH = 12

/** Last 12 characters of a StudyInstanceUID: enough to tell studies apart on screen. */
export function shortUid(uid: string): string {
  return uid.length > SHORT_UID_LENGTH ? uid.slice(-SHORT_UID_LENGTH) : uid
}

interface Props {
  uid: string
  /** When set, the short UID is a link to this route. */
  to?: string
}

/**
 * A shortened study UID with a button that copies the full one. Study UIDs are the only
 * study reference the viewer shows; patient identifiers are never sent to the frontend.
 */
export function ShortUid({ uid, to }: Props) {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const short = shortUid(uid)
  const prefix = short === uid ? '' : '…'
  const label = `Study UID ending ${short}`

  async function copy() {
    try {
      await navigator.clipboard.writeText(uid)
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
  }

  return (
    <span className="uid">
      {to ? (
        <Link to={to} aria-label={`Open study, UID ending ${short}`}>
          <code>
            {prefix}
            {short}
          </code>
        </Link>
      ) : (
        <code aria-label={label}>
          {prefix}
          {short}
        </code>
      )}
      <button type="button" className="small" onClick={copy} aria-label={`Copy full UID of study ending ${short}`}>
        Copy UID
      </button>
      <span role="status" className="copy-status">
        {copyState === 'copied' ? 'Copied' : copyState === 'failed' ? 'Copy failed' : ''}
      </span>
    </span>
  )
}
