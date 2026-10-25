# Spec: docs/specs/ui.md
"""Builds the per-release bundle and keeps it in memory, keyed by the shas it was read at.
Reads `main` and the `results/*` refs through GitData, and the API keys through ui.secrets.
Writes nothing. A build, including its fetch, runs under one lock.
"""

import copy
import json
import threading
import tomllib
from pathlib import Path

from src.config import RELEASE_PATTERN
from src.release.release import parse_version
from src.run.models import KEY_VARIABLES
from ui import expdata, secrets
from ui.common import ApiError
from ui.experiments import DEFAULTS
from ui.gitdata import REMOTE_RESULTS, GitData
from ui.puzzleinfo import build_puzzle

PROVIDER_ORDER = ("anthropic", "openai", "google", "fake")
NO_KEY = "no API key: add it under Models"
NO_PRICE = "no price in config/prices.toml"
CACHE_LIMIT = 16


def config_form(config: dict, release_puzzles: list[str]) -> dict:
    """The experiment form (spec: HTTP API item 5) for a parsed experiment config."""
    return {"id": config["experiment_id"], "release": config["release"],
            "puzzles": list(config.get("puzzles") or release_puzzles),
            "models": [m["name"] for m in config["models"]], "attempts": config["attempts"],
            "retry_cap": config["retry_cap"], "max_output_tokens": config["max_output_tokens"],
            "budget": dict(config["budget"])}


class Bundles:
    def __init__(self, root: Path, git: GitData) -> None:
        self.root, self.git = Path(root), git
        self._lock = threading.Lock()
        self._cache: dict[tuple, dict] = {}

    # --- small readers, all from main -------------------------------------------------------

    def _manifest(self, release: str) -> dict | None:
        text = self.git.show(self.git.main_ref(), f"releases/{release}/manifest.json")
        try:
            found = json.loads(text) if text is not None else None
        except ValueError:
            return None
        return found if isinstance(found, dict) else None

    def releases(self) -> list[str]:
        main = self.git.main_ref()
        found = [v for v in self.git.ls(main, "releases")
                 if RELEASE_PATTERN.fullmatch(v) and "manifest.json" in self.git.ls(main, f"releases/{v}")]
        return sorted(found, key=parse_version, reverse=True)

    def _catalogue(self) -> list[dict]:
        try:
            entries = tomllib.loads(self.git.show(self.git.main_ref(), "config/models.toml") or "").get("models", [])
        except tomllib.TOMLDecodeError:
            return []
        return [e for e in entries if isinstance(e, dict) and {"name", "provider", "api_model_id"} <= set(e)]

    def _prices(self) -> dict:
        main = self.git.main_ref()
        try:
            return tomllib.loads(self.git.show(main, "config/prices.toml") or "")
        except tomllib.TOMLDecodeError:
            return {}

    # --- flags shared by the bundle rows and the detail ------------------------------------

    def _flags(self, exp: dict, live_ids: set[str], base: str | None) -> dict:
        remote = self.git.sha(REMOTE_RESULTS + exp["id"])
        branch = f"{base}/tree/{exp['sha']}/results/{exp['id']}" if base and exp["sha"] else None
        return {"pushed": remote is not None and remote == exp["sha"], "running": exp["id"] in live_ids,
                "branch": branch}

    def _is_mirror(self, release: str, other: str | None) -> bool:
        if other is None or other not in self.releases():
            return False
        if other == release:
            return True
        a, b = self._manifest(release), self._manifest(other)
        return bool(a and b and parse_version(release)[:2] == parse_version(other)[:2]
                    and a.get("files", {}).get("inputs.jsonl") == b.get("files", {}).get("inputs.jsonl"))

    # --- the bundle ------------------------------------------------------------------------

    def get(self, release: str | None, refresh: bool, live_ids: set[str], env: dict) -> dict:
        with self._lock:
            if refresh or self.git.fetched_at is None and self.git.fetch_error is None:
                self.git.fetch(force=refresh)
            versions = self.releases()
            if release is not None and release not in versions:
                raise ApiError(400, f"field 'release' must be one of {', '.join(versions) or '(none)'}")
            release = release or (versions[0] if versions else None)
            refs = self.git.results_refs(live_ids)
            main_sha = self.git.sha(self.git.main_ref())
            key = (release, main_sha, tuple(sorted((i, self.git.sha(r)) for i, r in refs.items())),
                   frozenset(live_ids))
            if key not in self._cache:
                if len(self._cache) >= CACHE_LIMIT:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = self._build(release, versions, refs, main_sha, live_ids)
            bundle = copy.deepcopy(self._cache[key])
            bundle["fetched_at"], bundle["fetch_error"] = self.git.fetched_at, self.git.fetch_error
        return self._fill_keys(bundle, env)

    def _fill_keys(self, bundle: dict, env: dict) -> dict:
        status = secrets.inspect(self.root)
        for provider in bundle["providers"]:
            info = status.get(provider["name"])
            provider["key"] = {"source": info["source"], "tail": info["tail"]} if info else {"source": "none", "tail": ""}
            have = info is None or bool(env.get(provider["variable"])) or info["configured"]
            for model in provider["models"]:
                if model["disabled_reason"] is None and not have:
                    model["disabled_reason"] = NO_KEY
        return bundle

    def _load_all(self, refs: dict[str, str], main: str) -> list[dict]:
        loaded = (expdata.load_experiment(self.git, i, ref, main) for i, ref in sorted(refs.items()))
        return [e for e in loaded if not (e["config"] is None and (e["error"] or "").endswith("file not found"))]

    def _build(self, release: str | None, versions: list[str], refs: dict[str, str], main_sha: str | None,
               live_ids: set[str]) -> dict:
        main, base = self.git.main_ref(), self.git.github()

        def link(path: str) -> str | None:
            return f"{base}/blob/{main_sha}/{path}" if base and main_sha else None

        manifest = self._manifest(release) if release else None
        inputs_by_release: dict[str, list[dict]] = {}
        catalogue = {e["name"]: e for e in self._catalogue()}
        experiments, rows = [], []
        for exp in self._load_all(refs, main):
            config = exp["config"]
            if config is not None and not self._is_mirror(release, config["release"]):
                continue
            experiments.append(exp)
            inputs = inputs_by_release.setdefault(config["release"], expdata.read_inputs(self.git, main, config["release"])) \
                if config else []
            flags = self._flags(exp, live_ids, base)
            for row in expdata.experiment_rows(exp, inputs):
                entry = next((m for m in config["models"] if m["name"] == row["model"]), None) if config else None
                known = catalogue.get(row["model"])
                differs = entry is not None and (known is None or any(
                    entry.get(f, {} if f == "params" else None) != known.get(f, {} if f == "params" else None)
                    for f in ("provider", "api_model_id", "params")))
                rows.append({**row, **flags, "differs_from_catalogue": differs})
        names = list(manifest["release_config"]["puzzles"]) if manifest else []
        puzzles = [build_puzzle(self.git, main, link, release, manifest,
                                name, inputs_by_release.setdefault(release, expdata.read_inputs(self.git, main, release)),
                                experiments) for name in names]
        return {"schema": 1, "release": release, "releases": versions, "fetched_at": None, "fetch_error": None,
                "repo": base, "main_sha": main_sha, "defaults": DEFAULTS,
                "providers": self._providers(catalogue, experiments), "puzzles": puzzles, "experiments": rows,
                "about": {"markdown": self.git.show(main, "README.md"), "source": link("README.md")}}

    def _providers(self, catalogue: dict[str, dict], experiments: list[dict]) -> list[dict]:
        prices = self._prices()
        used: dict[tuple, list[str]] = {}
        for exp in experiments:
            for m in exp["config"]["models"] if exp["config"] else []:
                used.setdefault((m["provider"], m["api_model_id"]), []).append(exp["id"])
        names = list(PROVIDER_ORDER) + sorted({e["provider"] for e in catalogue.values()} - set(PROVIDER_ORDER))
        out = []
        for name in names:
            models = []
            for e in (e for e in catalogue.values() if e["provider"] == name):
                price = prices.get(e["name"])
                ok = isinstance(price, dict) and {"price_input_per_mtok", "price_output_per_mtok"} <= set(price)
                models.append({"name": e["name"], "api_model_id": e["api_model_id"], "params": e.get("params", {}),
                               "price": {"input_per_mtok": price["price_input_per_mtok"],
                                         "output_per_mtok": price["price_output_per_mtok"]} if ok else None,
                               "disabled_reason": None if ok else NO_PRICE,
                               "experiments": sorted(set(used.get((name, e["api_model_id"]), [])))})
            out.append({"name": name, "variable": KEY_VARIABLES.get(name), "key": None, "models": models})
        return out

    # --- the other routes ------------------------------------------------------------------

    def experiment(self, experiment_id: str, live_ids: set[str]) -> dict:
        ref = self.git.results_refs(live_ids).get(experiment_id)
        main = self.git.main_ref()
        exp = expdata.load_experiment(self.git, experiment_id, ref, main) if ref else None
        if exp is None or (exp["config"] is None and (exp["error"] or "").endswith("file not found")):
            raise ApiError(404, f"experiment '{experiment_id}' not found")
        config, base = exp["config"], self.git.github()
        inputs = expdata.read_inputs(self.git, main, config["release"]) if config else []
        metric_rows, summary_rows, source = expdata.detail_metrics(exp, inputs)
        manifest = self._manifest(config["release"]) if config else None
        puzzles = list(manifest["release_config"]["puzzles"]) if manifest else []
        version = exp["report_version"]
        report = None if version is None else {
            "version": version, "markdown": exp["report_md"],
            "source": f"{base}/blob/{exp['sha']}/results/{experiment_id}/{version}.md" if base else None}
        served = {m: sorted({r["served_model"] for r in found if r.get("served_model")})
                  for m, found in exp["records"].items()}
        return {"id": experiment_id, "release": config["release"] if config else None,
                "config": config_form(config, puzzles) if config else None,
                **self._flags(exp, live_ids, base), "metrics_source": source, "report": report,
                "metric_rows": metric_rows, "summary_rows": summary_rows, "served_models": served,
                "error": exp["error"]}

    def inputs(self, release: str, puzzle: str) -> list[dict]:
        manifest = self._manifest(release)
        if manifest is None:
            raise ApiError(400, "field 'release' is not a release on main")
        if puzzle not in manifest["release_config"]["puzzles"]:
            raise ApiError(400, "field 'puzzle' is not a puzzle of this release")
        fields = ("input_id", "scramble_depth", "validity", "state", "scramble", "source_input_id", "corruption")
        return [{f: r.get(f) for f in fields} for r in expdata.read_inputs(self.git, self.git.main_ref(), release)
                if r["puzzle"] == puzzle]

    def branches(self) -> list[dict]:
        local, remote = self.git.local_ids(), self.git.remote_ids()
        out = []
        for i in sorted(local | remote):
            texts = {side: self.git.show(prefix + i, f"results/{i}/experiment.toml")
                     for side, ids, prefix in (("local", local, "refs/heads/results/"),
                                               ("remote", remote, REMOTE_RESULTS)) if i in ids}
            texts = {side: t for side, t in texts.items() if t is not None}
            if not texts:
                continue
            try:
                release = tomllib.loads(next(iter(texts.values()))).get("release")
            except tomllib.TOMLDecodeError:
                release = None
            out.append({"id": i, "release": release, "local": "local" in texts, "remote": "remote" in texts})
        return out
