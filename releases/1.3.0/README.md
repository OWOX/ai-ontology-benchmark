# Release 1.3.0

Note: Moves one per line or MISMATCH instead of a JSON object; validator parses lines

Date: 2026-11-02T23:56:19Z

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

sha256: `94f14822aeb2be54072b9bb8347e17d95a78e17be2e4f72cbb258c232f72ede8`

## Previous release

[1.2.0](../1.2.0/README.md)
