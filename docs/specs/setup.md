# setup

Files: `pyproject.toml`.

## Purpose

Install the project and its dependencies with one command.

## Inputs

None.

## Outputs

1. `pyproject.toml` requires Python 3.11 or later, for `tomllib`. It lists `pytest` as a test dependency and one official SDK for each provider in [models](models.md): `anthropic`, `openai`, `google-genai`, `typesafe-sdk`, and `cloudflare`, plus `pydantic`, which `src/run/models.py` imports directly, and `rich` for the run display. It lists nothing else.
2. API keys are not part of the install. `src/run/models.py` reads `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `TYPESAFE_API_KEY`, `CLOUDFLARE_API_TOKEN`, and `CLOUDFLARE_ACCOUNT_ID` from the environment. The [UI](ui.md#inputs) keeps keys in `secrets/`, which is in `.gitignore`.

## How to test

1. On a clean checkout, `pip install -e .` succeeds and `pytest` passes.
2. `git grep -nE "sk-|AIza"` finds no key in the repo.
