# Methodology

Terms are defined in [definitions.md](definitions.md).

## The question

Does giving an AI model the rules of a puzzle change how often its answers are right, how often it hallucinates, and how well it judges whether a puzzle can be solved at all?

Twisty puzzles fit this well. Every move is defined, AI models already know the notation, and the input is unambiguous. A wrong answer can be measured instead of argued about.

Puzzles: 2x2, 3x3, 4x4, and 5x5 cubes, an octahedral puzzle, and a tetrahedral puzzle. More can be added later.

## The variable

The [setup](definitions.md#setups) is the experimental variable, alongside the AI model and the input. Every input goes through all three setups: no model, descriptive model, and prescriptive model. All three ask the same question about the same input. The only thing that changes is how much of the ontology model the prompt carries.

[Decision models](definitions.md#setups) answer through a loop of [calls](definitions.md#attempts-and-outcomes) with a fixed set of options, so four things differ in their results. Their hallucination rate is n/a, because the [decision options](definitions.md#setups) are exactly the legal moves, `done`, and one `mismatch_<n>` option per [mismatch reason](definitions.md#attempts-and-outcomes), so they can't return an impossible move. Reports show the rate as n/a, and this page explains why. They can still choose the [decoy reason](definitions.md#attempts-and-outcomes), so their reason hallucination rate is measured as for any other AI model. The move list is offered under every setup, including no model, so the setups differ less for them and a setup effect is harder to see. A network failure never counts against precision, because the attempt is `infrastructure_failure` and every rate leaves it out. A long loop is more likely to reach the retry cap than a single call, so these models may show more infrastructure failures.

## Measurement

1. [`generate`](definitions.md#workflows) builds and freezes an input set once.
2. [`run`](definitions.md#workflows) sends every input to every AI model under every setup, as many attempts as config says. The validator gives each attempt one [outcome](definitions.md#attempts-and-outcomes), and `run` appends one raw record per attempt.
3. [`evaluate`](definitions.md#workflows) re-validates every attempt from its raw response, classifies each answer as below, and computes the [metrics](definitions.md#metrics) from raw records, frozen inputs, and config. No AI model takes part.

Setups are compared with the [paired setup test](definitions.md#metrics) on the same inputs.

## Scoring an answer

Each input is either solvable (a [valid input](definitions.md#inputs)) or not (an [invalid input](definitions.md#inputs)). Each answer either claims a solution, by giving moves, or claims that the puzzle can't be solved, by answering `MISMATCH` with a [mismatch reason](definitions.md#attempts-and-outcomes). The classification judges the answer, not the puzzle: an answer is positive when it claims a solution, and true when its claim is right.

| Input | Answer | Class |
|---|---|---|
| Solvable | Moves that solve it | [True positive](definitions.md#attempts-and-outcomes) |
| Solvable | Legal moves that leave it unsolved | [False positive](definitions.md#attempts-and-outcomes) |
| Solvable | Moves with an [impossible move](definitions.md#puzzles) | False positive, and a hallucination |
| Solvable | `MISMATCH`, any reason | [False negative](definitions.md#attempts-and-outcomes) |
| Solvable | `MISMATCH` with the [decoy reason](definitions.md#attempts-and-outcomes) | False negative, and a hallucination |
| Unsolvable | Any moves | False positive (a hallucination too if a move is impossible) |
| Unsolvable | `MISMATCH` with its corruption type | [True negative](definitions.md#attempts-and-outcomes) |
| Unsolvable | `MISMATCH` with another reason or `other` | False negative |
| Unsolvable | `MISMATCH` with the decoy reason | False negative, and a hallucination |
| Either | Abstention, format error, truncated, malformed output, or infrastructure failure | Not classified |

A hallucination is both a wrong answer and a hallucination, so it counts in both the class and the hallucination rate. The three headline metrics are:

1. [Balanced precision](definitions.md#metrics): the share of classified answers that are right, as the mean over solvable and unsolvable inputs, with [coverage](definitions.md#metrics) beside it.
2. The [hallucination rate](definitions.md#metrics) and the [reason hallucination rate](definitions.md#metrics).
3. [Critical thinking](definitions.md#metrics): the mean of the diagnosis rate on unsolvable inputs and one minus the false mismatch rate on solvable ones.

[Cost efficiency](definitions.md#metrics) gives the cost of one right answer. Balanced precision and critical thinking don't depend on the share of unsolvable inputs, so input sets with different splits compare.

## Mismatch reasons

A bare `MISMATCH` can't tell an inference from a guess, and an AI model that answers `MISMATCH` to every input gets a detection rate of 1.0. So the prompt asks for the [mismatch reason](definitions.md#attempts-and-outcomes) too, chosen from a closed list that the engine defines, and the validator judges it by exact match, as it judges moves.

1. The list holds every corruption type of the puzzle's [shape](definitions.md#puzzles), so on a 2x2 it names edges and wings that the 2x2 doesn't have. Naming one of those is a wrong reason.
2. The list also holds a [decoy reason](definitions.md#attempts-and-outcomes) that no state can show. Choosing it is a hallucination.
3. The right reason on an invalid input is a [diagnosis](definitions.md#attempts-and-outcomes). [Critical thinking](definitions.md#metrics) counts a false MISMATCH against the AI model as much as a missed diagnosis.
4. A wrong reason makes the answer a false negative, so it lowers precision and critical thinking. The mismatch detection rate and balanced accuracy read only the mismatch flag, so a wrong reason doesn't change them.
5. The list tells every setup, including no model, which kinds of defect exist. Detection rates under a release with mismatch reasons are therefore not comparable with releases 1.x and 2.x, which ask for a bare `MISMATCH`.

## Development and held-out inputs

Input sets 1 and 2 (releases 1.x and 2.x) are the [development input sets](definitions.md#inputs). Prompts were changed while the results of input set 1 were read, so the results on either set show how the method was built and are not evidence for the research question. Release 3.0.0 freezes a new input set from a new seed, the [held-out input set](definitions.md#inputs), with the prompts and the assessment as they stand when it is cut. Per puzzle and scramble depth it holds 40 valid inputs and 10 invalid ones (scramble count 40, valid/invalid split 0.25), so 20% of the inputs are unsolvable. The scramble depths are 5, 10, and 20 on the 2x2 and 3x3, 10, 20, and 40 on the 4x4, and 15, 30, and 60 on the 5x5. 40 and 60 are the WCA scramble lengths for the 4x4 and 5x5, so their deepest inputs match a competition scramble. Every AI model runs on it once. A prompt change after that is a new minor release, and its results are reported next to, never instead of, the earlier ones.

## Sample size

The [paired setup test](definitions.md#metrics) compares setups on the same inputs. With per-input outcomes treated as independent between setups (a conservative assumption, since a hard input tends to be hard under every setup), the exact sign test needs about this many valid inputs per AI model and puzzle for 80% power:

| Rate under setup A | Rate under setup B | Inputs at α 0.05 | Inputs at α 0.0167 (Holm, worst case) |
|---|---|---|---|
| 0.50 | 0.60 | 410 | 540 |
| 0.50 | 0.65 | 190 | 250 |
| 0.50 | 0.70 | 110 | 140 |
| 0.20 | 0.35 | 160 | 200 |
| 0.10 | 0.25 | 120 | 150 |

Input sets 1 and 2 have 30 valid inputs per puzzle, which has about 10–25% power for a 15–20 point difference, so a null result on it says little. The held-out input set has 120 valid inputs per puzzle (a scramble count of 40 over three depths). That is enough to detect a 20-point difference from 0.50 at α 0.05, and a little short of the 140 the worst-case Holm correction asks for. More attempts per input add little power, because the paired test uses the input as its unit, so the held-out run uses 1 attempt per input unless the budget allows more inputs.
