import pytest

from geoparse.options import best_keyword_option, keyword_hits, parse_distance, parse_value


@pytest.mark.parametrize("text,meters", [("2 km", 2000), ("2km", 2000), ("500 m", 500), ("five kms", 5000),
                                         ("1.5 miles", 2414.016), ("10-km", 10000), ("a 2 km", 2000)])
def test_parse_distance(text, meters):
    assert parse_distance(text) == pytest.approx(meters)


def test_parse_distance_rejects():
    assert parse_distance("2 km of coastal districts") is None
    assert parse_distance("Goa") is None


@pytest.mark.parametrize("text,value", [("1 million", 1e6), ("10 lakh", 1e6), ("500,000", 5e5), ("2 crore", 2e7),
                                        ("50,000", 5e4)])
def test_parse_value(text, value):
    assert parse_value(text) == value


def test_keywords_allow_one_typo():
    assert best_keyword_option("coastl states", "predicates")[0] == "coastal"
    assert best_keyword_option("populaton over", "attrs")[0] == "population"
    assert best_keyword_option("hospitls", "categories")[0] == "hospital"
    assert keyword_hits("north-east", ["north-east"]) == 1
