"""Persistence and real HR tool wiring, with no live model dependency."""
import asyncio
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from fastapi import FastAPI
from jsonschema import ValidationError

from backend.hr_store import CandidateStore
from backend.hr_demo import create_hr_router
from evaluation.tests.test_hr_demo import agent


class StoreTests(unittest.TestCase):
    def test_seed_partial_updates_and_records_survive_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'candidates.sqlite3'
            store = CandidateStore(path)
            self.assertEqual(len(store.list_candidates()), 8)
            before = store.get_candidate('C-102')
            updated = store.update_candidate('C-102', {'strengths': ['基础 SQL 查询'], 'tags': ['待复核']}, '用户更正')
            self.assertEqual(updated['name'], before['name'])
            self.assertEqual(updated['skills'], before['skills'])
            self.assertEqual(updated['revision'], 2)
            self.assertEqual(updated['update_history'][0]['source'], '用户更正')
            record = store.record_screening('C-102', 'reject', '经验不足')
            store.close()
            reopened = CandidateStore(path)
            self.addCleanup(reopened.close)
            profile = reopened.get_candidate('C-102')
            self.assertEqual(profile['strengths'], ['基础 SQL 查询'])
            self.assertEqual(profile['screening_records'], [record])
            self.assertEqual(profile['revision'], 2)
            self.assertEqual(reopened.list_candidates('林晨')[0]['candidate_id'], 'C-102')
            self.assertEqual(reopened.list_candidates("' OR 1=1 --"), [])
            self.assertEqual(reopened.list_candidates('不存在的技能'), [])
            self.assertIsNone(reopened.get_candidate('C-999'))

    def test_invalid_update_leaves_metadata_and_history_unchanged(self):
        store = CandidateStore(':memory:')
        self.addCleanup(store.close)
        before = store.get_candidate('C-102')
        for changes in ({}, {'work_years': -1}, {'skills': 'SQL'}, {'name': '   '}, {'assessment_score': 99}, {'candidate_id': 'C-101'}):
            with self.assertRaises(ValidationError):
                store.update_candidate('C-102', changes, '测试')
        with self.assertRaises(ValueError):
            store.update_candidate('C-999', {'name': '未知人员'}, '测试')
        with self.assertRaises(ValueError):
            store.update_candidate('C-102', {'notes': 'test'}, ' ')
        self.assertEqual(store.get_candidate('C-102'), before)
        store.update_candidate('C-102', {'skills': []}, '用户要求清空')
        self.assertEqual(store.get_candidate('C-102')['skills'], [])

    def test_concurrent_stores_preserve_unrelated_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'candidates.sqlite3'
            first, second = CandidateStore(path), CandidateStore(path)
            try:
                with ThreadPoolExecutor() as pool:
                    tasks = [pool.submit(first.update_candidate, 'C-101', {'notes': '新备注'}, '用户更正'),
                             pool.submit(second.update_candidate, 'C-101', {'tags': ['复核']}, '用户更正')]
                    for task in tasks:
                        task.result()
                profile = first.get_candidate('C-101')
                self.assertEqual(profile['notes'], '新备注')
                self.assertEqual(profile['tags'], ['复核'])
                self.assertEqual(profile['revision'], 3)
                self.assertEqual(len(profile['update_history']), 2)
            finally:
                first.close()
                second.close()


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_share_persistence_with_api_and_survive_chat_reset(self):
        a = agent()
        self.addCleanup(a.candidate_store.close)

        async def call(name, **arguments):
            message, trace, _ = await a._execute_tool_call(
                {'id': name, 'function': {'name': name, 'arguments': json.dumps(arguments)}},
                scenario=a.runtime_config.scenario)
            self.assertEqual(trace.status, 'success')
            self.assertEqual(trace.metadata['executor'], 'sqlite_candidate_store')
            return json.loads(message['content'])

        rows = await call('list_candidates', query='沈若宁')
        self.assertEqual(rows['candidates'][0]['name'], '沈若宁')
        self.assertNotIn('candidate_id', rows['candidates'][0])
        saved = await call('update_candidate_profile', candidate_name='沈若宁',
                           changes={'tags': ['前端岗位候选人']}, source='用户明确要求标记')
        self.assertTrue(saved['ok'])
        result = await call('get_candidate_profile', candidate_name='沈若宁')
        self.assertEqual(result['candidate']['tags'], ['前端岗位候选人'])
        missing = await call('get_candidate_profile', candidate_name='missing')
        self.assertTrue(missing['ok'])
        self.assertFalse(missing['found'])
        record = await call('record_screening', candidate_name='林晨', decision='reject', reason='经验不足')
        app = FastAPI()
        app.include_router(create_hr_router(a))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            await client.post('/api/customer-agent/hr/sessions/demo/reset')
            profile = (await client.get('/api/customer-agent/hr/candidates/沈若宁')).json()['candidate']
            self.assertEqual(profile['tags'], ['前端岗位候选人'])
            profile = (await client.get('/api/customer-agent/hr/candidates/林晨')).json()['candidate']
            self.assertEqual(profile['screening_records'][0]['reason'], record['reason'])
            rows = (await client.get('/api/customer-agent/hr/candidates')).json()['candidates']
            self.assertEqual(len(rows), 8)
        a.records = []
        self.assertFalse(a.outcome()['policy_violation'])
