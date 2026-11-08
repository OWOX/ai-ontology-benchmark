# Spec: docs/specs/ui.md
"""The live estimate behind `POST /api/estimate/live`: the numbers of `run --estimate` for a form that has not
been started, plus the time each AI model needs. Reads the release, prompts, and prices on `main` and the
experiment's branch through Bundles and GitData. Caches rendered prompts and latencies in memory. Writes nothing.
"""

import json
import threading
from statistics import median

from src.config import max_moves, parse_experiment_config
from src.evaluate.metrics import attempt_cost
from src.run.budget import estimate
from src.run.models import DECISION_PROVIDERS
from src.run.prompts import SETUPS, fill_template, parse_questions
from src.run.run import experiment_inputs
from ui import expdata, forms
from ui.bundle import Bundles
from ui.common import ApiError, missing_price_field, timed
from ui.gitdata import LOCAL_RESULTS, REMOTE_RESULTS

CACHE_LIMIT = 8
RELEASE_LIMIT = 4  # each holds every rendered prompt of a release
EXPERIMENT_LIMIT = 64
TOKEN_FIELDS = ("input_tokens", "output_tokens", "retry_input_tokens", "retry_output_tokens")


class _View:
    """What `forms.build_config` reads from Bundles, held for one main sha: the catalogue read with no keys
    (a missing key is allowed here) and the puzzles of each release."""

    def __init__(self, models: dict, puzzles) -> None:
        self._models, self.release_puzzles = models, puzzles

    def models(self, env: dict) -> dict:
        return self._models


class LiveEstimate:
    def __init__(self, bundles: Bundles) -> None:
        self.bundles = bundles
        self._lock = threading.Lock()
        self._main: dict[str, dict] = {}  # main sha -> view, prices, and the releases read
        self._releases: dict[tuple, dict] = {}  # (release, tree sha) -> inputs, templates, prompts, questions
        self._experiments: dict[tuple, dict] = {}  # (id, sha) -> the experiment as expdata loads it
        self._latency: tuple | None = None  # (key, medians)

    # --- caches ---------------------------------------------------------------------------

    def _at(self, main_sha: str | None) -> dict:
        """The catalogue, prices, and manifests of `main` at one sha, read once. The git reads are made outside the
        lock, so a slow read never blocks another call; a race reads twice and keeps the first."""
        with self._lock:
            held = self._main.get(main_sha)
        if held is not None:
            return held
        manifests = {}

        def puzzles(release: str):
            if release not in manifests:
                manifests[release] = self.bundles.manifest(release)
            found = manifests[release]
            return list(found["release_config"]["puzzles"]) if found else None

        # Read with the keys the page holds: a model with no key is allowed here, other reasons are not.
        held = {"view": _View(self.bundles.models({}), puzzles), "manifests": manifests,
                "prices": self.bundles.prices()}
        with self._lock:
            if len(self._main) >= CACHE_LIMIT:
                self._main.pop(next(iter(self._main)))
            return self._main.setdefault(main_sha, held)

    def _release(self, release: str, tree: str | None) -> dict:
        """What a release holds on `main`, kept per release and the sha of its tree, so a push that leaves the
        release alone keeps the rendered prompts. Everything is read from that tree, never from a later `main`.
        `lock` is held while prompts are rendered. The reads are made outside the global lock."""
        if tree is None:
            raise ApiError(400, f"releases/{release} is not on main")
        key = (release, tree)
        with self._lock:
            held = self._releases.get(key)
        if held is None:
            git = self.bundles.git
            try:
                manifest = json.loads(git.show(tree, "manifest.json") or "")
            except ValueError:
                raise ApiError(400, f"releases/{release}/manifest.json on main cannot be read") from None
            held = {"tree": tree, "manifest": manifest, "templates": {}, "prompts": {}, "questions": None,
                    "lock": threading.Lock(), "inputs": [json.loads(line) for line in (git.show(tree, "inputs.jsonl") or "").splitlines()
                               if line.strip()]}
            with self._lock:
                if len(self._releases) >= RELEASE_LIMIT:
                    self._releases.pop(next(iter(self._releases)))
                held = self._releases.setdefault(key, held)
        return held

    def _prompt(self, held: dict, release: str, row: dict, setup: str) -> str:
        key = row["input_id"], setup
        if key not in held["prompts"]:
            template_key = row["puzzle"], setup
            if template_key not in held["templates"]:
                path = f"prompts/{setup}/{row['puzzle']}.txt"
                text = self.bundles.git.show(held["tree"], path)
                if text is None:
                    raise ApiError(400, f"releases/{release}/{path} is not on main")
                held["templates"][template_key] = text
            held["prompts"][key] = fill_template(held["templates"][template_key], row, setup)
        return held["prompts"][key]

    def _questions(self, held: dict, release: str) -> dict:
        if held["questions"] is None:
            path = "prompts/decision/questions.txt"
            text = self.bundles.git.show(held["tree"], path)
            if text is None:
                raise ApiError(400, f"releases/{release}/{path} is not on main")
            try:
                held["questions"] = parse_questions(text, f"releases/{release}/{path}")
            except ValueError as error:
                raise ApiError(400, str(error)) from None
        return held["questions"]

    def _experiment(self, experiment_id: str, ref: str, sha: str) -> dict:
        """What the estimate needs of one experiment branch, kept per ref sha, the oldest dropped past a limit:
        `error`, the attempt keys and token sums of each AI model, and its (model, latency) pairs. Raw responses
        are not kept."""
        with self._lock:
            held = self._experiments.get((experiment_id, sha))
        if held is None:
            git = self.bundles.git
            held = {"missing": git.show(ref, f"results/{experiment_id}/experiment.toml") is None,
                    "error": None, "bad": None, "keys": {}, "tokens": {}, "latencies": []}
            exp = ({"error": None, "records": {}} if held["missing"]
                   else expdata.load_experiment(git, experiment_id, ref, git.main_ref()))
            held["error"] = exp["error"]
            for name, records in exp["records"].items():
                for number, r in enumerate(records, 1):
                    model = r.get("model", name)
                    fields = [r.get(f) for f in TOKEN_FIELDS]
                    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in fields):
                        held["bad"] = held["bad"] or f"record {number} of raw/{name}.jsonl has a token field that is not a number"
                        continue
                    held["keys"].setdefault(model, set()).add((r.get("input_id"), r.get("setup"), model,
                                                               r.get("attempt_number")))
                    tin, tout = held["tokens"].get(model, (0, 0))
                    held["tokens"][model] = (tin + fields[0] + fields[2], tout + fields[1] + fields[3])
                    if timed(r):
                        held["latencies"].append((model, r["latency_s"]))
            with self._lock:
                if len(self._experiments) >= EXPERIMENT_LIMIT:
                    self._experiments.pop(next(iter(self._experiments)))
                self._experiments[experiment_id, sha] = held
        return held

    def medians(self, remote: dict[str, str]) -> dict[str, tuple[float, int]]:
        """The median `latency_s` and the record count of each AI model over every pushed experiment, outcome
        `infrastructure_failure` left out. Cached by the shas of the refs read. A branch that does not load adds
        what it could read."""
        key = tuple(sorted(remote.items()))
        with self._lock:
            if self._latency and self._latency[0] == key:
                return self._latency[1]
        values: dict[str, list[float]] = {}
        for experiment_id, sha in sorted(remote.items()):
            for model, latency in self._experiment(experiment_id, REMOTE_RESULTS + experiment_id, sha)["latencies"]:
                values.setdefault(model, []).append(latency)
        found = {m: (median(v), len(v)) for m, v in values.items()}
        with self._lock:
            self._latency = (key, found)
        return found

    # --- the estimate ---------------------------------------------------------------------

    def live(self, form: dict, parallel: int, env: dict) -> dict:
        if not isinstance(form, dict):
            raise ApiError(400, "body must be a JSON object")
        main_sha, local, remote = self.bundles.git.results_state()
        at = self._at(main_sha)
        text = forms.config_text(at["view"], form, env, keyless_ok=True)
        try:
            config = parse_experiment_config(text, form["id"], f"{form['id']}.toml")
        except ValueError as error:
            raise ApiError(400, str(error)) from None
        prices = at["prices"]
        for model in config["models"]:
            if model["name"] not in prices:
                raise ApiError(400, f"no prices for model {model['name']!r} in config/prices.toml on main")
            field = missing_price_field(prices[model["name"]])
            if field:
                raise ApiError(400, f"config/prices.toml on main: model {model['name']!r} has no number for {field}")
        release = config["release"]
        tree = self.bundles.git.tree_sha(main_sha or "HEAD", f"releases/{release}")
        held = self._release(release, tree)
        manifest = held["manifest"]
        names = [m["name"] for m in config["models"]]
        done, spent = self._branch(config, form["id"], prices, local, remote)
        rows = experiment_inputs(config, held["inputs"])
        pending = [(row, model, setup, number) for row in rows for model in config["models"] for setup in SETUPS
                   for number in range(1, config["attempts"] + 1)
                   if (row["input_id"], setup, model["name"], number) not in done]
        decision = any(m["provider"] in DECISION_PROVIDERS for _, m, _, _ in pending)
        with held["lock"]:
            questions = self._questions(held, release) if decision else None
        prompts = {}
        with held["lock"]:  # two cold calls render once
            for row, _, setup, _ in pending:
                if (row["input_id"], setup) not in prompts:
                    prompts[row["input_id"], setup] = self._prompt(held, release, row, setup)
        release_config = manifest["release_config"]
        caps = {p: max_moves(config, release_config, p) for p in release_config["puzzles"]}
        result = estimate(config, pending, prices, questions, None, caps, prompts,
                          bool(manifest.get("mismatch_reasons", False)), {n: spent.get(n, 0.0) for n in names})
        return self._finish(result, config, parallel, len(rows), len(pending), remote)

    def _branch(self, config: dict, experiment_id: str, prices: dict, local: dict, remote: dict
                ) -> tuple[set, dict[str, float]]:
        """The (input id, setup, model, attempt number) keys with a record on the experiment's branch, local first,
        then origin, and the cost of those records per AI model."""
        if experiment_id in local:
            ref, sha = LOCAL_RESULTS + experiment_id, local[experiment_id]
        elif experiment_id in remote:
            ref, sha = REMOTE_RESULTS + experiment_id, remote[experiment_id]
        else:
            return set(), {}
        found = self._experiment(experiment_id, ref, sha)
        if found["missing"]:  # a branch with no experiment.toml is no experiment
            return set(), {}
        if found["error"] or found["bad"]:
            raise ApiError(400, f"experiment {experiment_id} cannot be read: {found['error'] or found['bad']}")
        done, spent = set(), {}
        for name in (m["name"] for m in config["models"]):
            done |= found["keys"].get(name, set())
            tin, tout = found["tokens"].get(name, (0, 0))
            spent[name] = attempt_cost({"input_tokens": tin, "output_tokens": tout, "retry_input_tokens": 0,
                                        "retry_output_tokens": 0}, prices[name])
        return done, spent

    def _finish(self, result: dict, config: dict, parallel: int, inputs: int, to_run: int, remote: dict) -> dict:
        medians = self.medians(remote)
        budget = config["budget"]
        times = []
        for m in result["models"]:
            found = medians.get(m["name"])
            m["median_latency_s"], m["latency_n"] = (found[0], found[1]) if found else (None, 0)
            m["time_s"] = 0.0 if m["attempts"] == 0 else (
                m["attempts"] * found[0] / parallel if found else None)
            m["over"] = (m["worst_case_usd"] + m["spent_usd"] > budget["per_model_usd"] + 1e-9
                         or m["max_request_usd"] > budget["per_request_usd"] + 1e-9)
            times.append(m["time_s"])
        total = result["total"]
        partial = any(t is None for t in times)
        total["time_s"] = None if partial else max(times, default=0.0)
        total["over"] = total["worst_case_usd"] + total["spent_usd"] > budget["per_experiment_usd"] + 1e-9
        result["timing"] = "partial" if partial else "full"
        planned = inputs * len(config["models"]) * len(SETUPS) * config["attempts"]
        result["counts"] = {"inputs": inputs, "models": len(config["models"]), "setups": len(SETUPS),
                            "attempts": config["attempts"], "planned": planned, "done": planned - to_run,
                            "to_run": to_run}
        return result
