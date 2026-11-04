# Experiment exp on release 1.0.0

Release: [1.0.0, tag `release-1.0.0`](../../releases/1.0.0/README.md)

The experiment ran on release 1.0.0. This report is not a mirror.

Assessment hash: `abc123`

Inputs: [inputs.jsonl](../../releases/1.0.0/inputs.jsonl). Prompts: [prompts/](../../releases/1.0.0/prompts).

## Experiment

Config: [experiment.toml](experiment.toml)

| AI model | Provider | API model id | Kind | Served model ids | Params |
|---|---|---|---|---|---|
| M | fake | m-1 | system-2 | m-1 | temperature=0.5 |

Attempts per input, model and setup: 2. Retry cap: 1. Maximum output tokens: 100.

First and last attempt: 2026-01-01T00:00:00Z to 2026-01-01T00:00:00Z.

Torn raw lines skipped: 2.

Token prices per million tokens, from [prices.toml](prices.toml):

| AI model | Input | Output |
|---|---|---|
| M | 1000.0 | 2000.0 |

Budgets in force (USD): request 0.5, AI model 5.0, experiment 10.0.

Cost spent, at the prices above (USD):

| AI model | Spent |
|---|---|
| M | 0.2400 |
| Total | 0.2400 |

## Summary

### M

#### Valid inputs

| Metric | no_model | descriptive | prescriptive |
|---|---|---|---|
| Success rate | 0.50 (0.09–0.91) n=2 | 0.50 (0.09–0.91) n=2 | 0.50 (0.09–0.91) n=2 |
| Hallucination rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| False mismatch rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| Malformed output rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| Cost per success | 0.0400 | 0.0400 | 0.0400 |

#### Invalid inputs

| Metric | no_model | descriptive | prescriptive |
|---|---|---|---|
| Success rate | 0.50 (0.09–0.91) n=2 | 0.50 (0.09–0.91) n=2 | 0.50 (0.09–0.91) n=2 |
| Mismatch detection rate | 0.50 (0.09–0.91) n=2 | 0.50 (0.09–0.91) n=2 | 0.50 (0.09–0.91) n=2 |
| Hallucination rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| Malformed output rate | 0.50 (0.09–0.91) n=2 | 0.50 (0.09–0.91) n=2 | 0.50 (0.09–0.91) n=2 |

## Setup comparison

Each row is a [paired setup test](../../docs/definitions.md#metrics) of two setups on the same inputs.

### M

#### 2x2

| Validity | Metric | Setups | Inputs paired | A higher | B higher | Mean difference | p | Holm p | Significant |
|---|---|---|---|---|---|---|---|---|---|
| valid | success_rate | no_model vs descriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | success_rate | no_model vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | success_rate | descriptive vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | hallucination_rate | no_model vs descriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | hallucination_rate | no_model vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | hallucination_rate | descriptive vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| invalid | success_rate | no_model vs descriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| invalid | success_rate | no_model vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| invalid | success_rate | descriptive vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| invalid | hallucination_rate | no_model vs descriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| invalid | hallucination_rate | no_model vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| invalid | hallucination_rate | descriptive vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| invalid | mismatch_detection_rate | no_model vs descriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| invalid | mismatch_detection_rate | no_model vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| invalid | mismatch_detection_rate | descriptive vs prescriptive | 1 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |

## Metrics

### 2x2

| Setup | AI model | Depth | Validity | Attempts | Infra failures | Success | Hallucination | Mismatch detection | False mismatch | Malformed | Efficiency | Consistency | Latency (s) | Input tokens | Output tokens | Cost per success |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| no_model | M | 1 | valid | 2 | 0 | 0.50 (0.09–0.91) n=2 | 0.00 (0.00–0.66) n=2 | n/a n=0 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 1.00 | 0.50 | 1.75 | 10.0 | 5.0 | 0.0400 |
| no_model | M | 1 | invalid | 2 | 0 | 0.50 (0.09–0.91) n=2 | 0.00 (0.00–0.66) n=2 | 0.50 (0.09–0.91) n=2 | n/a n=0 | 0.50 (0.09–0.91) n=2 | n/a | 0.50 | 0.50 | 10.0 | 5.0 | 0.0400 |
| descriptive | M | 1 | valid | 2 | 0 | 0.50 (0.09–0.91) n=2 | 0.00 (0.00–0.66) n=2 | n/a n=0 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 1.00 | 0.50 | 1.75 | 10.0 | 5.0 | 0.0400 |
| descriptive | M | 1 | invalid | 2 | 0 | 0.50 (0.09–0.91) n=2 | 0.00 (0.00–0.66) n=2 | 0.50 (0.09–0.91) n=2 | n/a n=0 | 0.50 (0.09–0.91) n=2 | n/a | 0.50 | 0.50 | 10.0 | 5.0 | 0.0400 |
| prescriptive | M | 1 | valid | 2 | 0 | 0.50 (0.09–0.91) n=2 | 0.00 (0.00–0.66) n=2 | n/a n=0 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 1.00 | 0.50 | 1.75 | 10.0 | 5.0 | 0.0400 |
| prescriptive | M | 1 | invalid | 2 | 0 | 0.50 (0.09–0.91) n=2 | 0.00 (0.00–0.66) n=2 | 0.50 (0.09–0.91) n=2 | n/a n=0 | 0.50 (0.09–0.91) n=2 | n/a | 0.50 | 0.50 | 10.0 | 5.0 | 0.0400 |

## Attempts

### [2x2-d1-001](../../releases/1.0.0/inputs.jsonl#L1) (valid, depth 1)

| AI model | Setup | Attempt | Outcome | Moves | Mismatch | Input tokens (excl. retries) | Output tokens (excl. retries) | Latency (s) |
|---|---|---|---|---|---|---|---|---|
| M | no_model | 1 | success | R | false | 10 | 5 | 1.50 |
| M | no_model | 2 | failure | U | false | 10 | 5 | 2.00 |
| M | descriptive | 1 | success | R | false | 10 | 5 | 1.50 |
| M | descriptive | 2 | failure | U | false | 10 | 5 | 2.00 |
| M | prescriptive | 1 | success | R | false | 10 | 5 | 1.50 |
| M | prescriptive | 2 | failure | U | false | 10 | 5 | 2.00 |

### [2x2-d1-001-x](../../releases/1.0.0/inputs.jsonl#L2) (invalid, depth 1)

| AI model | Setup | Attempt | Outcome | Moves | Mismatch | Input tokens (excl. retries) | Output tokens (excl. retries) | Latency (s) |
|---|---|---|---|---|---|---|---|---|
| M | no_model | 1 | success |  | true | 10 | 5 | 0.50 |
| M | no_model | 2 | malformed_output |  | false | 10 | 5 | 0.50 |
| M | descriptive | 1 | success |  | true | 10 | 5 | 0.50 |
| M | descriptive | 2 | malformed_output |  | false | 10 | 5 | 0.50 |
| M | prescriptive | 1 | success |  | true | 10 | 5 | 0.50 |
| M | prescriptive | 2 | malformed_output |  | false | 10 | 5 | 0.50 |

## Raw responses

Not copied here. See [raw/](raw).
