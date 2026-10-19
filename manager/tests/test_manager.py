"""Manager isolation and real HTTP/SSE telemetry contracts, without model services."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from manager.activity_middleware import ActivityMiddleware, ResponseCapture
from manager.activity_store import ActivityStore, risk_findings
from backend.auth_store import AuthStore
from manager.api import create_manager_router
from manager.telemetry import create_telemetry_router
from manager.auth import COOKIE, ManagerAuthStore


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.auth = AuthStore(root / 'users.db', root / 'nonexistent.json')
        self.managers = ManagerAuthStore(root / 'manager.db')
        self.activity = ActivityStore(root / 'activity.db')
        self.user = self.auth.register('visitor@example.com', 'customer-password')
        self.other = self.auth.register('other@example.com', 'other-password')
        self.managers.provision('owner@example.com', 'manager-password')
        app = FastAPI()
        app.include_router(create_manager_router(self.auth, self.managers, self.activity))
        app.include_router(create_telemetry_router(self.auth, self.activity))
        app.add_middleware(ActivityMiddleware, auth_store=self.auth, activity_store=self.activity)

        @app.post('/api/customer-agent/run')
        async def run(request: Request):
            body = await request.json()
            return {'session_id': body.get('session_id'), 'assistant_message': '演示结果',
                    'defense_signals': [{'defense_id': 'activation_probe', 'status': 'risk', 'blocked': True,
                                        'stage': 'context', 'score': 0.9, 'metadata': {'per_risk': {'ipi': {'flagged': True, 'score': 0.9}}}}],
                    'tool_trace': [{'name': 'read_workspace_file', 'arguments': {'file_id': 'resume'}}]}

        @app.post('/api/customer-agent/hr/chat/stream')
        async def stream(request: Request):
            body = await request.json()
            async def events():
                yield 'event: delta\ndata: {"content":"开始"}\n\n'
                if body.get('fail'):
                    yield 'event: error\ndata: {"message":"model unavailable"}\n\n'
                else:
                    result = {'session_id': 'session-hr', 'assistant_message': '结果', 'verdict': 'compromised',
                              'attack': {'success': True, 'summary': '测试中观察到越权'}}
                    yield 'event: final\ndata: ' + json.dumps(result, ensure_ascii=False) + '\n\n'
                yield 'event: done\ndata: {"ok":true}\n\n'
            return StreamingResponse(events(), media_type='text/event-stream')

        @app.post('/v1/moderations')
        async def moderation():
            return {'action': 'block', 'per_risk': {'ipi': {'flagged': True}}}

        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def manager_login(self):
        response = self.client.post('/api/manager/login', json={'email': 'owner@example.com', 'password': 'manager-password'})
        self.assertEqual(response.status_code, 200, response.text)
        return self.client.cookies.get(COOKIE)

    def customer_login(self):
        self.client.cookies.set('pm_session', self.user['session'])

    def test_customer_role_and_token_never_grant_manager_access(self):
        self.auth.set_role('visitor@example.com', 'admin')
        self.customer_login()
        for path in ['/api/manager/me', '/api/manager/users', '/api/manager/events', '/api/manager/overview']:
            self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer ' + self.user['token']}).status_code, 401)
        self.assertEqual(self.client.post('/api/manager/login', json={'email': 'visitor@example.com', 'password': 'customer-password'}).status_code, 401)

    def test_manager_is_not_customer_identity_and_logout_revokes_session(self):
        token = self.manager_login()
        self.assertIsNone(self.auth.current_user(session=token, token=token))
        self.assertEqual(self.client.get('/api/manager/users').json()['total'], 2)
        self.assertEqual(self.client.post('/api/manager/logout').status_code, 200)
        self.assertIsNone(self.managers.current(token))
        self.assertEqual(self.client.get('/api/manager/me', headers={'Cookie': f'{COOKIE}={token}'}).status_code, 401)

    def test_password_rotation_and_expiry(self):
        session = self.manager_login()
        self.managers.provision('owner@example.com', 'new-manager-password')
        self.assertIsNone(self.managers.current(session))
        _, session = self.managers.login('owner@example.com', 'new-manager-password', 'test')
        with self.managers.connect() as db:
            db.execute("UPDATE manager_sessions SET expires_at='2000-01-01'")
        self.assertIsNone(self.managers.current(session))

    def test_login_rate_limit_persists_across_store_instances(self):
        for _ in range(10):
            response = self.client.post('/api/manager/login', json={'email': 'owner@example.com', 'password': 'wrong'})
            self.assertEqual(response.status_code, 401)
        store = ManagerAuthStore(self.managers.path)
        with self.assertRaises(PermissionError):
            store.login('owner@example.com', 'wrong', 'testclient')

    def test_cross_origin_login_and_write_rejected(self):
        response = self.client.post('/api/manager/login', json={'email': 'owner@example.com', 'password': 'manager-password'}, headers={'Origin': 'https://evil.test'})
        self.assertEqual(response.status_code, 403)
        self.manager_login()
        response = self.client.patch(f"/api/manager/users/{self.user['user']['id']}/lead", json={'status': 'follow_up'}, headers={'Origin': 'https://evil.test'})
        self.assertEqual(response.status_code, 403)

    def test_server_attribution_dedup_and_browser_cannot_claim_risks(self):
        self.customer_login()
        event = {'id': str(uuid4()), 'name': 'click', 'path': '/', 'session_id': 's1', 'label': '运行 Agent',
                 'user_id': self.other['user']['id'], 'risk_count': 99, 'created_at': '2000-01-01'}
        for _ in range(2):
            self.assertEqual(self.client.post('/api/telemetry/events', json={'events': [event]}).status_code, 202)
        events = self.activity.events()['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['user_id'], self.user['user']['id'])
        self.assertEqual(events[0]['risk_count'], 0)
        self.assertEqual(self.activity.events(q='运行 Agent')['total'], 1)
        self.assertNotEqual(events[0]['created_at'], '2000-01-01')

    def test_collector_requires_customer_and_valid_batch(self):
        self.manager_login()
        event = {'id': str(uuid4()), 'name': 'click', 'path': '/'}
        self.assertEqual(self.client.post('/api/telemetry/events', json={'events': [event]}).status_code, 401)
        self.customer_login()
        self.assertEqual(self.client.post('/api/telemetry/events', json={'events': [event] * 31}).status_code, 422)
        event['name'] = 'risk_detected'
        self.assertEqual(self.client.post('/api/telemetry/events', json={'events': [event]}).status_code, 422)

    def test_request_body_response_tools_risks_and_credential_redaction(self):
        self.customer_login()
        response = self.client.post('/api/customer-agent/run?api_key=hidden-query', json={
            'session_id': 'demo-session', 'message': '检查这个 request', 'password': 'hidden',
            'nested': {'api_key': 'hidden-key'}, 'max_tokens': 20})
        self.assertEqual(response.status_code, 200)
        event = self.activity.detail(response.headers['x-activity-id'])
        self.assertEqual(event['session_id'], 'demo-session')
        self.assertEqual(event['request']['message'], '检查这个 request')
        self.assertEqual(event['request']['password'], '[REDACTED]')
        self.assertEqual(event['request']['nested']['api_key'], '[REDACTED]')
        self.assertEqual(event['properties']['query']['api_key'], '[REDACTED]')
        self.assertEqual(event['response']['tool_trace'][0]['name'], 'read_workspace_file')
        self.assertEqual(event['risks'][0]['kind'], 'ipi')
        self.assertEqual(event['blocked'], 1)
        self.assertEqual(event['status'], 'completed')

    def test_sse_final_and_http_200_error_are_recorded(self):
        self.customer_login()
        for fail in [False, True]:
            response = self.client.post('/api/customer-agent/hr/chat/stream', json={'message': '筛选简历', 'fail': fail})
            self.assertIn('event: delta', response.text)
            record = self.activity.detail(response.headers['x-activity-id'])
            self.assertEqual(record['status'], 'error' if fail else 'completed')
            self.assertEqual(record['risk_count'], 0 if fail else 1)
            if not fail:
                self.assertEqual(record['session_id'], 'session-hr')

    def test_cli_token_attribution_takes_precedence_for_moderations(self):
        self.customer_login()
        response = self.client.post('/v1/moderations', json={'messages': []}, headers={'Authorization': 'Bearer ' + self.other['token']})
        self.assertEqual(self.activity.detail(response.headers['x-activity-id'])['user_id'], self.other['user']['id'])

    def test_filters_pagination_manual_labels_and_persistence(self):
        self.customer_login()
        self.client.post('/api/customer-agent/run', json={'message': 'test'})
        self.manager_login()
        response = self.client.get('/api/manager/events?risk_only=true&page=99&page_size=1')
        self.assertEqual(response.json()['total'], 1)
        self.assertEqual(response.json()['page'], 1)
        self.assertEqual(self.client.get('/api/manager/events', params={'user_id': self.other['user']['id']}).json()['total'], 0)
        self.assertEqual(self.client.get('/api/manager/events?since=2099-01-01').json()['total'], 0)
        self.assertEqual(self.client.get('/api/manager/events?page_size=101').status_code, 422)
        self.assertEqual(self.client.get('/api/manager/events?since=bad').status_code, 422)
        self.assertEqual(self.client.get('/api/manager/events?since=2026-10-12&until=2026-10-11').status_code, 422)
        user_id = self.user['user']['id']
        response = self.client.patch(f'/api/manager/users/{user_id}/lead', json={'status': 'not_interested', 'note': '已联系，暂时不需要'})
        self.assertEqual(response.status_code, 200)
        result = self.client.get('/api/manager/users?lead_status=not_interested&engagement=tried').json()
        self.assertEqual(result['users'][0]['id'], user_id)
        reopened = ActivityStore(self.activity.path)
        self.assertEqual(reopened.users(self.auth.users_by_id())['users'][0]['lead']['note'], '已联系，暂时不需要')
        self.assertEqual(self.client.get('/api/manager/events/missing').status_code, 404)
        self.assertEqual(self.client.get('/api/manager/overview').json()['risky_requests'], 1)

    def test_errors_selected_attacks_and_disabled_probes_are_not_risks(self):
        findings = risk_findings({'attack': {'attack_id': 'prompt_injection', 'attempted': True, 'success': False},
                                 'defense_signals': [{'status': 'error', 'blocked': False},
                                 {'status': 'safe', 'metadata': {'disabled_risks': ['harmful'], 'per_risk': {'harmful': {'flagged': True}}}}]})
        self.assertEqual(findings, [])

    def test_comparison_keeps_both_branches(self):
        findings = risk_findings({'baseline': {'verdict': 'compromised'}, 'defended': {'output_blocked': True}})
        self.assertEqual([r['branch'] for r in findings], ['baseline', 'defended'])

    def test_sse_parser_handles_byte_boundaries(self):
        capture = ResponseCapture(); capture.stream = True
        data = 'event: final\ndata: {"assistant_message":"中文字符"}\n\n'.encode()
        for byte in data:
            capture.feed(bytes([byte]))
        self.assertEqual(capture.result()['assistant_message'], '中文字符')
        self.assertTrue(capture.final)

    def test_recording_failure_does_not_fail_user_request(self):
        self.customer_login()
        from unittest.mock import patch
        with patch.object(self.activity, 'append', side_effect=OSError('disk full')):
            response = self.client.post('/api/customer-agent/run', json={'message': 'test'})
        self.assertEqual(response.status_code, 200)

    def test_asgi_stream_is_forwarded_before_completion_and_disconnect_recorded(self):
        async def check():
            messages = []
            async def app(scope, receive, send):
                await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'content-type', b'text/event-stream')]})
                await send({'type': 'http.response.body', 'body': b'event: delta\ndata: {"content":"first"}\n\n', 'more_body': True})
                self.assertEqual(len(messages), 2)  # No buffering until the final response.
                raise asyncio.CancelledError()
            async def receive():
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            async def send(message):
                messages.append(message)
            middleware = ActivityMiddleware(app, self.auth, self.activity)
            scope = {'type': 'http', 'path': '/api/customer-agent/run/stream', 'method': 'POST', 'scheme': 'http',
                     'headers': [(b'cookie', ('pm_session=' + self.user['session']).encode())], 'query_string': b'', 'server': ('test', 80)}
            with self.assertRaises(asyncio.CancelledError):
                await middleware(scope, receive, send)
        asyncio.run(check())
        record = self.activity.events()['events'][0]
        self.assertEqual(record['status'], 'interrupted')
        self.assertEqual(record['risk_count'], 0)


if __name__ == '__main__':
    unittest.main()
