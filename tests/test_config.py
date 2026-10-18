# Spec: docs/specs/config.md
"""Tests for the config loaders. They read the repo config and write temporary files only."""

import pytest

from src.config import load_experiment_config, load_prices, load_release_config

RELEASE = """seed = 1
puzzles = ["2x2"]
scramble_depths = [5]
scramble_count = 2
valid_invalid_split = 0.5
"""
EXPERIMENT = """release = "1.0.0"
attempts = 3
retry_cap = 0
max_output_tokens = 100

[[models]]
name = "m"
provider = "fake"
api_model_id = "m-1"
"""
PRICES = """[m]
price_input_per_mtok = 3
price_output_per_mtok = 15.5
"""


def write(tmp_path, text, name="file.toml"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_example_files_load():
    assert load_release_config("config/release.toml")["puzzles"] == ["2x2", "3x3"]
    experiment = load_experiment_config("config/experiments/example.toml")
    assert experiment["experiment_id"] == "example"
    assert experiment["models"][0]["provider"] == "fake"
    assert "example-model" in load_prices("config/prices.toml")


def test_valid_minimal_files_load(tmp_path):
    assert load_release_config(write(tmp_path, RELEASE))["seed"] == 1
    assert load_experiment_config(write(tmp_path, EXPERIMENT, "exp_1-a.toml"))
    assert load_prices(write(tmp_path, PRICES))["m"]["price_input_per_mtok"] == 3


def bad(text, old, new):
    assert old in text
    return text.replace(old, new)


RELEASE_CASES = [
    ("seed", bad(RELEASE, "seed = 1\n", "")),
    ("seed", bad(RELEASE, "seed = 1", 'seed = "1"')),
    ("seed", bad(RELEASE, "seed = 1", "seed = 0")),
    ("puzzles", bad(RELEASE, '["2x2"]', '["4x4"]')),
    ("puzzles", bad(RELEASE, '["2x2"]', "[]")),
    ("scramble_depths", bad(RELEASE, "[5]", "[0]")),
    ("scramble_depths", bad(RELEASE, "[5]", '["a"]')),
    ("scramble_count", bad(RELEASE, "scramble_count = 2", "scramble_count = 0")),
    ("valid_invalid_split", bad(RELEASE, "0.5", "1.5")),
    ("valid_invalid_split", bad(RELEASE, "0.5", "-0.1")),
    ("valid_invalid_split", bad(RELEASE, "0.5", '"half"')),
]


@pytest.mark.parametrize("field,text", RELEASE_CASES)
def test_release_errors(tmp_path, field, text):
    path = write(tmp_path, text)
    with pytest.raises(ValueError, match=field) as error:
        load_release_config(path)
    assert "file.toml" in str(error.value)


EXPERIMENT_CASES = [
    ("release", bad(EXPERIMENT, 'release = "1.0.0"\n', "")),
    ("release", bad(EXPERIMENT, "1.0.0", "1.0")),
    ("attempts", bad(EXPERIMENT, "attempts = 3", "attempts = 0")),
    ("attempts", bad(EXPERIMENT, "attempts = 3", "attempts = true")),
    ("retry_cap", bad(EXPERIMENT, "retry_cap = 0", "retry_cap = -1")),
    ("max_output_tokens", bad(EXPERIMENT, "max_output_tokens = 100", "max_output_tokens = 1.5")),
    ("models", bad(EXPERIMENT, '[[models]]\nname = "m"\nprovider = "fake"\napi_model_id = "m-1"\n', "models = []\n")),
    ("provider", bad(EXPERIMENT, '"fake"', '"mystery"')),
    ("name", bad(EXPERIMENT, 'name = "m"\n', "")),
    ("api_model_id", bad(EXPERIMENT, 'api_model_id = "m-1"\n', "")),
    ("params", EXPERIMENT + "params = 3\n"),
    ("params", EXPERIMENT + "params = { max_tokens = 5 }\n"),
    ("params", EXPERIMENT + "params = { model = 'x' }\n"),
    ("params", EXPERIMENT + "params = { prompt = 'x' }\n"),
    ("params", EXPERIMENT + "params = { instructions = 'x' }\n"),
    ("params", EXPERIMENT + "params = { system_instruction = 'x' }\n"),
    ("params", EXPERIMENT + "params = { response_format = 'x' }\n"),
    ("params", EXPERIMENT + "params = { response_mime_type = 'x' }\n"),
    ("params", EXPERIMENT + "params = { response_schema = 'x' }\n"),
    ("params", EXPERIMENT + "params = { tools = 'x' }\n"),
    ("params", EXPERIMENT + "params = { tool_choice = 'x' }\n"),
    ("name", EXPERIMENT + '\n[[models]]\nname = "m"\nprovider = "fake"\napi_model_id = "z"\n'),
]


@pytest.mark.parametrize("field,text", EXPERIMENT_CASES)
def test_experiment_errors(tmp_path, field, text):
    path = write(tmp_path, text)
    with pytest.raises(ValueError, match=field) as error:
        load_experiment_config(path)
    assert "file.toml" in str(error.value)


def test_bad_experiment_id(tmp_path):
    path = write(tmp_path, EXPERIMENT, "bad name.toml")
    with pytest.raises(ValueError, match="experiment_id"):
        load_experiment_config(path)


PRICE_CASES = [
    ("price_output_per_mtok", bad(PRICES, "price_output_per_mtok = 15.5\n", "")),
    ("price_input_per_mtok", bad(PRICES, "price_input_per_mtok = 3", "price_input_per_mtok = -1")),
    ("price_input_per_mtok", bad(PRICES, "price_input_per_mtok = 3", 'price_input_per_mtok = "3"')),
    ("m", "m = 4\n"),
]


@pytest.mark.parametrize("field,text", PRICE_CASES)
def test_price_errors(tmp_path, field, text):
    path = write(tmp_path, text)
    with pytest.raises(ValueError, match=field) as error:
        load_prices(path)
    assert "file.toml" in str(error.value)


def test_missing_and_malformed_files(tmp_path):
    with pytest.raises(ValueError, match="nope.toml"):
        load_release_config(tmp_path / "nope.toml")
    with pytest.raises(ValueError, match="file.toml"):
        load_release_config(write(tmp_path, "seed = = 1"))
