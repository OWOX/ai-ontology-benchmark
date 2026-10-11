# Related work

Papers close to this study, grouped by the question they share with it. Each entry says what it does and where this study differs.

## Cubes and other puzzles with checkable moves

1. Cube Bench: A Benchmark for Spatial Visual Reasoning in MLLMs. [arXiv:2512.20595](https://arxiv.org/abs/2512.20595), [code](https://github.com/dana-23/cube-bench). Tests multimodal models on 3x3 cube skills, from reading faces to choosing the next move, and scores progress as distance to solved. This study plans to reuse its 3x3 simulator code. It won't use its prompts or evaluation.
2. CubeBench: Diagnosing Interactive, Long-Horizon Spatial Reasoning Under Partial Observations. [arXiv:2512.23328](https://arxiv.org/abs/2512.23328). Uses the cube to test agents that track state over many steps and explore under partial observation.
3. Empirical Evidence of Complexity-Induced Limits in Large Language Models on Finite Discrete State-Space Problems with Explicit Validity Constraints. [arXiv:2604.13371](https://arxiv.org/abs/2604.13371). Covers the cube among other finite puzzles and lists illegal notation as one of its failure modes. That is the closest existing match to this study's definition of hallucination.
4. On the Limits of Innate Planning in Large Language Models. [arXiv:2511.21591](https://arxiv.org/abs/2511.21591). On the 8-puzzle, models without tools often make invalid moves, which the authors put down to a fragile internal picture of the puzzle state.
5. The Illusion of Thinking. [arXiv:2506.06941](https://arxiv.org/abs/2506.06941). Uses Tower of Hanoi and other puzzles with controlled difficulty, and finds that reasoning models collapse past a certain complexity.
6. PlanBench. [arXiv:2206.10498](https://arxiv.org/abs/2206.10498). A planning benchmark in Blocksworld-style domains where an external tool checks every plan rather than a person or a model.

## Rules in the prompt

1. Can LLMs Follow Simple Rules? [arXiv:2311.04235](https://arxiv.org/abs/2311.04235). Gives models explicit rules in the prompt and checks with code whether they keep them.
2. Evaluating Large Language Models with Grid-Based Game Competitions. [arXiv:2407.07796](https://arxiv.org/abs/2407.07796). Gives the same game rules in different prompt formats and counts invalid moves as disqualifications.
3. LudoBench. [arXiv:2604.05681](https://arxiv.org/abs/2604.05681). Puts the full rules in the prompt for Ludo and studies the moves models choose.

## Hallucination and inputs that can't exist

1. HalluLens: LLM Hallucination Benchmark. [arXiv:2504.17550](https://arxiv.org/abs/2504.17550). A hallucination taxonomy and benchmark. This study narrows hallucination to one countable event, an impossible move.
2. Do Large Language Models Know What They Don't Know? [arXiv:2305.18153](https://arxiv.org/abs/2305.18153). Tests whether models recognize questions they can't answer.
3. Unsolvable Problem Detection. [arXiv:2403.20331](https://arxiv.org/abs/2403.20331). Asks whether multimodal models notice when a question has no valid answer.
4. From Blind Solvers to Logical Thinkers. [arXiv:2410.18921](https://arxiv.org/abs/2410.18921). Uses deliberately faulty math problems to test whether models solve them anyway.
5. Learning the Boundary of Solvability. [arXiv:2512.01661](https://arxiv.org/abs/2512.01661). Makes unsolvable problems by injecting contradictions and trains models to detect them.

## The gap

Among these papers, none gives the same frozen inputs to several models under three levels of rules in the prompt (none, an explanation, or a fixed move list) and then measures success rate, impossible moves, and detection of invalid inputs with one deterministic validator. That combination is what this study adds.
