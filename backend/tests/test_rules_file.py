import pytest
import yaml

from app.services.rules.engine import RulesError, load_rules, split_in_three
from tests.rules_helpers import RULES_DIR, book

RULE = {
    "code": "test_rule",
    "title": "Тест за {period_name}",
    "kind": "payment",
    "schedule": {"type": "yearly", "day": 1, "month": 1},
    "source": "ст. 1",
}


def test_2026_rules_have_sources_and_unique_codes():
    rules = book.for_period_year(2026).rules

    assert len(rules) > 40
    assert all("ст" in rule.source for rule in rules)


def write(tmp_path, rules, year=2026, name="2026.yaml"):
    data = {"year": year, "checked": "тест", "rules": rules}
    (tmp_path / name).write_text(yaml.safe_dump(data, allow_unicode=True))
    return tmp_path


@pytest.mark.parametrize(
    "rule",
    [
        {k: v for k, v in RULE.items() if k != "source"},
        RULE | {"source": ""},
        RULE | {"applies": {"main_regim": ["usn6"]}},
        RULE | {"applies": {"main_regime": ["envd"]}},
        RULE | {"schedule": {"type": "weekly"}},
        RULE | {"schedule": {"type": "handler", "name": "unknown"}},
        RULE | {"schedule": {"type": "yearly", "day": 32, "month": 1}},
    ],
)
def test_invalid_rule_is_rejected(tmp_path, rule):
    with pytest.raises(RulesError):
        load_rules(write(tmp_path, [rule]))


def test_duplicate_codes_and_wrong_year(tmp_path):
    with pytest.raises(RulesError, match="test_rule"):
        load_rules(write(tmp_path, [RULE, RULE]))
    with pytest.raises(RulesError, match="2025"):
        load_rules(write(tmp_path, [RULE], year=2025))


def test_next_year_file_covers_its_periods(tmp_path):
    write(tmp_path, [RULE])
    write(tmp_path, [RULE | {"code": "new_rule"}], year=2027, name="2027.yaml")

    loaded = load_rules(tmp_path)

    assert loaded.for_period_year(2025).year == 2026
    assert loaded.for_period_year(2027).year == 2027
    assert loaded.for_period_year(2028) is None
    assert RULES_DIR.joinpath("2026.yaml").exists()


@pytest.mark.parametrize(
    ("total", "parts"),
    [
        (100_000_00, (33_334_00, 33_334_00, 33_334_00)),
        (611_100_00, (203_700_00, 203_700_00, 203_700_00)),
        (0, (0, 0, 0)),
        (2, (100, 100, 100)),
        (300_01, (101_00, 101_00, 101_00)),
    ],
)
def test_split_in_three(total, parts):
    assert split_in_three(total) == parts
    assert 0 <= sum(parts) - total < 300
