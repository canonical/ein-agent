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

    def test_small_result_not_truncated(self):
        data = {'items': [{'name': f'pod-{i}'} for i in range(5)]}
        result = serialize_result(data, max_chars=100_000)
        parsed = json.loads(result)
        assert len(parsed['items']) == 5
        assert '_truncated' not in parsed

    def test_k8s_list_truncated_with_summary(self):
        """Kubernetes-style list responses are smartly truncated."""
        items = [{'name': f'pod-{i}', 'status': 'Running', 'data': 'x' * 500} for i in range(100)]
        data = {'kind': 'PodList', 'apiVersion': 'v1', 'items': items}
        result = serialize_result(data, max_chars=5000)
        parsed = json.loads(result)
        assert '_truncated' in parsed
        assert parsed['_truncated']['total'] == 100
        assert parsed['_truncated']['shown'] < 100
        assert len(parsed['items']) == parsed['_truncated']['shown']
        assert len(result) <= 5000

    def test_non_list_large_result_hard_truncated(self):
        """Non-list large results are hard-truncated with a warning."""
        data = 'x' * 10_000
        result = serialize_result(data, max_chars=1000)
        assert len(result) <= 1000
        assert 'TRUNCATED' in result

    def test_truncation_respects_max_chars(self):
        """Truncated output never exceeds max_chars."""
        items = [{'name': f'item-{i}', 'payload': 'y' * 1000} for i in range(200)]
        data = {'items': items}
        for limit in [2000, 5000, 10_000, 50_000]:
            result = serialize_result(data, max_chars=limit)
            assert len(result) <= limit, f'Result {len(result)} exceeded limit {limit}'


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
