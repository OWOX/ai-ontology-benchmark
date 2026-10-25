# Spec: docs/specs/ui.md
"""Readers the form and run routes add to Bundles: the catalogue with its disabled reasons, a release's
puzzles, an experiment's stored config, and one experiment branch. Reads `main` and the results refs
through GitData. Writes nothing.
"""

from ui import expdata
from ui.catalogue import build_providers
from ui.common import ApiError
from ui.gitdata import LOCAL_RESULTS, REMOTE_RESULTS


class BranchReaders:
    """Mixin for Bundles: needs `git`, `_manifest`, `_catalogue`, `_prices`, and `_fill_keys`."""

    def models(self, env: dict) -> dict[str, dict]:
        """The catalogue on main by name, each model with its provider, `disabled_reason`, and the rest of its entry."""
        providers = self._fill_keys({"providers": build_providers({e["name"]: e for e in self._catalogue()},
                                                                  self._prices(), [])}, env)["providers"]
        return {m["name"]: {**m, "provider": p["name"]} for p in providers for m in p["models"]}

    def release_puzzles(self, release: str) -> list[str] | None:
        """The puzzles of a release on main, or None when main has no such release."""
        manifest = self._manifest(release)
        return list(manifest["release_config"]["puzzles"]) if manifest else None

    def branch_config(self, experiment_id: str) -> str | None:
        """`results/<id>/experiment.toml` on the local branch if there is one, else on the remote branch."""
        path = f"results/{experiment_id}/experiment.toml"
        for prefix, ids in ((LOCAL_RESULTS, self.git.local_ids()), (REMOTE_RESULTS, self.git.remote_ids())):
            text = self.git.show(prefix + experiment_id, path) if experiment_id in ids else None
            if text is not None:
                return text
        return None

    def loaded(self, experiment_id: str, live_ids: set[str]) -> dict:
        """One experiment branch read by `expdata`, from the local ref when its id is live. 404 when it has none."""
        ref = self.git.results_refs(live_ids).get(experiment_id)
        exp = expdata.load_experiment(self.git, experiment_id, ref, self.git.main_ref()) if ref else None
        if exp is None or (exp["config"] is None and (exp["error"] or "").endswith("file not found")):
            raise ApiError(404, f"experiment '{experiment_id}' not found")
        return exp
