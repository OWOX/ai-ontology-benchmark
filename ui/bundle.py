# Spec: docs/specs/ui.md
"""Builds the per-release bundle and keeps it in memory, keyed by the shas it was read at.
Reads `main` and the `results/*` refs through GitData, and the API keys through ui.secrets.
Writes nothing. A build, including its fetch, runs under one lock.
"""

import copy
import json
import re
import threading
import tomllib
from pathlib import Path

from src.config import RELEASE_PATTERN
from src.release.release import parse_version
from src.puzzles.registry import ENGINES
from src.run.prompts import SETUPS
from ui import benchmarks, expdata, secrets
from ui.branches import BranchReaders
from ui.catalogue import PROVIDER_ORDER, build_providers, config_form
from ui.common import ApiError
from ui.experiments import DEFAULTS
from ui.gitdata import REMOTE_RESULTS, GitData
from ui.puzzleinfo import build_puzzle

NO_KEY = "no API key: add it under Models"
NO_ACCOUNT = "no account id: add it under Models"
CACHE_LIMIT = 16


def metric_definitions(markdown: str | None) -> dict[str, str]:
    """Each numbered item under `## Metrics` in docs/definitions.md, keyed by its bold term, as plain text:
    links keep their text and backticks are dropped."""
    section = re.search(r"^## Metrics\n(.*?)(?=^## |\Z)", markdown or "", re.M | re.S)
    out = {}
    for term, text in re.findall(r"^\d+\. \*\*(.+?)\.\*\* (.+)$", section.group(1) if section else "", re.M):
        out[term] = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text).replace("`", "")
    return out


def is_mirror(release: str, other: str | None, manifests: dict[str, dict | None]) -> bool:
    """True when `other` is `release` or a mirror of it: same major and minor, same inputs.jsonl hash."""
    if other is None or other not in manifests:
        return False
    if other == release:
        return True
    a, b = manifests.get(release), manifests[other]
    return bool(a and b and parse_version(release)[:2] == parse_version(other)[:2]
                and a.get("files", {}).get("inputs.jsonl") == b.get("files", {}).get("inputs.jsonl"))


class Bundles(BranchReaders):
    def __init__(self, root: Path, git: GitData) -> None:
        self.root, self.git = Path(root), git
        self._lock = threading.Lock()  # held for a whole fetch and build
        self._scored_lock = threading.Lock()  # guards only gets and sets on `_scored_cache`, never held across a load
        self._cache: dict[tuple, dict] = {}
        self._bench_cache: dict[tuple, dict] = {}
        self._scored_cache: dict[str, dict] = {}  # one entry per experiment id

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

    def _pushed(self, exp_id: str, sha: str | None) -> bool:
        remote = self.git.sha(REMOTE_RESULTS + exp_id)
        return remote is not None and remote == sha

    # --- the bundle ------------------------------------------------------------------------

    def get(self, release: str | None, refresh: bool, live_ids: set[str], env: dict, running: set[str]) -> dict:
        """`live_ids` pick the local ref over the remote one; `running` marks rows running."""
        with self._lock:
            if refresh or not self._cache:
                self.git.fetch()
            versions = self.releases()
            if release is not None and release not in versions:
                raise ApiError(400, f"field 'release' must be one of {', '.join(versions) or '(none)'}")
            release = release or (versions[0] if versions else None)
            refs = self.git.results_refs(live_ids)
            main_sha = self.git.sha(self.git.main_ref())
            shas = {i: self.git.sha(r) for i, r in refs.items()}
            key = (release, main_sha, tuple(sorted(shas.items())))
            if key not in self._cache:
                if len(self._cache) >= CACHE_LIMIT:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = self._build(release, versions, refs, main_sha)
            bundle = copy.deepcopy(self._cache[key])
            bundle["fetched_at"], bundle["fetch_error"] = self.git.fetched_at, self.git.fetch_error
            # Per request, never cached: a job starting or stopping, or a push, changes these, not a ref read.
            pushed = {i: self._pushed(i, shas.get(i)) for i in {row["id"] for row in bundle["experiments"]}}
            for row in bundle["experiments"]:
                row["running"] = row["id"] in running
                row["pushed"] = pushed[row["id"]]
        return self._fill_keys(bundle, env)

    def _fill_keys(self, bundle: dict, env: dict) -> dict:
        status = secrets.inspect(self.root)
        for provider in bundle["providers"]:
            info = status.get(provider["name"])
            provider["key"] = {"source": info["source"], "tail": info["tail"], "configured": info["configured"]} if info else None
            if info and "account" in info:
                provider["key"]["account"] = {"variable": info["account"]["variable"], "source": info["account"]["source"]}
            have = info is None or info["configured"] or (bool((env.get(provider["variable"]) or "").strip()) and "account" not in info)
            for model in provider["models"]:
                if model["disabled_reason"] is None and not have:
                    model["disabled_reason"] = NO_ACCOUNT if info["source"] != "missing" else NO_KEY
        return bundle

    def _scored(self, experiment_id: str, ref: str, main_sha: str | None) -> dict:
        """One experiment as loaded, with its scored attempt rows once they have been read. One entry per
        experiment id, replaced when its ref sha or the main sha changes, so a new filter reuses it and
        memory follows the number of experiments. Called under the lock."""
        stamp = (self.git.sha(ref), main_sha)
        with self._scored_lock:
            held = self._scored_cache.get(experiment_id)
        if held is None or held["stamp"] != stamp:
            held = {"stamp": stamp, "rows": None,
                    "exp": expdata.load_experiment(self.git, experiment_id, ref, self.git.main_ref())}
            with self._scored_lock:
                self._scored_cache[experiment_id] = held
        return held

    def _load_all(self, refs: dict[str, str], main_sha: str | None) -> list[dict]:
        """The scored-cache entries of every experiment that has a config file or an error to show. Called under the lock."""
        held = (self._scored(i, ref, main_sha) for i, ref in sorted(refs.items()))
        return [h for h in held if not (h["exp"]["config"] is None and (h["exp"]["error"] or "").endswith("file not found"))]

    def _build(self, release: str | None, versions: list[str], refs: dict[str, str], main_sha: str | None) -> dict:
        main, base = self.git.main_ref(), self.git.github()

        def link(path: str) -> str | None:
            return f"{base}/blob/{main_sha}/{path}" if base and main_sha else None

        manifests = {v: self._manifest(v) for v in versions}
        manifest = manifests.get(release)
        inputs_by_release: dict[str, list[dict]] = {}
        catalogue = {e["name"]: e for e in self._catalogue()}
        experiments, rows = [], []
        # The Experiments list picks its releases on the page, so rows cover every release on main. Everything
        # else in the bundle reads only this release and its mirrors.
        rows_by_exp: dict[str, list[dict]] = {}  # validated attempt rows per experiment, shared with the puzzles
        for held in self._load_all(refs, main_sha):
            config = held["exp"]["config"]
            if config is not None and config["release"] not in manifests:
                continue
            if config and config["release"] not in inputs_by_release:
                inputs_by_release[config["release"]] = expdata.read_inputs(self.git, main, config["release"])
            inputs = inputs_by_release[config["release"]] if config else []
            scored = self._rows(held, manifests, inputs_by_release) if config else None
            exp = {**held["exp"]}  # callers below write `error` into it, which must not reach the cached entry
            if config is None or is_mirror(release, config["release"], manifests):
                experiments.append(exp)
            branch = f"{base}/tree/{exp['sha']}/results/{exp['id']}" if base and exp["sha"] else None
            rows_by_exp[exp["id"]] = scored or []
            for row in expdata.experiment_rows(exp, inputs, scored):
                entry = next((m for m in config["models"] if m["name"] == row["model"]), None) if config else None
                known = catalogue.get(row["model"])
                differs = entry is not None and (known is None or any(
                    entry.get(f, {} if f == "params" else None) != known.get(f, {} if f == "params" else None)
                    for f in ("provider", "api_model_id", "params")))
                rows.append({**row, "branch": branch, "pushed": False, "running": False,
                             "differs_from_catalogue": differs})
        names = list(manifest["release_config"]["puzzles"]) if manifest else []
        if names and release not in inputs_by_release:
            inputs_by_release[release] = expdata.read_inputs(self.git, main, release)
        puzzles = [build_puzzle(self.git, main, link, release, manifest, name, inputs_by_release[release],
                                experiments, rows_by_exp) for name in names]
        definitions = link("docs/definitions.md")
        return {"schema": 3, "release": release, "releases": versions, "fetched_at": None, "fetch_error": None,
                "repo": base, "main_sha": main_sha, "defaults": DEFAULTS,
                "providers": build_providers(catalogue, self._prices(), experiments), "puzzles": puzzles, "experiments": rows,
                "about": {"markdown": self.git.show(main, "README.md"), "source": link("README.md")},
                "metric_definitions": {"terms": metric_definitions(self.git.show(main, "docs/definitions.md")),
                                       "source": definitions and definitions + "#metrics"}}

    # --- benchmarks ------------------------------------------------------------------------

    def benchmarks(self, query: dict[str, list[str] | None], live_ids: set[str]) -> dict:
        """`query` holds the lists of GET /api/benchmarks (None or empty: the default) and `validity` (a string)."""
        with self._lock:
            if self.git.fetched_at is None:
                self.git.fetch()
            versions = self.releases()
            refs = self.git.results_refs(live_ids)
            main_sha = self.git.sha(self.git.main_ref())
            asked = query.get("releases")
            chosen = self._choose("releases", asked, versions,
                                  [] if asked else self._newest_with_data(versions, refs, main_sha))
            puzzles = self._choose("puzzles", query.get("puzzles"), list(ENGINES), list(ENGINES))
            setups = self._choose("setups", query.get("setups"), list(SETUPS), list(SETUPS))
            scope = query.get("validity") or "all"
            if scope not in expdata.SCOPES:
                raise ApiError(400, f"field 'validity' must be one of {', '.join(expdata.SCOPES)}")
            models = list(query.get("models") or [])
            shas = tuple(sorted((i, self.git.sha(r)) for i, r in refs.items()))
            key = ("benchmarks", tuple(chosen), tuple(puzzles), tuple(setups), scope, tuple(sorted(models)),
                   main_sha, shas)
            if key not in self._bench_cache:
                if len(self._bench_cache) >= CACHE_LIMIT:
                    self._bench_cache.pop(next(iter(self._bench_cache)))
                self._bench_cache[key] = self._benchmarks(chosen, puzzles, setups, scope, models, refs)
            return self._bench_cache[key]

    def _newest_with_data(self, versions: list[str], refs: dict[str, str], main_sha: str | None) -> list[str]:
        """The default release: the newest one with scored attempts from an experiment that ran on it, directly
        or through a mirror. The newest release when there is none. Scores candidates newest first, so a record
        that cannot be scored counts the same on every request. Called under the lock."""
        manifests = {v: self._manifest(v) for v in versions}
        held = [self._scored(i, ref, main_sha) for i, ref in sorted(refs.items())]
        inputs_by_release: dict[str, list[dict]] = {}
        for v in versions:
            for h in held:
                config = h["exp"]["config"]
                if config is not None and is_mirror(v, config["release"], manifests) \
                        and self._rows(h, manifests, inputs_by_release):
                    return [v]
        return versions[:1]

    def _rows(self, held: dict, manifests: dict[str, dict | None], inputs_by_release: dict[str, list[dict]]) -> list[dict]:
        """The scored attempt rows of one experiment with a config, read once. Empty when it has an error."""
        exp = held["exp"]
        if held["rows"] is None and not exp["error"]:
            release = exp["config"]["release"]
            if release not in inputs_by_release:
                inputs_by_release[release] = expdata.read_inputs(self.git, self.git.main_ref(), release)
            rows = expdata.attempt_rows(exp, inputs_by_release[release])
            set_id = (manifests.get(release) or {}).get("input_set_id")
            for row in rows:
                row["input_set_id"] = set_id
                row["experiment"] = exp["id"]
                row["priced"] = row["model"] in exp["prices"]
            held["rows"] = rows
        return [] if exp["error"] else held["rows"] or []

    @staticmethod
    def _choose(field: str, asked: list[str] | None, known: list[str], default: list[str]) -> list[str]:
        if not asked:
            return default
        unknown = [a for a in asked if a not in known]
        if unknown:
            raise ApiError(400, f"field '{field}' has {unknown[0]!r}, which is not one of {', '.join(known) or '(none)'}")
        return [k for k in known if k in asked]

    def _benchmarks(self, chosen: list[str], puzzles: list[str], setups: list[str], scope: str,
                    models: list[str], refs: dict[str, str]) -> dict:
        main = self.git.main_ref()
        manifests = {v: self._manifest(v) for v in self.releases()}
        inputs_by_release: dict[str, list[dict]] = {}
        attempts, skipped, read, entries = [], [], [], {}
        main_sha = self.git.sha(main)
        for i, ref in sorted(refs.items()):
            held = self._scored(i, ref, main_sha)
            exp = held["exp"]
            config = exp["config"]
            if config is None and (exp["error"] or "").endswith("file not found"):
                continue
            if config is not None and not any(is_mirror(r, config["release"], manifests) for r in chosen):
                continue
            if config is not None:
                rows = self._rows(held, manifests, inputs_by_release)
            if config is None or exp["error"]:
                skipped.append({"id": exp["id"], "error": exp["error"]})
                continue
            attempts += rows
            read.append(exp["id"])
            for m in config["models"]:
                entries.setdefault(m["name"], m["provider"])
        providers = list(PROVIDER_ORDER) + sorted(set(entries.values()) - set(PROVIDER_ORDER))
        ordered = [n for p in providers for n, provider in entries.items() if provider == p]
        known = [n for n in ordered if n in models]  # names that no experiment holds are ignored
        shown = known or ordered
        held = {r["puzzle"] for r in attempts}
        attempts = [r for r in attempts if r["setup"] in setups]
        return {"releases": chosen,
                "options": {"providers": [{"name": p, "models": [n for n in ordered if entries[n] == p]}
                                          for p in providers if p in entries.values()],
                            "puzzles": [p for p in ENGINES if p in held]},
                "models": [{"name": n, "provider": entries[n]} for n in shown],
                "experiments": read,
                "rows": benchmarks.build_rows(attempts, shown, [p for p in puzzles if p in held], scope,
                                           "|".join([*chosen, *setups])),
                "skipped": skipped}

    # --- the other routes ------------------------------------------------------------------

    def experiment(self, experiment_id: str, live_ids: set[str], running: set[str]) -> dict:
        exp, main = self.loaded(experiment_id, live_ids), self.git.main_ref()
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
                "model_entries": [{f: m.get(f) for f in ("name", "provider", "api_model_id", "kind", "params")}
                                  for m in config["models"]] if config else [],
                "pushed": self._pushed(experiment_id, exp["sha"]), "running": experiment_id in running,
                "branch": f"{base}/tree/{exp['sha']}/results/{experiment_id}" if base and exp["sha"] else None,
                "metrics_source": source, "report": report,
                # Work-tree reads (like API 12), with local_report below: Evaluate and Commit need the results on disk.
                "local_results": (self.root / "results" / experiment_id / "experiment.toml").is_file(),
                "local_report": bool(config) and (self.root / "results" / experiment_id / f"{config['release']}.md").is_file(),
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
