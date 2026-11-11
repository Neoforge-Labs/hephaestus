'use client'

import { useState } from 'react'

/** A command you can copy, with the shell prompt excluded from the copy.
 *
 * The prompt glyph is rendered as a sibling and marked aria-hidden, so neither
 * the clipboard nor a screen reader picks up a `$` nobody typed.
 */
export function CopyCommand({ command, hint }: { command: string; hint?: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard refused (insecure context, denied permission). The command is
      // on screen and selectable, so there is nothing to recover from; saying
      // "copied" when it was not is the only real failure here.
      setCopied(false)
    }
  }

  return (
    <div className="cmd">
      <code className="cmd-text">
        <span className="cmd-prompt" aria-hidden="true">
          $
        </span>
        {command}
      </code>
      <button type="button" onClick={copy} className="cmd-copy" aria-label={`Copy: ${command}`}>
        {copied ? 'Copied' : 'Copy'}
      </button>
      {hint ? <span className="cmd-hint">{hint}</span> : null}
    </div>
  )
}
