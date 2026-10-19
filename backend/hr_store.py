"""Persistent, scene-local candidate metadata and screening records."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from jsonschema import validate

DATA_ROOT = Path(__file__).resolve().parents[1] / 'data' / 'hr_agent'
DEFAULT_DB_PATH = DATA_ROOT / 'state' / 'candidates.sqlite3'


def text_field(limit=4000):
    return {'type': 'string', 'maxLength': limit}


def list_field():
    return {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 500},
            'maxItems': 50, 'uniqueItems': True}


PROFILE_CHANGES_SCHEMA = {
    'type': 'object', 'minProperties': 1, 'additionalProperties': False,
    'properties': {
        'name': {**text_field(100), 'minLength': 1, 'pattern': r'\S'},
        'target_role': text_field(200),
        'skills': list_field(), 'strengths': list_field(), 'tags': list_field(),
        'work_years': {'type': 'number', 'minimum': 0, 'maximum': 80},
        'experience_summary': text_field(), 'project_summary': text_field(),
        'pending_verification': text_field(), 'notes': text_field(),
    },
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class CandidateStore:
    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = str(path)
        if self.path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute('PRAGMA foreign_keys = ON')
        self._db.execute('PRAGMA journal_mode = WAL')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY,
                profile TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS candidate_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
                changes TEXT NOT NULL, before_profile TEXT NOT NULL,
                source TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS screening_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
                decision TEXT NOT NULL CHECK(decision IN ('recommend_interview', 'reject')),
                reason TEXT NOT NULL, created_at TEXT NOT NULL
            );
        ''')
        seeds = json.loads((DATA_ROOT / 'candidates.json').read_text(encoding='utf-8'))
        now = timestamp()
        with self._db:
            for item in seeds:
                profile = dict(item)
                candidate_id = profile.pop('candidate_id')
                # Initialization never overwrites previously edited metadata.
                self._db.execute('INSERT OR IGNORE INTO candidates VALUES (?, ?, ?, ?, 1)',
                                 (candidate_id, encode(profile), now, now))

    def close(self):
        with self._lock:
            self._db.close()

    def resolve_name(self, name):
        """Resolve a human name without exposing database keys to the agent."""
        with self._lock:
            matches = [r['candidate_id'] for r in self._db.execute('SELECT candidate_id, profile FROM candidates')
                       if json.loads(r['profile'])['name'] == name.strip()]
        if len(matches) > 1:
            raise ValueError('存在同名档案，无法唯一确定要操作的人员')
        return matches[0] if matches else None

    def display_name(self, candidate_id):
        profile = self.get_candidate(candidate_id)
        return profile['name'] if profile else '未知人员'

    def public_view(self, value):
        """Remove storage keys, including identifiers in historical text."""
        with self._lock:
            names = {r['candidate_id']: json.loads(r['profile'])['name']
                     for r in self._db.execute('SELECT candidate_id, profile FROM candidates')}

        def render(item):
            if isinstance(item, list):
                return [render(v) for v in item]
            if isinstance(item, dict):
                result = {k: render(v) for k, v in item.items()
                          if k not in {'candidate_id', 'record_id', 'update_id', 'source_document_ids'}}
                if 'candidate_id' in item and 'name' not in result:
                    result['candidate_name'] = names.get(item['candidate_id'], '未知人员')
                if 'source_document_ids' in item:
                    result['sources'] = render(item['source_document_ids'])
                return result
            if isinstance(item, str):
                for key, name in names.items():
                    item = item.replace('hr-resume-' + key.lower(), name + '_简历.txt').replace(key, name)
                return item.replace('（JOB-001）', '').replace('JOB-001', '后端工程师')
            return item

        return render(value)

    @staticmethod
    def _profile(row):
        return {**json.loads(row['profile']), 'candidate_id': row['candidate_id'],
                'created_at': row['created_at'], 'updated_at': row['updated_at'],
                'revision': row['revision']}

    def list_candidates(self, query='', limit=20):
        with self._lock:
            rows = self._db.execute('''SELECT * FROM candidates
                WHERE instr(lower(candidate_id || ' ' || profile), lower(?)) > 0
                ORDER BY candidate_id LIMIT ?''', (query.strip(), limit)).fetchall()
            return [self._profile(row) for row in rows]

    def get_candidate(self, candidate_id):
        with self._lock:
            row = self._db.execute('SELECT * FROM candidates WHERE candidate_id = ?', (candidate_id,)).fetchone()
            if row is None:
                return None
            result = self._profile(row)
            result['screening_records'] = [self._screening(r) for r in self._db.execute(
                'SELECT * FROM screening_records WHERE candidate_id = ? ORDER BY id', (candidate_id,))]
            result['update_history'] = [
                {'update_id': r['id'], 'changes': json.loads(r['changes']),
                 'source': r['source'], 'created_at': r['created_at']}
                for r in self._db.execute('SELECT * FROM candidate_updates WHERE candidate_id = ? ORDER BY id',
                                          (candidate_id,))]
            return result

    def update_candidate(self, candidate_id, changes, source):
        validate(changes, PROFILE_CHANGES_SCHEMA)
        if not isinstance(source, str) or not source.strip() or len(source) > 1000:
            raise ValueError('请提供更新依据或资料来源（1–1000 字符）')
        encoded_changes = encode(changes)
        with self._lock, self._db:
            # Lock the database before reading so concurrent processes also
            # preserve unrelated fields when merging partial updates.
            self._db.execute('BEGIN IMMEDIATE')
            row = self._db.execute('SELECT * FROM candidates WHERE candidate_id = ?', (candidate_id,)).fetchone()
            if row is None:
                raise ValueError('候选人不存在，无法更新')
            profile = {**json.loads(row['profile']), **changes}
            now = timestamp()
            self._db.execute('UPDATE candidates SET profile = ?, updated_at = ?, revision = revision + 1 WHERE candidate_id = ?',
                             (encode(profile), now, candidate_id))
            self._db.execute('INSERT INTO candidate_updates(candidate_id, changes, before_profile, source, created_at) VALUES (?, ?, ?, ?, ?)',
                             (candidate_id, encoded_changes, row['profile'], source.strip(), now))
            result = self.get_candidate(candidate_id)
        return result

    @staticmethod
    def _screening(row):
        return {'record_id': f"HR-{row['id']}", 'candidate_id': row['candidate_id'],
                'decision': row['decision'], 'reason': row['reason'],
                'created_at': row['created_at'], 'simulated': True}

    def record_screening(self, candidate_id, decision, reason):
        if decision not in {'recommend_interview', 'reject'} or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError('筛选决定或理由无效')
        with self._lock, self._db:
            if not self._db.execute('SELECT 1 FROM candidates WHERE candidate_id = ?', (candidate_id,)).fetchone():
                raise ValueError('候选人不存在，无法保存筛选结果')
            cursor = self._db.execute('INSERT INTO screening_records(candidate_id, decision, reason, created_at) VALUES (?, ?, ?, ?)',
                                      (candidate_id, decision, reason, timestamp()))
            return self._screening(self._db.execute('SELECT * FROM screening_records WHERE id = ?', (cursor.lastrowid,)).fetchone())
