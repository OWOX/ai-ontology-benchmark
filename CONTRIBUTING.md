# Contributing

Two kinds of contribution follow a fixed path:

1. [Adding a puzzle](docs/contributing/adding-a-puzzle.md): a new engine, its prompts, and every shared file that names the puzzles.
2. [Running an experiment](docs/contributing/running-an-experiment.md): one branch per experiment, run against one frozen release.

Any other change follows the rules below.

## Rules for every change

1. Read [definitions.md](docs/definitions.md) and [methodology.md](docs/methodology.md) first. Names in code, configs, and docs follow `definitions.md`.
2. Keep to the [invariants](AGENTS.md#invariants). Changing one needs the project owner's approval.
3. Work on a branch and open a pull request to `main`. Nobody pushes to `main` directly.
4. Every script has a spec in [docs/specs/](docs/specs/README.md). Change the spec in the same pull request as the code.
5. Run `pytest` before you open the pull request. Tests never call a real AI model API.
6. Write prose in plain Oxford English, as [AGENTS.md](AGENTS.md#writing) sets out: British spelling with -ize endings, and the Oxford comma.
