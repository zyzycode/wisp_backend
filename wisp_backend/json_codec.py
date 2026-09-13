"""Strict JSON: reject duplicate keys and non-JSON numeric constants."""
import json


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Invalid JSON constant")


def decode_json(value):
    return json.loads(value, object_pairs_hook=unique_object, parse_constant=reject_constant)
