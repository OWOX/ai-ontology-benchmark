# Release 2.0.3

Note: Mirror of 2.0.2. Assessment fix: a list marker glued to the first token after a bullet is stripped, so lines like '- 1.R' or '- b) R' parse as decorated move lines; some outcomes move from abstention to format_error or hallucination, and from hallucination to format_error

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
| 4x4 | 5 | invalid | 5 |
| 4x4 | 5 | valid | 10 |
| 4x4 | 10 | invalid | 5 |
| 4x4 | 10 | valid | 10 |
| 4x4 | 20 | invalid | 5 |
| 4x4 | 20 | valid | 10 |
| 5x5 | 5 | invalid | 5 |
| 5x5 | 5 | valid | 10 |
| 5x5 | 10 | invalid | 5 |
| 5x5 | 10 | valid | 10 |
| 5x5 | 20 | invalid | 5 |
| 5x5 | 20 | valid | 10 |

## Prompt versions

| Setup | Puzzle | Prompt version |
|---|---|---|
| descriptive | 2x2 | d04f7295702f |
| descriptive | 3x3 | d8778f255092 |
| descriptive | 4x4 | fd6384232ed2 |
| descriptive | 5x5 | 8a913bf6e36e |
| no_model | 2x2 | 07b93c228ffe |
| no_model | 3x3 | 3243cd507c17 |
| no_model | 4x4 | 99c3ffb8521b |
| no_model | 5x5 | 9ab32e5bae95 |
| prescriptive | 2x2 | a3ebfa4c2de4 |
| prescriptive | 3x3 | b323b5bf5f93 |
| prescriptive | 4x4 | 1a16b51cc1d2 |
| prescriptive | 5x5 | e5345c9f280c |

## Decision prompt versions

| Setup | Puzzle | Prompt version |
|---|---|---|
| descriptive | 2x2 | f413e8a9f6a8 |
| descriptive | 3x3 | 46b24da21ce9 |
| descriptive | 4x4 | 0a7f90dc2076 |
| descriptive | 5x5 | 27886de3530b |
| no_model | 2x2 | c9c245e0ec14 |
| no_model | 3x3 | 028988720033 |
| no_model | 4x4 | f8946466ea4c |
| no_model | 5x5 | c213c0799f64 |
| prescriptive | 2x2 | 91ab2f1295e9 |
| prescriptive | 3x3 | 8e3e91a82367 |
| prescriptive | 4x4 | 612284e158cc |
| prescriptive | 5x5 | b9105c31b59b |

## Assessment

sha256: `9358b5ec7c871b6d3f40bb736b52b6452d74f7d4dd32d6f71423a1e9b450f9b9`

## Previous release

[2.0.2](../2.0.2/README.md)
