"""Tests for dict_merge utility."""

from __future__ import annotations

from redreactor.helpers.utils import dict_merge


def test_flat_merge_overwrites_keys():
    """Flat merge should overwrite existing keys."""
    dct = {"a": 1, "b": 2}
    merge_dct = {"b": 99, "c": 3}
    dict_merge(dct, merge_dct)
    assert dct == {"a": 1, "b": 99, "c": 3}


def test_nested_merge_recurses():
    """Nested dicts are merged recursively."""
    dct = {"a": {"x": 1, "y": 2}}
    merge_dct = {"a": {"y": 99, "z": 3}}
    dict_merge(dct, merge_dct)
    assert dct == {"a": {"x": 1, "y": 99, "z": 3}}


def test_keys_in_merge_dct_not_in_dct_are_added():
    """Keys present only in merge_dct are added to dct."""
    dct = {"a": 1}
    merge_dct = {"b": 2}
    dict_merge(dct, merge_dct)
    assert dct["b"] == 2


def test_non_dict_value_replaced_by_dict():
    """Non-dict value in dct is replaced when merge_dct has a dict."""
    dct = {"a": "string_value"}
    merge_dct = {"a": {"nested": "dict"}}
    dict_merge(dct, merge_dct)
    assert dct["a"] == {"nested": "dict"}
