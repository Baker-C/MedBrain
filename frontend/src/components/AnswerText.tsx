import type { SourcesMap } from '../api/types'
import { answerSegments } from '../lib/sentinels'
import { CitationLink } from './CitationLink'

/** Answer text with its sentinels resolved into citations.
 *
 *  While streaming, a half-arrived sentinel is withheld by `answerSegments`, so `[[S`
 *  never flashes on screen before its closing brackets arrive. */
export function AnswerText({
  text,
  sources,
  streaming,
}: {
  text: string
  sources: SourcesMap
  streaming: boolean
}) {
  return (
    <>
      {answerSegments(text, streaming).map((segment, index) =>
        segment.kind === 'text' ? (
          <span key={index} className="whitespace-pre-wrap">
            {segment.text}
          </span>
        ) : (
          <CitationLink key={index} tag={segment.tag} citation={sources[segment.tag]} />
        ),
      )}
    </>
  )
}
