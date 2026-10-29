# ai-ontology-hallucination-research

## Goals

1. Measure how an ontology model changes the hallucination rate without bias and so that anyone can reproduce the result:
   1. No person and no AI model grades the answers. A deterministic validator does.
   2. Every AI model and every setup gets byte-identical, frozen inputs.
   3. Anyone can rerun the scoring from the stored raw responses without calling an AI model again.
2. Make the cost of accuracy measurable. How many tokens and how many dollars does each AI model and setup spend for one success? Which AI model gives answers without hallucinations at the lowest [cost per success](docs/definitions.md#metrics)? An ontology model makes the prompt longer, so it pays off only if it saves more than it adds.
3. Compare [system-1 and system-2 models](docs/definitions.md#setups). Does reasoning before the answer lower the hallucination rate, does an ontology model help one kind more than the other, and what does each kind pay per success?

## Approach

An AI model hallucinates when it returns a move that doesn't exist on the puzzle it's given. A deterministic validator checks every returned move against the puzzle's [move group](docs/definitions.md#puzzles) by exact string match and counts each one that isn't there. Some inputs show a colouring that no sequence of legal moves can produce, and the validator also records whether the AI model flags them.

Studies of hallucination in AI models usually score answers against a reference that a person or another AI model judges to be correct. The measured rate then carries the judge's bias and can't be reproduced exactly. A common mitigation is to give the AI model an explicit [ontology model](docs/definitions.md#setups) of its domain. Whether this reduces hallucination, and at what cost in tokens, is still open.

This study tests the question in closed systems where correctness isn't a matter of judgement. A deterministic ontology model of each [twisty puzzle](docs/definitions.md#puzzles) defines hallucination as a broken rule of the system, independent of what the authors, a human rater, or another AI model consider right or wrong. Every count can be recomputed from the stored responses. Twisty puzzles are close to the best case for this mitigation, because their rules are complete and every answer can be checked. If an ontology model in the prompt doesn't reduce hallucination here, there is little reason to expect it to do so in open domains, where neither condition holds. If it does, the size of the effect and its cost give a reference point for those domains.

1. Does an ontology model in the prompt lower the [hallucination rate](docs/definitions.md#metrics)?
2. Does it raise the [success rate](docs/definitions.md#metrics)?
3. Does explaining the rules work differently from listing the legal moves?
4. Does each AI model notice when the colouring it's given makes no sense, because it breaks the puzzle's rules and can't be solved, or does it try to solve it anyway?

## Expected outcomes

1. An open benchmark: versioned, read-only [releases](docs/definitions.md#releases-and-experiments) of the inputs, prompts, and scoring code.
2. For each AI model, setup, puzzle, and scramble depth, the hallucination rate, success rate, mismatch detection rate, and false mismatch rate, each with its denominator n and a 95% Wilson score interval.
3. Tokens per attempt and cost per success for each AI model and setup, split into system-1 and system-2 models.
4. Code under Apache 2.0, and data and results under CC BY 4.0.

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
