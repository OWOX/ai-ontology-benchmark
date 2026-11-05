# Methodology

Terms are defined in [definitions.md](definitions.md).

## The question

Does giving an AI model the rules of a puzzle change how often it solves the puzzle and how often it hallucinates?

Twisty puzzles fit this well. Every move is defined, AI models already know the notation, and the input is unambiguous. A wrong answer can be measured instead of argued about.

Puzzles: 2x2, 3x3, 4x4, and 5x5 cubes, an octahedral puzzle, and a tetrahedral puzzle. More can be added later.

## The variable

The [setup](definitions.md#setups) is the experimental variable, alongside the AI model and the input. Every input goes through all three setups: no model, descriptive model, and prescriptive model. All three ask the same question about the same input. The only thing that changes is how much of the ontology model the prompt carries.

[Decision models](definitions.md#setups) answer through a loop of [calls](definitions.md#attempts-and-outcomes) with a fixed set of options, so four things differ in their results. Their hallucination rate is n/a, because the [decision options](definitions.md#setups) are exactly the legal moves, `done`, and `mismatch`, so they can't return an impossible move and there is nothing to judge. Their hallucination flag is null, and reports show the rate as n/a. This page explains why. The move list is offered under every setup, including no model, so the setups differ less for them and a setup effect is harder to see. A network failure never counts against the success rate, because the attempt is `infrastructure_failure` and every rate leaves it out. A long loop is more likely to reach the retry cap than a single call, so these models may show more infrastructure failures.

## Measurement

1. [`generate`](definitions.md#workflows) builds and freezes an input set once.
2. [`run`](definitions.md#workflows) sends every input to every AI model under every setup, as many attempts as config says. The validator gives each attempt one [outcome](definitions.md#attempts-and-outcomes), and `run` appends one raw record per attempt.
3. [`evaluate`](definitions.md#workflows) re-validates every attempt from its raw response and computes the [metrics](definitions.md#metrics) from raw records, frozen inputs, and config, including the [balanced accuracy](definitions.md#metrics) and the mismatch detection rate by [corruption type](definitions.md#puzzles). No AI model takes part.

Setups are compared with the [paired setup test](definitions.md#metrics) on the same inputs.

## Development and held-out inputs

Input sets 1 and 2 (releases 1.x and 2.x) are the [development input sets](definitions.md#inputs). Prompts were changed while the results of input set 1 were read, so the results on either set show how the method was built and are not evidence for the research question. Release 3.0.0 freezes a new input set from a new seed, the [held-out input set](definitions.md#inputs), with the prompts and the assessment as they stand when it is cut. Every AI model runs on it once. A prompt change after that is a new minor release, and its results are reported next to, never instead of, the earlier ones.

## Sample size

The [paired setup test](definitions.md#metrics) compares setups on the same inputs. With per-input outcomes treated as independent between setups (a conservative assumption, since a hard input tends to be hard under every setup), the exact sign test needs about this many valid inputs per AI model and puzzle for 80% power:

| Rate under setup A | Rate under setup B | Inputs at α 0.05 | Inputs at α 0.0167 (Holm, worst case) |
|---|---|---|---|
| 0.50 | 0.60 | 410 | 540 |
| 0.50 | 0.65 | 190 | 250 |
| 0.50 | 0.70 | 110 | 140 |
| 0.20 | 0.35 | 160 | 200 |
| 0.10 | 0.25 | 120 | 150 |

Input sets 1 and 2 have 30 valid inputs per puzzle, which has about 10–25% power for a 15–20 point difference, so a null result on it says little. The held-out input set aims for at least 150 valid inputs per puzzle (a scramble count of 50 over three depths), enough to detect a 20-point difference. More attempts per input add little power, because the paired test uses the input as its unit, so the held-out run uses 1 attempt per input unless the budget allows more inputs.
