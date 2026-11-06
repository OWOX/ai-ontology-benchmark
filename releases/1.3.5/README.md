# Release 1.3.5

Note: Mirror of 1.3.4. Assessment fix: a list marker glued to the first token after a bullet is stripped, so lines like '- 1.R' or '- b) R' parse as decorated move lines; some outcomes move from abstention to format_error or hallucination, and from hallucination to format_error

Date: 2026-11-06T05:51:23Z

## Inputs

| Puzzle | Depth | Validity | Inputs |
|---|---|---|---|
| 2x2 | 5 | invalid | 5 |
| 2x2 | 5 | valid | 10 |
| 2x2 | 10 | invalid | 5 |
| 2x2 | 10 | valid | 10 |
| 2x2 | 20 | invalid | 5 |
| 2x2 | 20 | valid | 10 |
| 3x3 | 5 | invalid | 5 |
| 3x3 | 5 | valid | 10 |
| 3x3 | 10 | invalid | 5 |
| 3x3 | 10 | valid | 10 |
| 3x3 | 20 | invalid | 5 |
| 3x3 | 20 | valid | 10 |

## Prompt versions

| Setup | Puzzle | Prompt version |
|---|---|---|
| descriptive | 2x2 | d04f7295702f |
| descriptive | 3x3 | d8778f255092 |
| no_model | 2x2 | 07b93c228ffe |
| no_model | 3x3 | 3243cd507c17 |
| prescriptive | 2x2 | a3ebfa4c2de4 |
| prescriptive | 3x3 | b323b5bf5f93 |

## Decision prompt versions

| Setup | Puzzle | Prompt version |
|---|---|---|
| descriptive | 2x2 | f413e8a9f6a8 |
| descriptive | 3x3 | 46b24da21ce9 |
| no_model | 2x2 | c9c245e0ec14 |
| no_model | 3x3 | 028988720033 |
| prescriptive | 2x2 | 91ab2f1295e9 |
| prescriptive | 3x3 | 8e3e91a82367 |

## Assessment

sha256: `9358b5ec7c871b6d3f40bb736b52b6452d74f7d4dd32d6f71423a1e9b450f9b9`

## Previous release

[1.3.4](../1.3.4/README.md)
