# Methodology

Terms are defined in [definitions.md](definitions.md).

## The question

Does giving an AI model the rules of a puzzle change how often it solves the puzzle and how often it hallucinates?

Twisty puzzles fit this well. Every move is defined, AI models already know the notation, and the input is unambiguous. A wrong answer can be measured instead of argued about.

Puzzles: 2x2, 3x3, and 5x5 cubes, an octahedral puzzle, and a tetrahedral puzzle. More can be added later.

## The variable

The [setup](definitions.md#setups) is the experimental variable, alongside the AI model and the input. Every input goes through all three setups: no model, descriptive model, and prescriptive model. All three ask the same question about the same input. The only thing that changes is how much of the ontology model the prompt carries.

[Decision models](definitions.md#setups) answer through a loop of [calls](definitions.md#attempts-and-outcomes) with a fixed set of options, so four things differ in their results. Their hallucination rate is always 0, because the [decision options](definitions.md#setups) are exactly the legal moves and `done`, and reports show it as 0. This page explains why. The move list is offered under every setup, including no model, so the setups differ less for them and a setup effect is harder to see. A network failure never counts against the success rate, because the attempt is `infrastructure_failure` and every rate leaves it out. A long loop is more likely to reach the retry cap than a single call, so these models may show more infrastructure failures.

## Measurement

1. [`generate`](definitions.md#workflows) builds and freezes an input set once.
2. [`run`](definitions.md#workflows) sends every input to every AI model under every setup, as many attempts as config says. The validator gives each attempt one [outcome](definitions.md#attempts-and-outcomes), and `run` appends one raw record per attempt.
3. [`evaluate`](definitions.md#workflows) re-validates every attempt from its raw response and computes the [metrics](definitions.md#metrics) from raw records, frozen inputs, and config. No AI model takes part.
