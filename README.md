# ai-ontology-hallucination-research

## Key questions

The study tests whether an [ontology model](docs/definitions.md#setups), meaning the rules of a twisty puzzle, given as input changes the [hallucination rate](docs/definitions.md#metrics) and [success rate](docs/definitions.md#metrics) of AI models. Puzzles are deterministic, so every answer can be checked by a script and nobody has to argue about it. The ontology model goes into the prompt under one of three [setups](docs/definitions.md#setups): no model, descriptive model, or prescriptive model.

1. With an ontology model in the input, does an AI model solve the puzzle more often?
2. Does it make up fewer moves that don't exist?
3. Does a descriptive ontology model work differently from a prescriptive one?
4. Does the AI model notice when the input describes a state that can't be reached by legal moves?

## Side questions

1. Token use and cost. How many input and output tokens, and how much latency, does each setup spend per attempt, and what does one success cost? An ontology model makes the prompt longer, so it pays off only if it saves more than it adds.
2. Does the success rate fall as scramble depth grows, and does an ontology model slow that fall?
3. Do the effects hold as the cubes get bigger, from 2x2 to 5x5? The octahedral and tetrahedral puzzles have no size series, so this question covers the cubes only.
4. How consistent is an AI model across repeated attempts on the same input, and does an ontology model change that?

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
ui/                local web page to run an experiment (python -m ui.server)
prompts/           working templates: no_model, descriptive, prescriptive
releases/          one read-only folder per release version
results/           one folder per experiment: raw records and one report per release
docs/              definitions, methodology, assumptions, related work
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
