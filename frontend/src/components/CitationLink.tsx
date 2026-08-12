import { useState } from 'react'

import { getSourceUrl, withPage } from '../api/client'
import type { Citation } from '../api/types'
import { messageOf } from '../lib/errors'

/** `warfarin § 5.1 Hemorrhage`, or the page alone on a chunk with no carved section.
 *  Mirrors `section_label` in backend/chat/context.py. */
function label(citation: Citation): string {
  const section = [citation.section_number, citation.section_title].filter(Boolean).join(' ')
  return section === ''
    ? `${citation.drug} p.${citation.page_start}`
    : `${citation.drug} § ${section}`
}

/** A citation tag rendered as its source. Clicking mints a short-lived signed URL and
 *  opens the PDF at the cited page.
 *
 *  An unresolved tag renders as its raw sentinel rather than disappearing — if the
 *  mapping and the answer ever disagree, that should be visible, not silently swallowed. */
export function CitationLink({ tag, citation }: { tag: string; citation: Citation | undefined }) {
  const [opening, setOpening] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (citation === undefined) return <span>{`[[${tag}]]`}</span>

  async function open(source: Citation) {
    setOpening(true)
    setError(null)
    try {
      const { url } = await getSourceUrl(source.document_id)
      window.open(withPage(url, source.page_start), '_blank', 'noopener,noreferrer')
    } catch (failure) {
      setError(messageOf(failure))
    } finally {
      setOpening(false)
    }
  }

  return (
    <button
      type="button"
      disabled={opening}
      onClick={() => void open(citation)}
      title={error ?? `Open ${label(citation)} at page ${citation.page_start}`}
      className={`mx-0.5 rounded border px-1.5 py-0.5 align-baseline text-xs ${
        error === null
          ? 'border-sky-300 bg-sky-50 text-sky-800 hover:bg-sky-100'
          : 'border-red-300 bg-red-50 text-red-800'
      } disabled:opacity-60`}
    >
      {label(citation)}
    </button>
  )
}
