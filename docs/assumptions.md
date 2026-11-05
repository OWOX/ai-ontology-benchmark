# Assumptions

What the study takes as given. If one turns out false, the results built on it need a second look. Terms are defined in [definitions.md](definitions.md).

1. Twisty puzzles are deterministic. A move applied to a state always gives the same next state.
2. AI models already know the standard notation for each puzzle, such as Singmaster for 3x3, from their training data. That makes the no-model setup a fair test. The descriptive model restates the notation anyway.
3. Every valid input describes exactly one puzzle state, so an AI model can't blame an ambiguous input.
4. An impossible move is an objective error. A script can count it, and nobody has to judge it.
5. An invalid input can't be reached from the solved state by legal moves, so no answer can solve it and flagging it is objectively correct. This holds even when the corrupted state could be assembled by taking a physical puzzle apart.
6. The fifth puzzle is tetrahedral. This still needs confirmation, and so do the exact octahedral and tetrahedral puzzles.
7. The code is in Python, so that Cube Bench's simulator can be reused as planned.
