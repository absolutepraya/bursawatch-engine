from __future__ import annotations

from evidence import normalize_evidence, normalized_mae, parse_number, path_correlation


def test_parse_number_handles_screenshot_units_and_indonesian_decimal() -> None:
    assert parse_number("Rp 189.01M") == 189_010_000
    assert parse_number("21,2M") == 21_200_000
    assert parse_number("+9.60%") == 9.60
    assert parse_number("not visible") is None


def test_hidden_fields_are_not_promoted_to_observations() -> None:
    bundle = normalize_evidence(
        [
            {
                "kind": "chart",
                "source": "user-image",
                "as_of": "2026-08-19",
                "fields": {
                    "price": 192,
                    "macd": {"value": -1.4, "visible": False},
                    "rsi": None,
                },
            }
        ]
    )

    assert bundle.visible_names() == ("price",)
    assert bundle.as_of == "2026-08-19"


def test_nested_items_and_string_pivots_are_normalized() -> None:
    bundle = normalize_evidence(
        {
            "items": [
                {
                    "kind": "chart",
                    "source": "user-image",
                    "as_of": "2026-08-19",
                    "fields": {"path": "10, 20, 15"},
                }
            ]
        }
    )

    assert bundle.first("pivots") == (10.0, 20.0, 15.0)


def test_path_math_is_affine_invariant_and_detects_reversal() -> None:
    assert path_correlation([10, 20, 15, 30], [100, 200, 150, 300]) > 0.99
    assert normalized_mae([10, 20, 15, 30], [100, 200, 150, 300]) < 0.01
    assert path_correlation([10, 20, 15, 30], [30, 15, 20, 10]) < -0.9
