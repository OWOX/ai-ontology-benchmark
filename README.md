# ai-ontology-hallucination-research

## Abstract

To evaluate AI models without bias, we test them on ontologies of real-world objects. The research uses Rubik's cubes as the well-known source of legal moves, constraints, and a criterion of success. Each model gets a scrambled cube and must either solve it or say why it can't be solved. A script judges every answer, not a person or another AI, so the assessment is objective and the experiments are reproducible. The metrics show how often a model's answers are right, how often it hallucinates by making [impossible moves](docs/definitions.md#puzzles) or naming a defect the cube can't show, and how well it spots an impossible cube and names what is wrong.

## Goals

1. Measure how an ontology model affects the hallucination rate.
2. Make the measurement without bias and the result easily reproducible.
3. Make the cost of accuracy measurable.

## Approach

The study uses [twisty puzzles](docs/definitions.md#puzzles): 2x2, 3x3, 4x4, and 5x5 cubes. An octahedral puzzle and a tetrahedral puzzle will be added later. A move turns one part of the puzzle and is written in the puzzle's standard notation, which AI models already know from their training data, for example `R`, `U'`, or `F2` on the 3x3 cube. Each puzzle has a fixed list of legal moves. An AI model gets a scrambled puzzle and returns the moves it thinks solve it.

The AI model hallucinates when it returns a move that isn't on the puzzle's list of legal moves. A deterministic validator checks every returned move against that list by exact string match and counts each one that isn't there. Some inputs show a colouring that no sequence of legal moves can produce, and the validator also records whether the AI model flags them and which reason it gives, chosen from a fixed list. The list holds a decoy reason that no state can show, and choosing it also counts as a hallucination.

Each answer is scored as a [true or false positive](docs/methodology.md#scoring-an-answer), a solution that does or doesn't solve the puzzle, or a true or false negative, a `MISMATCH` with the right reason or any other `MISMATCH`. Three numbers summarize an AI model: [balanced precision](docs/definitions.md#metrics), the share of its answers that are right; the [hallucination rate](docs/definitions.md#metrics); and [critical thinking](docs/definitions.md#metrics), how well it tells a solvable puzzle from an unsolvable one and names what is wrong.

Studies of hallucination in AI models usually score answers against a reference that a person or another AI model judges to be correct. The measured rate then carries the judge's bias and can't be reproduced exactly. One proposed remedy is to give the AI model an explicit [ontology model](docs/definitions.md#setups) of its domain, either in the prompt or through a knowledge graph ([related work](docs/related-work.md#ontologies-and-knowledge-graphs-against-hallucination)). Whether this reduces hallucination, and at what cost in tokens, is still open.

This study tests the question in closed systems where correctness isn't a matter of judgement. A deterministic ontology model of each [twisty puzzle](docs/definitions.md#puzzles) defines hallucination as a broken rule of the system, independent of what the authors, a human rater, or another AI model consider right or wrong. Every count can be recomputed from the stored responses. Twisty puzzles are close to the best case for this remedy, because their rules are complete and every answer can be checked. If an ontology model in the prompt doesn't reduce hallucination here, there is little reason to expect it to do so in open domains, where neither condition holds. If it does, the size of the effect and its cost give a reference point for those domains.

1. Does an ontology model in the prompt lower the [hallucination rate](docs/definitions.md#metrics)?
2. Does it raise [balanced precision](docs/definitions.md#metrics)?
3. Does explaining the rules work differently from listing the legal moves?
4. Does each AI model notice when the colouring it's given makes no sense, because it breaks the puzzle's rules and can't be solved, and name the broken rule, or does it try to solve it anyway? This is its [critical thinking](docs/definitions.md#metrics).

## Expected outcomes

1. An open benchmark: versioned, read-only [releases](docs/definitions.md#releases-and-experiments) of the inputs, prompts, and scoring code.
2. For each AI model, setup, puzzle, and scramble depth, balanced precision, coverage, the hallucination rate, critical thinking, the mismatch detection rate, and the false mismatch rate, each with its denominator n and a 95% bootstrap interval over inputs.
3. Tokens per attempt and [cost efficiency](docs/definitions.md#metrics), the cost of one right answer, for each AI model and setup.
4. Code under Apache 2.0, and data and results under CC BY 4.0.

## Side questions

1. Does precision fall as scramble depth grows, and does an ontology model slow that fall?
2. Do the effects hold as the cubes get bigger, from 2x2 to 5x5?
3. How consistent is an AI model across repeated attempts on the same input, and does an ontology model change that?
4. Do [system-1 and system-2 models](docs/definitions.md#setups) differ? Does an ontology model help one kind more than the other, and what does each kind pay per right answer?

## Challenges

1. Hallucination is usually judged by a person or by another model. Here a deterministic script decides, so every count can be reproduced.
2. Every AI model and every setup must see byte-identical inputs, or the comparison means nothing.

## Docs

1. [Getting started](docs/getting-started.md): the minimum steps to run an experiment from the terminal.
2. [Definitions](docs/definitions.md): every term and metric, from puzzle and input to precision and hallucination rate.
3. [Methodology](docs/methodology.md): the setups and how each attempt is measured.
4. [Assumptions](docs/assumptions.md): what the study takes as given.
5. [Related work](docs/related-work.md): other papers on the same problems, and the gap this study fills.
6. [Script specs](docs/specs/README.md): inputs, outputs, and tests for every script, and the commands that run the project.
7. [Contributing](CONTRIBUTING.md): how to add a puzzle and how to run an experiment, step by step.
8. [AGENTS.md](AGENTS.md): rules for coding agents, including the invariants that keep results reproducible.
9. [One-page summary](docs/onepager.pdf) (PDF): the goals, approach, expected outcomes, and authors on one page.

## Structure

Planned layout. Folders appear as the code is written.

```
config/
  release.toml     seed, puzzles, scramble count and depths, and valid/invalid split
  experiments/     one file per experiment: release, AI models, attempts, and retry cap
  templates/       one experiment config per provider to copy, see docs/getting-started.md
  prices.toml      token prices per AI model
  models.toml      model catalogue for the UI
src/
  config.py        loads and checks the config files
  validator.py     turns a raw response into moves, flags, and an outcome
  puzzles/         common interface, one engine per puzzle, registry
  generate/        builds an input set with each engine's scramble
  release/         freezes inputs, prompts, and assessment into a release
  run/             plays a release against each AI model under the three setups
  evaluate/        computes the metrics and writes the experiment report
ui/                local web page to browse, run, and commit experiments (ui/start.sh)
prompts/           working templates: no_model, descriptive, prescriptive
releases/          one read-only folder per release version
results/           one folder per experiment: raw records and one report per release
docs/              definitions, methodology, specs, puzzles, contributing guides, assumptions, related work, one-page summary PDF
CONTRIBUTING.md    how to add a puzzle and how to run an experiment
LICENSE            Apache 2.0 licence text
LICENSE-CC-BY-4.0  CC BY 4.0 licence text
NOTICE             copyright and attribution for reused code
tests/
```

## Builds on

1. Cube Bench: A Benchmark for Spatial Visual Reasoning in MLLMs. [arXiv:2512.20595](https://arxiv.org/abs/2512.20595), [code](https://github.com/dana-23/cube-bench).
2. HalluLens: LLM Hallucination Benchmark. [arXiv:2504.17550](https://arxiv.org/abs/2504.17550).

## Licence

Code in `src/`, `ui/`, `tests/`, and `config/`, plus the build and packaging files at the root, such as `pyproject.toml`, is under the [Apache License 2.0](LICENSE). Everything else, including docs, prompts, frozen inputs, and results, is under [CC BY 4.0](LICENSE-CC-BY-4.0). Reused third-party code is listed in [NOTICE](NOTICE).
