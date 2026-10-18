# setup

Files: `pyproject.toml`, `.env.example`.

## Purpose

Install the project and its dependencies with one command, and show which API keys it needs.

## Inputs

None.

## Outputs

1. `pyproject.toml` requires Python 3.11 or later, for `tomllib`. It lists `pytest` as a test dependency and one official SDK for each provider in [models](models.md): `anthropic`, `openai`, and `google-genai`. It lists nothing else.
2. `.env.example` lists `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY`, each with an empty value. The real `.env` is already in `.gitignore`.

## How to test

1. On a clean checkout, `pip install -e .` succeeds and `pytest` passes.
2. `git grep -nE "sk-|AIza"` finds no key in the repo.
