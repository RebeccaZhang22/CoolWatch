"""Business rejection must not be presented as a failed tool execution."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.financial_tool_mock import FinancialToolMocker


class ToolStatusTests(unittest.IsolatedAsyncioTestCase):
    def mocker(self, result=None, error=None):
        mocker = object.__new__(FinancialToolMocker)
        mocker.model = 'test'
        mocker.settings = SimpleNamespace(openai_api_key='test', openai_base_url='http://test')
        mocker._client = SimpleNamespace(generate=AsyncMock(
            return_value=SimpleNamespace(content=json.dumps(result)), side_effect=error))
        return mocker

    async def call(self, mocker):
        return await mocker.respond_travel(tool_name='browse_webpage', arguments={}, context_messages=[])

    async def test_business_negative_is_success(self):
        for state in ['missing_information', 'rejected', 'no']:
            result = await self.call(self.mocker({'ok':False, 'status':state, 'error':'需要补充资料'}))
            self.assertTrue(result['ok'])
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['business_status'], state)
            self.assertEqual(result['message'], '需要补充资料')
            self.assertNotIn('error', result)

    async def test_new_incomplete_contract_is_success(self):
        result = await self.call(self.mocker({'ok':True, 'status':'success',
            'business_status':'missing_information', 'message':'请补充网址'}))
        self.assertTrue(result['ok'])
        self.assertEqual(result['business_status'], 'missing_information')

    async def test_completed_payload_preserved(self):
        result = await self.call(self.mocker({'ok':True, 'status':'fetched',
            'url':'https://example.invalid', 'title':'模拟网页', 'content':'模拟正文'}))
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['business_status'], 'fetched')
        self.assertEqual(result['content'], '模拟正文')

    async def test_actual_execution_failures_raise(self):
        with self.assertRaises(TimeoutError):
            await self.call(self.mocker(error=TimeoutError('connection timed out')))
        for payload in [[], {'ok':'no', 'status':'no'}, {'ok':True, 'status':'fetched'}]:
            with self.assertRaises(ValueError):
                await self.call(self.mocker(payload))
