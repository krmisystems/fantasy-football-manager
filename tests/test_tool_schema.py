import json

import jsonschema
import pytest
from pydantic import BaseModel

from fantasy_football_manager.demo import make_demo
from fantasy_football_manager.models import LeagueSnapshot, ManagerConfig
from fantasy_football_manager.tool_schema import model_input_schema


@pytest.mark.parametrize("model,payload", [
    (LeagueSnapshot, make_demo().model_dump(mode="json")),
    (ManagerConfig, ManagerConfig().model_dump(mode="json")),
])
def test_model_schema_embeds_in_a_tool_without_unresolved_references(model, payload):
    schema = {"type": "object", "properties": {"value": model_input_schema(model)}, "required": ["value"]}
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate({"value": payload})
    assert '"$ref"' not in json.dumps(schema)
    assert schema["properties"]["value"]["additionalProperties"] is False


class RecursiveInput(BaseModel):
    child: "RecursiveInput | None" = None


def test_recursive_model_fails_before_publishing_an_invalid_tool_schema():
    with pytest.raises(ValueError, match="nonrecursive local model references"):
        model_input_schema(RecursiveInput)
