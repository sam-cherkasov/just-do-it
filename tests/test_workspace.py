import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from personal_os.engine import Engine
from personal_os.store import Invalid
from personal_os.workspace import snapshot
from personal_os.workspace_server import make_server


def seed(root):
    engine = Engine(root)
    engine.init({'calendar_account': 'fiction@example.test', 'synthetic': True})
    source = {'kind': 'synthetic', 'reference': 'Fictional workspace test'}
    def run(op, request, data, **extra):
        return engine.run(op, dict(request_id=request, source=source, data=data, **extra))
    node = run('node', 'node', {'title': 'Fictional area', 'type': 'area', 'mode': 'growth', 'parents': []})
    task = run('task', 'task', {'title': 'Проверить учебный пример', 'parents': [node['id']], 'intent': 'proposed', 'status': 'ready', 'priority': 'unranked', 'next_action': 'Открыть вымышленный документ и проверить один пример.', 'rationale': 'Synthetic next action.', 'sources': []})
    stream = run('workstream', 'stream', {'title': 'Учебный проект', 'summary': 'Собрать ясную историю и один убедительный пример.', 'outcome': 'Один понятный пример для учебной страницы.', 'context': 'Вымышленный проект для проверки интерфейса.', 'color': 'lilac', 'task_ids': [task['id']], 'source_ids': [], 'sources': [], 'questions': [{'text': 'Какой пример объясняет идею лучше всего?', 'task_id': task['id']}], 'chats': []})
    return engine, source, task, stream


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine, self.source, self.task, self.stream = seed(self.root)

    def start(self, request='start'):
        return dict(request_id=request, source=self.source, data={'workstream_id': self.stream['id'], 'task_id': self.task['id'], 'task_revision': 1, 'target': 'One clear example', 'minutes': 60})

    def test_session_survives_reload_and_close_is_explicit(self):
        p = self.start()
        created = self.engine.run('focus', p)
        self.assertTrue(self.engine.run('focus', p)['replayed'])
        fresh = Engine(self.root)
        self.assertEqual(snapshot(fresh)['sessions'][0]['data']['target'], 'One clear example')
        with self.assertRaisesRegex(Invalid, 'already active'):
            fresh.run('focus', self.start('second'))
        finish = dict(request_id='finish', source=self.source, id=created['id'], expected_revision=1,
                      data={'status': 'closed', 'outcome': 'progress', 'note': 'Example drafted', 'next_action': 'Review the ending'})
        closed = fresh.run('focus', finish)
        self.assertEqual(closed['record']['data']['title'], self.task['record']['data']['title'])
        self.assertTrue(fresh.run('focus', finish)['replayed'])
        self.assertEqual(fresh.store.get(self.task['id'])['data']['status'], 'ready')
        self.assertEqual(fresh.store.get(created['id'])['history'][0]['data']['status'], 'active')
        fresh.run('focus', self.start('next'))
        self.assertEqual(len(snapshot(fresh)['sessions']), 2)
        self.assertFalse(any(r['kind'] in ('calendar', 'plan') for r in fresh.store.records()))

    def test_invalid_foreign_task_budget_and_stale_revision(self):
        for updates in ({'task_revision': 2}, {'minutes': 0}, {'minutes': True}, {'target': ''}, {'task_id': self.stream['id']}):
            p = self.start(); p['data'].update(updates)
            with self.assertRaises(Invalid):
                self.engine.run('focus', p)
        created = self.engine.run('focus', self.start())
        with self.assertRaises(Invalid):
            self.engine.run('focus', dict(request_id='bad-close', source=self.source, id=created['id'], expected_revision=1, data={'status': 'closed', 'outcome': 'result', 'note': ''}))
        self.assertEqual(self.engine.store.get(created['id'])['revision'], 1)

    def test_dashboard_excludes_diary_and_secrets_and_rejects_bad_links(self):
        self.engine.run('diary', dict(request_id='private', source=self.source, data={'text': 'Fictional private note', 'event_date': '2026-11-03'}))
        self.assertNotIn('Fictional private note', json.dumps(snapshot(self.engine)))
        data = dict(self.stream['record']['data'])
        data['chats'] = [{'title': 'Bad', 'url': 'javascript:alert(1)', 'activity_at': '2026-11-03'}]
        with self.assertRaises(Invalid):
            self.engine.run('workstream', dict(request_id='bad-link', source=self.source, data=data))

    def test_source_reconciliation_can_reference_updated_workstream(self):
        source = self.engine.run('register-source', dict(request_id='chat', source=self.source,
            data={'title': 'Fictional chat', 'source_type': 'chat', 'locator': 'fictional-chat', 'scope': 'Synthetic updates'}))
        from personal_os.store import now
        check = self.engine.run('check-source', dict(request_id='check', source=self.source,
            data={'source_id': source['id'], 'source_revision': 1, 'status': 'ok', 'checked_at': now(),
                  'observed_revision': 'user-message', 'fingerprint': 'a' * 64, 'coverage': 'One fictional user message'}))
        self.engine.run('review-source', dict(request_id='review', source=self.source,
            data={'check_id': check['id'], 'outcome': 'reconciled', 'summary': 'Updated fictional direction',
                  'records': [{'id': self.stream['id'], 'revision': 1}]}))
        self.assertEqual(self.engine.context()['source_health'][0]['state'], 'reviewed')

    def test_context_snapshot_does_not_cache_across_mutations(self):
        self.engine.context()
        data = dict(self.stream['record']['data'], summary='Changed after the first read')
        self.engine.run('workstream', dict(request_id='update-stream', source=self.source,
            id=self.stream['id'], expected_revision=1, data=data))
        loaded = next(r for r in self.engine.context()['records'] if r['id'] == self.stream['id'])
        self.assertEqual(loaded['data']['summary'], 'Changed after the first read')
        from personal_os.view import render
        self.assertIn('Changed after the first read', render(self.engine).read_text())

    def test_http_auth_retry_conflict_and_path_allowlist(self):
        server = make_server(self.root, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(origin + '/api/workspace') as response:
            boot = json.load(response)
        def post(payload, valid=True):
            return urllib.request.urlopen(urllib.request.Request(origin + '/api/focus', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Origin': origin if valid else 'http://foreign.test', 'X-Workspace-Token': boot['token']}))
        with self.assertRaises(urllib.error.HTTPError) as error:
            post(self.start(), False)
        self.assertEqual(error.exception.code, 403)
        with post(self.start()) as response:
            result = json.load(response)
        self.assertEqual(len(result['sessions']), 1)
        with post(self.start()) as response:
            self.assertEqual(len(json.load(response)['sessions']), 1)
        with self.assertRaises(urllib.error.HTTPError) as error:
            post(self.start('conflict'))
        self.assertEqual(error.exception.code, 409)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(origin + '/personal/config.json')
        self.assertEqual(error.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(origin + '/api/workspace', headers={'Host': 'attacker.test'}))
        self.assertEqual(error.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
