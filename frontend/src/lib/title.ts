const MAX_TITLE_LENGTH = 60

/** A conversation title from its opening question.
 *
 *  Titles are set when the conversation is created and never again — the API has no
 *  PATCH — so this runs on the first question and its result is permanent.
 */
export function deriveTitle(question: string): string {
  const collapsed = question.trim().replace(/\s+/g, ' ')
  if (collapsed.length <= MAX_TITLE_LENGTH) return collapsed
  return `${collapsed.slice(0, MAX_TITLE_LENGTH - 1).trimEnd()}…`
}
