# ai-ontology-hallucination-research

## Abstract

AI models make things up. They cite court cases that never happened and call library functions nobody wrote. A common remedy is to give the AI model the rules of the world it works in, an [ontology model](docs/definitions.md#setups). Does that remedy work, and what does it cost? Few studies can say, because judging a hallucination usually means a person or another AI model deciding what is true.

This study measures it where the truth isn't in question. In a twisty puzzle, a move either exists or it doesn't, and a state can either be solved or it can't. A deterministic ontology model judges every answer, so a hallucination means a broken rule of the system. It never depends on what the authors, a human rater, or another AI model consider right or wrong, and anyone can rerun the scoring and get the same counts.

The answers matter to anyone who builds on AI models. They show whether writing the rules into the prompt is worth its tokens, and whether a cheaper AI model with the rules can beat a costlier one without them.

1. Does an ontology model in the prompt lower the [hallucination rate](docs/definitions.md#metrics)?
2. Does it raise the [success rate](docs/definitions.md#metrics)?
3. Does explaining the rules work differently from listing the legal moves?
4. Does each AI model notice when the colouring it's given makes no sense, because it breaks the puzzle's rules and can't be solved, or does it try to solve it anyway?

## Goals

1. Measure how an ontology model changes the hallucination rate without bias and so that anyone can reproduce the result:
   1. No person and no AI model grades the answers. A deterministic validator does.
   2. Every AI model and every setup gets byte-identical, frozen inputs.
   3. Anyone can rerun the scoring from the stored raw responses without calling an AI model again.
2. Make the cost of accuracy measurable. How many tokens and how many dollars does each AI model and setup spend for one success? Which AI model gives answers without hallucinations at the lowest [cost per success](docs/definitions.md#metrics)? An ontology model makes the prompt longer, so it pays off only if it saves more than it adds.
3. Compare [system-1 and system-2 models](docs/definitions.md#setups). Does reasoning before the answer lower the hallucination rate, does an ontology model help one kind more than the other, and what does each kind pay per success?

## Expected outcomes

1. An open benchmark: versioned, read-only [releases](docs/definitions.md#releases-and-experiments) of the inputs, prompts, and scoring code.
2. For each AI model, setup, puzzle, and scramble depth, the hallucination rate, success rate, mismatch detection rate, and false mismatch rate, each with its denominator n and a 95% Wilson score interval.
3. Tokens per attempt and cost per success for each AI model and setup, split into system-1 and system-2 models.
4. Code under Apache 2.0, and data and results under CC BY 4.0.
5. Listing the legal moves cuts impossible moves the most, because the AI model no longer has to recall the notation.
6. Explaining the rules raises the success rate more than listing the moves does.
7. The gain from an ontology model shrinks as scramble depth and cube size grow.
8. Without an ontology model, AI models rarely notice a colouring the puzzle can't have.
9. An ontology model helps system-1 models more than system-2 models, so a system-1 model with the rules can reach a lower cost per success than a system-2 model without them.

## Side questions

1. Does the success rate fall as scramble depth grows, and does an ontology model slow that fall?
2. Do the effects hold as the cubes get bigger, from 2x2 to 5x5? The octahedral and tetrahedral puzzles have no size series, so this question covers the cubes only.
3. How consistent is an AI model across repeated attempts on the same input, and does an ontology model change that?

## Challenges

1. Hallucination is usually judged by a person or by another model. Here a deterministic script decides, so every count can be reproduced.
2. Every AI model and every setup must see byte-identical inputs, or the comparison means nothing.
3. Move counts must be comparable across models, so all of them are measured against the same reference solver.

## Docs

1. [Definitions](docs/definitions.md): every term and metric, from puzzle and input to success rate and hallucination rate.
2. [Methodology](docs/methodology.md): the setups and how each attempt is measured.
3. [Assumptions](docs/assumptions.md): what the study takes as given.
4. [Related work](docs/related-work.md): other papers on the same problems, and the gap this study fills.
5. [Script specs](docs/specs/README.md): inputs, outputs, and tests for every script, and the commands that run the project.
6. [AGENTS.md](AGENTS.md): rules for coding agents, including the invariants that keep results reproducible.

## Structure

Planned layout. Folders appear as the code is written.

```
config/
  release.toml     seed, puzzles, scramble count and depths, and valid/invalid split
  experiments/     one file per experiment: release, AI models, attempts, and retry cap
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
docs/              definitions, methodology, specs, puzzles, assumptions, related work
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
