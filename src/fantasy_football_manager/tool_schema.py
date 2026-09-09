"""Describe existing dictionary inputs without changing their runtime validators."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def model_input_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Inline local model references for an embedded MCP parameter schema.

    Pydantic cannot embed an independent model's root-relative references inside
    a dictionary parameter. The current input models are finite and nonrecursive.
    Runtime arguments remain dictionaries and retain their existing validation.
    """
    schema = model.model_json_schema()
    definitions = schema.get("$defs", {})

    def expand(value, active=()):
        if isinstance(value, list):
            return [expand(item, active) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            reference = value["$ref"]
            prefix = "#/$defs/"
            if not reference.startswith(prefix) or reference in active:
                raise ValueError("MCP input schemas require nonrecursive local model references.")
            name = reference[len(prefix):].replace("~1", "/").replace("~0", "~")
            if name not in definitions:
                raise ValueError("MCP input schema contains an unresolved model reference.")
            resolved = expand(deepcopy(definitions[name]), (*active, reference))
            resolved.update({key: expand(item, active) for key, item in value.items() if key != "$ref"})
            return resolved
        return {key: expand(item, active) for key, item in value.items() if key != "$defs"}

    return expand(schema)
