# Spec: docs/specs/config.md
"""Tests for the config loaders. They read the repo config and write temporary files only."""

import pytest

from src.config import load_experiment_config, load_prices, load_release_config, parse_experiment_config

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


def with_puzzles(value):
    return bad(EXPERIMENT, "attempts = 3\n", f"attempts = 3\npuzzles = {value}\n")


EXPERIMENT_CASES = [
    ("puzzles", with_puzzles("[]")),
    ("puzzles", with_puzzles('["2x2", "2x2"]')),
    ("puzzles", with_puzzles("[2]")),
    ("puzzles", with_puzzles('"2x2"')),
    ("puzzles", with_puzzles('["4x4"]')),
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


DEFAULT_BUDGET = {"per_request_usd": 0.50, "per_model_usd": 5.00, "per_experiment_usd": 10.00}


def test_no_budget_table_gives_the_defaults(tmp_path):
    config = load_experiment_config(write(tmp_path, EXPERIMENT, "e.toml"))
    assert config["budget"] == DEFAULT_BUDGET


def test_partial_budget_fills_the_other_defaults(tmp_path):
    text = EXPERIMENT + "\n[budget]\nper_experiment_usd = 25\n"
    config = load_experiment_config(write(tmp_path, text, "e.toml"))
    assert config["budget"] == {**DEFAULT_BUDGET, "per_experiment_usd": 25}


@pytest.mark.parametrize("field", list(DEFAULT_BUDGET))
@pytest.mark.parametrize("value", ["0", "-1", '"1"', "true"])
def test_bad_budget_value(tmp_path, field, value):
    text = EXPERIMENT + f"\n[budget]\n{field} = {value}\n"
    with pytest.raises(ValueError, match=field) as error:
        load_experiment_config(write(tmp_path, text, "e.toml"))
    assert "e.toml" in str(error.value)


def test_budget_must_be_a_table_and_know_its_fields(tmp_path):
    with pytest.raises(ValueError, match="budget"):
        load_experiment_config(write(tmp_path, 'budget = 3\n' + EXPERIMENT, "e.toml"))
    with pytest.raises(ValueError, match="per_day_usd"):
        load_experiment_config(write(tmp_path, EXPERIMENT + "\n[budget]\nper_day_usd = 1\n", "e.toml"))


def test_experiment_puzzles_valid_list_is_kept(tmp_path):
    config = load_experiment_config(write(tmp_path, with_puzzles('["3x3", "2x2"]'), "e.toml"))
    assert config["puzzles"] == ["3x3", "2x2"]


def test_experiment_without_puzzles_leaves_the_key_absent(tmp_path):
    assert "puzzles" not in load_experiment_config(write(tmp_path, EXPERIMENT, "e.toml"))


def test_parse_experiment_config_matches_load(tmp_path):
    path = write(tmp_path, EXPERIMENT, "exp.toml")
    assert parse_experiment_config(EXPERIMENT, "exp", "<stdin>") == load_experiment_config(path)


def test_parse_experiment_config_names_source():
    with pytest.raises(ValueError, match="<stdin>"):
        parse_experiment_config('release = "1.0.0"\n', "exp", "<stdin>")
    with pytest.raises(ValueError, match="<stdin>: not valid TOML"):
        parse_experiment_config("release = ", "exp", "<stdin>")


@pytest.mark.parametrize("kind", ["system-1", "system-2"])
def test_model_kind_is_kept(tmp_path, kind):
    text = EXPERIMENT + f'kind = "{kind}"\n'
    assert load_experiment_config(write(tmp_path, text, "e.toml"))["models"][0]["kind"] == kind


def test_model_kind_is_optional(tmp_path):
    assert "kind" not in load_experiment_config(write(tmp_path, EXPERIMENT, "e.toml"))["models"][0]


@pytest.mark.parametrize("value", ['"system-3"', '"System-1"', '""', "1", "true"])
def test_bad_model_kind(tmp_path, value):
    with pytest.raises(ValueError, match="kind"):
        load_experiment_config(write(tmp_path, EXPERIMENT + f"kind = {value}\n", "e.toml"))


def test_decision_providers_are_known():
    from src.config import PROVIDERS

    assert {"typesafe", "cloudflare", "fake_decision"} <= set(PROVIDERS)


def test_max_moves_default_and_override():
    from src.config import max_moves

    release = {"scramble_depths": [3, 7, 5]}
    assert max_moves({}, release) == 14
    assert max_moves({"max_moves": 9}, release) == 9


def experiment_with_max_moves(literal):
    return (
        'release = "1.0.0"\nattempts = 1\nretry_cap = 0\nmax_output_tokens = 10\n'
        f"max_moves = {literal}\n"
        '[[models]]\nname = "m"\nprovider = "fake"\napi_model_id = "x"\n'
    )


@pytest.mark.parametrize("literal", ["0", "-1", '"5"', "true"])
def test_max_moves_must_be_positive_int(literal):
    with pytest.raises(ValueError, match="max_moves"):
        parse_experiment_config(experiment_with_max_moves(literal), "e", "e.toml")


def test_max_moves_valid_value_is_kept():
    assert parse_experiment_config(experiment_with_max_moves("5"), "e", "e.toml")["max_moves"] == 5
