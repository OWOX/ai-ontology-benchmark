# Experiment e1 on release 1.0.0

Release: [1.0.0, tag `release-1.0.0`](../../releases/1.0.0/README.md)

The experiment ran on release 1.0.0. This report is not a mirror.

Assessment hash: `<hash>`

Inputs: [inputs.jsonl](../../releases/1.0.0/inputs.jsonl). Prompts: [prompts/](../../releases/1.0.0/prompts).

## Experiment

Config: [experiment.toml](experiment.toml)

| AI model | Provider | API model id | Kind | Served model ids | Params |
|---|---|---|---|---|---|
| A | fake | a-1 | not set | fake | provider defaults |

Attempts per input, model and setup: 2. Retry cap: 3. Maximum output tokens: 100.


Torn raw lines skipped: 0.

Token prices per million tokens, from [prices.toml](prices.toml):

| AI model | Input | Output |
|---|---|---|
| A | 1.0 | 2.0 |

Budgets in force (USD): request 2.0, AI model 25.0, experiment 50.0.

Cost spent, at the prices above (USD):

| AI model | Spent |
|---|---|
| A | 0.0000 |
| Total | 0.0000 |

## Summary

### A

#### Valid inputs

| Metric | no_model | descriptive | prescriptive |
|---|---|---|---|
| Success rate | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 |
| Hallucination rate | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 |
| False mismatch rate | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 |
| Malformed output rate | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 |
| Truncation rate | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 |
| Abstention rate | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 |
| Format error rate | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 |
| Cost per success | n/a | n/a | n/a |

#### Invalid inputs

| Metric | no_model | descriptive | prescriptive |
|---|---|---|---|
| Success rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| Mismatch detection rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| Hallucination rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| Malformed output rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| Truncation rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| Abstention rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |
| Format error rate | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 |

## Setup comparison

Each row is a [paired setup test](../../docs/definitions.md#metrics) of two setups on the same inputs.

### A

#### 2x2

| Validity | Metric | Setups | Inputs paired | A higher | B higher | Mean difference | p | Holm p | Significant |
|---|---|---|---|---|---|---|---|---|---|
| valid | success_rate | no_model vs descriptive | 2 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | success_rate | no_model vs prescriptive | 2 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | success_rate | descriptive vs prescriptive | 2 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | hallucination_rate | no_model vs descriptive | 2 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | hallucination_rate | no_model vs prescriptive | 2 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
| valid | hallucination_rate | descriptive vs prescriptive | 2 | 0 | 0 | 0.00 | 1.000 | 1.000 | no |
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

| Setup | AI model | Depth | Validity | Attempts | Infra failures | Success | Hallucination | Mismatch detection | False mismatch | Malformed | Truncated | Abstention | Format error | Consistency | Latency (s) | Input tokens | Output tokens | Cost per success |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| no_model | A | 1 | valid | 4 | 0 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | n/a n=0 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 1.00 | 0.00 | 0.0 | 0.0 | n/a |
| no_model | A | 1 | invalid | 2 | 0 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | n/a n=0 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 1.00 | 0.00 | 0.0 | 0.0 | n/a |
| descriptive | A | 1 | valid | 4 | 0 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | n/a n=0 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 1.00 | 0.00 | 0.0 | 0.0 | n/a |
| descriptive | A | 1 | invalid | 2 | 0 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | n/a n=0 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 1.00 | 0.00 | 0.0 | 0.0 | n/a |
| prescriptive | A | 1 | valid | 4 | 0 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | n/a n=0 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 0.00 (0.00–0.49) n=4 | 1.00 | 0.00 | 0.0 | 0.0 | n/a |
| prescriptive | A | 1 | invalid | 2 | 0 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | n/a n=0 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 0.00 (0.00–0.66) n=2 | 1.00 | 0.00 | 0.0 | 0.0 | n/a |

## Attempts

### [2x2-d1-001](../../releases/1.0.0/inputs.jsonl#L1) (valid, depth 1)

| AI model | Setup | Attempt | Outcome | Moves | Mismatch | Input tokens (excl. retries) | Output tokens (excl. retries) | Latency (s) |
|---|---|---|---|---|---|---|---|---|
| A | no_model | 1 | failure | U | false | 0 | 0 | 0.00 |
| A | no_model | 2 | failure | U | false | 0 | 0 | 0.00 |
| A | descriptive | 1 | failure | U | false | 0 | 0 | 0.00 |
| A | descriptive | 2 | failure | U | false | 0 | 0 | 0.00 |
| A | prescriptive | 1 | failure | U | false | 0 | 0 | 0.00 |
| A | prescriptive | 2 | failure | U | false | 0 | 0 | 0.00 |

### [2x2-d1-001-x](../../releases/1.0.0/inputs.jsonl#L2) (invalid, depth 1)

| AI model | Setup | Attempt | Outcome | Moves | Mismatch | Input tokens (excl. retries) | Output tokens (excl. retries) | Latency (s) |
|---|---|---|---|---|---|---|---|---|
| A | no_model | 1 | failure | U | false | 0 | 0 | 0.00 |
| A | no_model | 2 | failure | U | false | 0 | 0 | 0.00 |
| A | descriptive | 1 | failure | U | false | 0 | 0 | 0.00 |
| A | descriptive | 2 | failure | U | false | 0 | 0 | 0.00 |
| A | prescriptive | 1 | failure | U | false | 0 | 0 | 0.00 |
| A | prescriptive | 2 | failure | U | false | 0 | 0 | 0.00 |

### [2x2-d1-002](../../releases/1.0.0/inputs.jsonl#L3) (valid, depth 1)

| AI model | Setup | Attempt | Outcome | Moves | Mismatch | Input tokens (excl. retries) | Output tokens (excl. retries) | Latency (s) |
|---|---|---|---|---|---|---|---|---|
| A | no_model | 1 | failure | U | false | 0 | 0 | 0.00 |
| A | no_model | 2 | failure | U | false | 0 | 0 | 0.00 |
| A | descriptive | 1 | failure | U | false | 0 | 0 | 0.00 |
| A | descriptive | 2 | failure | U | false | 0 | 0 | 0.00 |
| A | prescriptive | 1 | failure | U | false | 0 | 0 | 0.00 |
| A | prescriptive | 2 | failure | U | false | 0 | 0 | 0.00 |

## Raw responses

Not copied here. See [raw/](raw).
