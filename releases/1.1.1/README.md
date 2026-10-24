# Release 1.1.1

Note: Mirror of 1.1.0 after comments were added to src/validator.py

Date: 2026-10-24T21:25:49Z

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
| descriptive | 2x2 | c73bc3c402b2 |
| descriptive | 3x3 | bf7bd31d24ce |
| no_model | 2x2 | 39826219a35f |
| no_model | 3x3 | 2b340850dbf8 |
| prescriptive | 2x2 | e29b0e335344 |
| prescriptive | 3x3 | 4270735ea5ca |

## Assessment

sha256: `1f2037d9fd0a0542530302c34cf5aa9646d10a65bcfa9a6d4c22a718396d6ca0`

## Previous release

[1.1.0](../1.1.0/README.md)
