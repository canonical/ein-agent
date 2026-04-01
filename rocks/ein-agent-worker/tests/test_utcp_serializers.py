"""Tests for UTCP serializers: serialize_result and serialize_schema."""

import json
from unittest.mock import MagicMock

from ein_agent_worker.utcp.serializers import serialize_result, serialize_schema


class TestSerializeResult:
    def test_dict_input(self):
        result = serialize_result({'key': 'value'})
        assert json.loads(result) == {'key': 'value'}

    def test_list_input(self):
        result = serialize_result([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]

    def test_string_input(self):
        assert serialize_result('hello') == 'hello'

    def test_non_json_type(self):
        assert serialize_result(42) == '42'


class TestSerializeSchema:
    def test_dict_input(self):
        result = serialize_schema({'type': 'string', 'description': 'A name'})
        assert result == {'type': 'string', 'description': 'A name'}

    def test_list_input(self):
        result = serialize_schema([{'type': 'string'}])
        assert result == [{'type': 'string'}]

    def test_string_passthrough(self):
        assert serialize_schema('hello') == 'hello'

    def test_none_values_stripped(self):
        result = serialize_schema({'type': 'string', 'default': None, 'title': 'Name'})
        assert result == {'type': 'string', 'title': 'Name'}

    def test_nested_none_values_stripped(self):
        result = serialize_schema({
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'default': None},
            },
        })
        assert result == {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
            },
        }

    def test_pydantic_model(self):
        mock_model = MagicMock()
        mock_model.model_dump.return_value = {'type': 'string', 'extra': None}

        result = serialize_schema(mock_model)
        mock_model.model_dump.assert_called_once()
        assert result == {'type': 'string'}
