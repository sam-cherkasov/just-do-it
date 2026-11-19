import copy
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
from test_workspace import seed


class WorkItemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine, self.source, self.task, self.stream = seed(self.root)

    def call(self, request, data, record=None):
        payload = dict(request_id=request, source=self.source, data=data)
        if record:
            payload.update(id=record['id'], expected_revision=record['revision'])
        return self.engine.run('workspace-item', payload)

    def start(self, request='start', **extra):
        return self.engine.run('focus', dict(request_id=request, source=self.source, data={
            'task_id': self.task['id'], 'task_revision': self.engine.store.get(self.task['id'])['revision'],
            'workstream_id': self.stream['id'], 'target': 'One result', 'minutes': 45, **extra}))['record']

    def close(self, session, step='Resume the exact saved step'):
        return self.engine.run('focus', dict(request_id='close-'+session['id'], source=self.source,
            id=session['id'], expected_revision=session['revision'], data={
                'status': 'closed', 'outcome': 'progress', 'note': 'Saved result', 'next_action': step}))['record']

    def test_capture_retry_restart_and_no_focus_or_task_side_effect(self):
        self.start()
        before = {r['id']: r for r in self.engine.store.records()}
        data = {'category': 'note', 'title': 'A thought', 'body': 'Original <words>\nsecond line'}
        first = self.call('capture', data)
        self.assertTrue(self.call('capture', data)['replayed'])
        fresh = Engine(self.root)
        self.assertEqual(fresh.store.get(first['id'])['data']['body'], data['body'])
        self.assertEqual({r['id']: r for r in fresh.store.records() if r['id'] in before}, before)
        self.assertEqual(len(snapshot(fresh)['workspace_items']), 1)
        self.assertEqual(len(snapshot(fresh)['sessions']), 1)

    def test_edits_conflict_and_preserve_original_and_links(self):
        note = self.call('note', {'category': 'note', 'title': 'Original', 'body': 'Original body'})['record']
        edit = dict(action='edit', title='Revised', body='Updated', task_id=self.task['id'], reason='Attach my idea')
        changed = self.call('edit', edit, note)['record']
        with self.assertRaisesRegex(Invalid, 'revision'):
            self.call('stale-edit', {**edit, 'title': 'Stale'}, note)
        record = self.engine.store.get(note['id'])
        self.assertEqual(record['history'][0]['data']['title'], 'Original')
        self.assertEqual(changed['data']['task_id'], self.task['id'])
        self.assertEqual(snapshot(self.engine)['relationships']['items'][0]['item_id'], note['id'])

    def test_material_validation_and_snapshot_excludes_unrelated_private_data(self):
        for i, url in enumerate(['javascript:alert(1)', 'data:text/html,x', 'file:///etc/passwd',
                                 'https://name:secret@example.test/a', 'https://a\\b', 'https://x/a\nb',
                                 '//example.test', 'https://example.test:invalid']):
            with self.assertRaises(ValueError):
                self.call('bad-'+str(i), {'category': 'material', 'title': 'Bad', 'task_id': self.task['id'], 'url': url})
        for i, url in enumerate(['https://example.test/doc#part', 'http://127.0.0.1:8770/', 'codex://threads/fictional']):
            self.call('material-'+str(i), {'category': 'material', 'title': '<script>literal</script>', 'task_id': self.task['id'], 'url': url})
        self.engine.run('diary', dict(request_id='diary', source=self.source, data={'text': 'SECRET_DIARY', 'event_date': '2026-11-05'}))
        view = snapshot(self.engine)
        self.assertNotIn('SECRET_DIARY', json.dumps(view))
        self.assertNotIn('calendar_account', json.dumps(view))
        self.assertEqual(len(view['workspace_items']), 3)

    def test_question_requires_task_condition_and_distinct_dependency(self):
        good = dict(category='question', title='Which option?', task_id=self.task['id'], condition='Pick one based on evidence')
        for i, changes in enumerate([{'task_id': None}, {'condition': ''}, {'depends_on_task_id': self.task['id']},
                                      {'depends_on_task_id': self.stream['id']}, {'task_id': self.stream['id']} ]):
            with self.assertRaises(Invalid):
                self.call('invalid-'+str(i), {**good, **changes})
        task_data = copy.deepcopy(self.task['record']['data'])
        other = self.engine.run('task', dict(request_id='other', source=self.source, data=task_data))
        question = self.call('q', {**good, 'depends_on_task_id': other['id']})['record']
        self.engine.run('task-control', dict(request_id='done', source=self.source, id=other['id'], expected_revision=1,
            data={'action': 'done', 'reason': 'Synthetic completion'}))
        self.assertEqual(self.engine.store.get(question['id'])['data']['status'], 'open')
        before = self.engine.store.get(self.task['id'])
        answer = self.call('answer', dict(action='resolve', resolution='Option A', reason='Condition satisfied'), question)['record']
        self.assertEqual(answer['data']['status'], 'resolved')
        self.assertEqual(self.engine.store.get(self.task['id']), before)
        archived = self.call('archive', {'action': 'archive', 'reason': 'Keep history'}, answer)['record']
        reopened = self.call('reopen', {'action': 'reopen', 'reason': 'New evidence'}, archived)['record']
        self.assertNotIn('resolution', reopened['data'])
        self.assertTrue(any(v['data'].get('resolution') == 'Option A' for v in self.engine.store.get(question['id'])['history']))

    def test_explicit_actions_and_lifecycle_validation(self):
        with self.assertRaises(Invalid):
            self.engine.run('workspace-item', dict(request_id='agent', source={'kind': 'agent_generated', 'reference': 'Guess'},
                data={'category': 'note', 'title': 'Unapproved'}))
        note = self.call('note', {'category': 'note', 'title': 'A note'})['record']
        with self.assertRaises(Invalid):
            self.call('resolve-note', {'action': 'resolve', 'resolution': 'Done', 'reason': 'Because'}, note)
        archived = self.call('archive', {'action': 'archive', 'reason': 'Park it'}, note)['record']
        with self.assertRaises(Invalid):
            self.call('edit-archive', {'action': 'edit', 'title': 'Change', 'reason': 'Because'}, archived)
        self.assertEqual(self.engine.store.get(note['id'])['revision'], 2)

    def test_continuation_freezes_saved_step_and_uses_current_chat(self):
        prior = self.close(self.start())
        self.engine.run('task-control', dict(request_id='chat', source=self.source, id=self.task['id'], expected_revision=1,
            data={'action': 'edit', 'reason': 'New chat and default step', 'values': {'chat_url': 'codex://threads/new-chat', 'next_action': 'Current generic action'}}))
        resumed = self.start('resume', continuation_id=prior['id'], continuation_revision=prior['revision'])
        self.assertEqual(resumed['data']['first_action'], prior['data']['next_action'])
        self.assertEqual(resumed['data']['chat_url'], 'codex://threads/new-chat')
        self.assertEqual(Engine(self.root).store.get(resumed['id'])['data']['continuation_id'], prior['id'])
        self.assertEqual(self.engine.store.get(prior['id'])['revision'], 2)
        self.assertEqual(self.engine.store.get(self.task['id'])['data']['next_action'], 'Current generic action')

    def test_invalid_continuation_does_not_create_a_session(self):
        prior = self.close(self.start())
        for i, changes in enumerate([{'continuation_revision': 1}, {'continuation_id': self.task['id']},
                                     {'day_choice_id': 'another'}, {'planner_id': 'another'}]):
            with self.assertRaises(Invalid):
                self.start('bad-'+str(i), **{'continuation_id': prior['id'], 'continuation_revision': 2, **changes})
        other_data = copy.deepcopy(self.task['record']['data'])
        other = self.engine.run('task', dict(request_id='other', source=self.source, data=other_data))
        with self.assertRaises(Invalid):
            self.start('foreign', continuation_id=prior['id'], continuation_revision=2, task_id=other['id'], workstream_id=None)
        no_step = self.close(self.start('blank'), step='')
        with self.assertRaises(Invalid):
            self.start('no-step', continuation_id=no_step['id'], continuation_revision=2)
        self.assertFalse(any(s['data']['status'] == 'active' for s in snapshot(self.engine)['sessions']))

    def test_http_guards_retry_conflict_and_archive(self):
        server = make_server(self.root, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(origin+'/api/workspace') as response:
            token = json.load(response)['token']
        def post(payload, authenticated=True):
            headers = {'Content-Type': 'application/json', 'Origin': origin}
            if authenticated:
                headers['X-Workspace-Token'] = token
            req = urllib.request.Request(origin+'/api/workspace-item', json.dumps(payload).encode(), headers=headers)
            with urllib.request.urlopen(req) as response:
                return json.load(response)
        payload = {'request_id': 'http-note', 'data': {'category': 'note', 'title': 'HTTP idea'}}
        with self.assertRaises(urllib.error.HTTPError) as failure:
            post(payload, False)
        self.assertEqual(failure.exception.code, 403)
        result = post(payload)
        self.assertEqual(len(post(payload)['workspace_items']), 1)
        item = result['workspace_items'][0]
        archived = {'request_id': 'http-archive', 'id': item['id'], 'expected_revision': 1, 'data': {'action': 'archive', 'reason': 'Done reviewing'}}
        self.assertEqual(post(archived)['workspace_items'][0]['data']['status'], 'archived')
        with self.assertRaises(urllib.error.HTTPError) as failure:
            post({**archived, 'request_id': 'stale'})
        self.assertEqual(failure.exception.code, 409)
