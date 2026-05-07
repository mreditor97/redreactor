"""Tests for dict_merge utility."""

from __future__ import annotations

from redreactor.helpers.utils import dict_merge


def test_flat_merge_overwrites_keys():
    """dict_merge overwrites top-level keys."""
    dct = {"a": 1, "b": 2}
    dict_merge(dct, {"b": 99, "c": 3})
    assert dct == {"a": 1, "b": 99, "c": 3}


def test_nested_merge_recurses():
    """dict_merge recurses into nested dicts."""
    dct = {"outer": {"inner": 1, "other": 2}}
    dict_merge(dct, {"outer": {"inner": 99}})
    assert dct["outer"]["inner"] == 99
    assert dct["outer"]["other"] == 2


def test_merge_adds_new_keys():
    """dict_merge adds keys from merge_dct that are not in dct."""
    dct = {"a": 1}
    dict_merge(dct, {"b": 2})
    assert dct["b"] == 2


def test_non_dict_replaced_by_value():
    """dict_merge replaces a non-dict value with the value from merge_dct."""
    dct = {"key": "string_value"}
    dict_merge(dct, {"key": {"nested": True}})
    assert dct["key"] == {"nested": True}
