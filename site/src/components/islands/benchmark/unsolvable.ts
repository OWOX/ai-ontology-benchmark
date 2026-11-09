/** Why a state with a given corruption type can't be reached from the solved state by legal moves (docs/definitions.md, Corruption). */
const WHY: Record<string, string> = {
  'twisted corner': 'Legal moves keep the total twist of the corners a multiple of a full turn. One corner twisted on its own breaks that.',
  'flipped edge': 'Every legal move flips an even number of edges, so the number of flipped edges always stays even. One flipped edge on its own can\'t be reached.',
  'flipped wing': "A wing's two stickers never swap places under legal moves, so a wing showing them swapped can't be reached.",
  'swapped corners': 'Legal moves permute the corners and the edges with the same parity. Swapping two corners and nothing else is an odd permutation that legal moves can\'t make alone.',
  'swapped edges': 'Legal moves permute the corners and the edges with the same parity. Swapping two edges and nothing else is an odd permutation that legal moves can\'t make alone.',
  'recoloured sticker': 'Legal moves only move stickers and never change their colour, so every colour keeps its count. A recoloured sticker leaves one colour with too many stickers and another with too few.',
}

const GENERIC = "No sequence of legal moves from the solved state produces this state."

/** The corruption type: the first two words of the corruption description, e.g. "recoloured sticker" from "recoloured sticker L3 D to U". */
export function corruptionType(corruption: string | null | undefined): string {
  return (corruption ?? '').trim().split(/\s+/).slice(0, 2).join(' ')
}

/** One or two sentences on why the corruption makes the state unreachable; a generic sentence for an unknown or missing type. */
export function whyUnsolvable(corruption: string | null | undefined): string {
  return WHY[corruptionType(corruption)] ?? GENERIC
}

/** The corruption description as a sentence: capitalized, ending in a full stop. Empty without one. */
export function corruptionSentence(corruption: string | null | undefined): string {
  const text = (corruption ?? '').trim()
  if (!text) return ''
  const sentence = text[0].toUpperCase() + text.slice(1)
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`
}
