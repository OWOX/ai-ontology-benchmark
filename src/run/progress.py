# Spec: docs/specs/run.md
"""Live progress of one `run` process. Reads the records handed in and the prices in config.
Writes to the terminal (rich) or, when stdout is not a terminal, one plain line per attempt.
Display only: nothing here goes into a raw record.
"""

import sys
from collections import Counter

from src.evaluate.metrics import attempt_cost

NA = "n/a"


class Tally:
    """Counts of the records of one AI model, or of all of them."""

    def __init__(self) -> None:
        self.attempts = self.tokens_in = self.tokens_out = 0
        self.cost = 0.0
        self.outcomes: Counter = Counter()
        self.valid = self.invalid = self.flagged_valid = self.flagged_invalid = 0

    def add(self, record: dict, price: dict) -> None:
        self.attempts += 1
        self.tokens_in += record["input_tokens"] + record["retry_input_tokens"]
        self.tokens_out += record["output_tokens"] + record["retry_output_tokens"]
        self.cost += attempt_cost(record, price)
        self.outcomes[record["outcome"]] += 1
        if record["outcome"] == "infrastructure_failure":
            return  # left out of every rate
        if record["validity"] == "invalid":
            self.invalid += 1
            self.flagged_invalid += bool(record["mismatch"])
        else:
            self.valid += 1
            self.flagged_valid += bool(record["mismatch"])

    @property
    def counted(self) -> int:
        return self.attempts - self.outcomes["infrastructure_failure"]

    def share(self, hits: int, n: int) -> str:
        return f"{round(100 * hits / n)}%" if n else NA

    def rate(self, outcome: str) -> str:
        return self.share(self.outcomes[outcome], self.counted)

    def detection(self) -> str:
        return self.share(self.flagged_invalid, self.invalid)

    def false_mismatch(self) -> str:
        return self.share(self.flagged_valid, self.valid)


class Progress:
    def __init__(self, config: dict, prices: dict, totals: dict, prior_records: list[dict], console=None):
        """`totals` maps (model name, puzzle) to attempts recorded plus attempts still to run."""
        self.prices = prices
        self.totals = totals
        self.names = [m["name"] for m in config["models"] if any(k[0] == m["name"] for k in totals)]
        self.by_model = {name: Tally() for name in self.names}
        self.done: Counter = Counter()
        self.total = Tally()
        self.last: dict | None = None
        self.console = console
        self.live = None
        for record in prior_records:
            self.count(record)

    def count(self, record: dict) -> None:
        model = record["model"]
        if model not in self.by_model:
            return
        self.by_model[model].add(record, self.prices[model])
        self.total.add(record, self.prices[model])
        self.done[(model, record["puzzle"])] += 1

    @property
    def goal(self) -> int:
        return sum(self.totals.values())

    def __enter__(self) -> "Progress":
        terminal = self.console.is_terminal if self.console else sys.stdout.isatty()
        if terminal:
            try:
                self.start_live()
            except ImportError:  # an old venv without rich still runs
                self.live = None
        return self

    def __exit__(self, *exc) -> None:
        if self.live:
            self.live.stop()
            self.live = None

    def update(self, record: dict) -> None:
        self.count(record)
        self.last = record
        if self.live:
            self.refresh_live()
        else:
            print(self.plain_line(record), flush=True)

    def plain_line(self, record: dict) -> str:
        t = self.total
        return (f"[{t.attempts}/{self.goal}] {record['model']} {record['puzzle']} {record['input_id']} "
                f"{record['setup']} #{record['attempt_number']} {record['outcome']} | "
                f"in {t.tokens_in} out {t.tokens_out} | ${t.cost:.4f} | "
                f"success {t.rate('success')} hallucination {t.rate('hallucination')} "
                f"malformed {t.rate('malformed_output')} truncated {t.rate('truncated')} "
                f"abstention {t.rate('abstention')} format error {t.rate('format_error')}")

    # rich path, imported only when stdout is a terminal

    def start_live(self) -> None:
        from rich.console import Console, Group
        from rich.live import Live
        from rich.progress import (BarColumn, MofNCompleteColumn, Progress as Bars, TextColumn,
                                   TimeElapsedColumn, TimeRemainingColumn)
        from rich.table import Table
        from rich.text import Text
        self.Table, self.Text = Table, Text
        self.console = self.console or Console()
        self.bars = Bars(TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(),
                         TimeElapsedColumn(), TimeRemainingColumn(), console=self.console)
        self.global_task = self.bars.add_task("all attempts", total=self.goal, completed=self.total.attempts)
        self.tasks = {key: self.bars.add_task(f"{key[0]} {key[1]}", total=n, completed=self.done[key])
                      for key, n in sorted(self.totals.items())}
        self.group = Group(self.bars, self.table(), self.last_line())
        self.live = Live(self.group, console=self.console, refresh_per_second=4)
        self.live.start()

    def refresh_live(self) -> None:
        from rich.console import Group
        self.bars.update(self.global_task, completed=self.total.attempts)
        for key, task in self.tasks.items():
            self.bars.update(task, completed=self.done[key])
        self.live.update(Group(self.bars, self.table(), self.last_line()))

    def last_line(self):
        r = self.last
        if not r:
            return self.Text("last attempt: none yet")
        return self.Text(f"last attempt: {r['model']} {r['puzzle']} {r['input_id']} {r['setup']} "
                         f"#{r['attempt_number']} {r['outcome']}")

    def table(self):
        table = self.Table()
        for title in ("AI model", "attempts", "input tokens*", "output tokens*", "cost USD", "success",
                      "hallucination", "malformed", "truncated", "abstention", "format error", "mismatch detection", "false mismatch", "infra failures"):
            table.add_column(title, justify="left" if title == "AI model" else "right")
        for name, t in [*self.by_model.items(), ("total", self.total)]:
            table.add_row(name, str(t.attempts), str(t.tokens_in), str(t.tokens_out), f"{t.cost:.4f}",
                          t.rate("success"), t.rate("hallucination"), t.rate("malformed_output"),
                          t.rate("truncated"), t.rate("abstention"), t.rate("format_error"),
                          t.detection(), t.false_mismatch(), str(t.outcomes["infrastructure_failure"]))
        table.caption = "* retry tokens included"
        return table
