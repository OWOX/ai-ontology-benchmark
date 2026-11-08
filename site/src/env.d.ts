// Only type checking reaches cubing: poly/model.ts is imported for its types and never bundled, so the package is not a dependency.
declare module 'cubing/kpuzzle' {
  export type KPuzzle = any
}
declare module 'cubing/puzzles' {
  export const puzzles: any
}
