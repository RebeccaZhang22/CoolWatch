"""Directory separation and standalone service contracts."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

from manager.app import create_app
from manager.auth import ManagerAuthStore, COOKIE
from manager.config import ManagerConfig, MANAGER_ROOT
from manager.activity_store import ActivityStore
from manager.user_directory import UserDirectory


class StandaloneTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = self.root / 'data'
        self.user_db = self.root / 'customer.db'
        with sqlite3.connect(self.user_db) as db:
            db.execute('CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT, role TEXT, created_at TEXT, password_digest TEXT)')
            db.execute("INSERT INTO users VALUES ('usr_test','visitor@example.test','admin','2026-10-12','not-exposed')")
        config = ManagerConfig(MANAGER_DATA_DIR=self.data, MANAGER_USER_DB=self.user_db,
                               MANAGER_USAGE_LOG=self.root / 'usage.jsonl', MANAGER_EMAIL='', MANAGER_PASSWORD='')
        self.managers = ManagerAuthStore(self.data / 'manager.db')
        self.managers.provision('owner@example.test', 'standalone-test-password')
        self.client = TestClient(create_app(config))
        self.addCleanup(self.client.close)

    def login(self):
        response = self.client.post('/api/manager/login', json={'email':'owner@example.test','password':'standalone-test-password'})
        self.assertEqual(response.status_code, 200, response.text)

    def test_standalone_serves_real_pages_and_protects_console(self):
        self.assertEqual(self.client.get('/health').json()['status'], 'ok')
        for path in ['/', '/manager/', '/manager/index.html', '/manager/?demo=1', '/admin.html']:
            response = self.client.get(path)
            self.assertTrue(str(response.url).endswith('/manager/login.html'), response.url)
        login = self.client.get('/manager/login.html')
        self.assertIn('登录管理中心', login.text)
        self.assertEqual(login.headers['x-frame-options'], 'DENY')
        self.assertEqual(self.client.get('/manager/manager.css').status_code, 200)
        self.assertEqual(self.client.get('/api/manager/users').status_code, 401)
        self.login()
        response = self.client.get('/manager/')
        self.assertIn('体验概览', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_data_and_customer_metadata_are_separate(self):
        self.login()
        users = self.client.get('/api/manager/users').json()['users']
        self.assertEqual(users[0]['id'], 'usr_test')
        self.assertNotIn('password_digest', users[0])
        self.assertEqual(len(users), 1)  # Managers are not inserted into customer accounts.
        for path in ['/data/manager.db', '/manager/data/manager.db', '/manager/../data/manager.db', '/manager/%2e%2e/data/manager.db', '/.env', '/manager/.env']:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertTrue((self.data / 'manager.db').exists())
        self.assertTrue((self.data / 'activity.db').exists())
        self.assertFalse((self.root / 'manager.db').exists())

    def test_external_activity_writes_are_visible_without_restart(self):
        self.login()
        self.assertEqual(self.client.get('/api/manager/events').json()['total'], 0)
        ActivityStore(self.data / 'activity.db').append('usr_test', kind='interaction', name='click')
        events = self.client.get('/api/manager/events').json()['events']
        self.assertEqual(events[0]['email'], 'visitor@example.test')

    def test_customer_collector_is_only_on_demo_host(self):
        self.assertEqual(self.client.post('/api/telemetry/events', json={'events': []}).status_code, 404)
        self.assertEqual(self.client.post('/api/auth/login', json={}).status_code, 404)
        self.assertEqual(self.client.get('/api/admin/users').status_code, 401)
        self.login()
        self.assertEqual(self.client.get('/api/admin/users').json()['total'], 1)
        self.assertEqual(self.client.get('/api/admin/usage').json()['total'], 0)

    def test_directory_only_reads_explicit_public_columns(self):
        users = UserDirectory(self.user_db).users_by_id()
        self.assertEqual(set(users['usr_test']), {'id', 'email', 'role', 'created_at'})
        self.assertEqual(UserDirectory(self.root / 'missing.db').users_by_id(), {})

    def test_relative_paths_are_based_on_manager_directory(self):
        config = ManagerConfig(MANAGER_DATA_DIR='data', MANAGER_USER_DB='../.runtime/prospectmonitor.db')
        self.assertEqual(config.data_dir, MANAGER_ROOT / 'data')
        self.assertEqual(config.user_db, MANAGER_ROOT.parent / '.runtime/prospectmonitor.db')

    def test_standalone_import_does_not_load_demo_or_models(self):
        code = 'import sys; from manager.app import create_app; assert not any(k == "backend" or k.startswith("backend.") or k == "torch" for k in sys.modules)'
        result = subprocess.run([sys.executable, '-c', code], cwd=MANAGER_ROOT.parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
