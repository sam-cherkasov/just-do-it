import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from personal_os.engine import Engine
from personal_os.store import Invalid
from personal_os.workspace import snapshot
from personal_os.workspace_server import make_server
from personal_os.today import local_date
from test_workspace import seed
from test_planner import fixture


class TodayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine, self.source, self.task, self.stream = seed(self.root)
        self.date = local_date('Europe/Madrid')

    def choose_payload(self, request='choose', **updates):
        data = dict(action='choose', date=self.date, task_id=self.task['id'], task_revision=1,
                    workstream_id=self.stream['id'], target='One finished example',
                    first_action='Open the fictional example', reason='My explicit local choice')
        data.update(updates)
        return dict(request_id=request, source=self.source, expected_revision=0, data=data)

    def choose(self):
        return self.engine.run('choose-day', self.choose_payload())['record']

    def control(self, action, revision=1, **extra):
        return self.engine.run('task-control', dict(request_id='control-'+action+'-'+str(revision), source=self.source,
            id=self.task['id'], expected_revision=revision, data=dict(action=action, reason='Fictional user decision', **extra)))

    def start(self, choice, task_revision=1, request='start'):
        return self.engine.run('focus', dict(request_id=request, source=self.source, data={
            'task_id': self.task['id'], 'task_revision': task_revision, 'workstream_id': choice['data'].get('workstream_id'),
            'day_choice_id': choice['id'], 'day_choice_revision': choice['revision'],
            'target': choice['data']['target'], 'minutes': 45}))

    def test_choice_reload_retry_and_second_tab_conflict(self):
        choice = self.choose()
        self.assertTrue(self.engine.run('choose-day', self.choose_payload())['replayed'])
        with self.assertRaisesRegex(Invalid, 'revision'):
            self.engine.run('choose-day', self.choose_payload('other-tab'))
        fresh = snapshot(Engine(self.root))
        self.assertEqual(fresh['day_choices'][0]['id'], choice['id'])
        self.assertEqual(fresh['relationships']['days'][0]['task_id'], self.task['id'])
        self.assertFalse(any(r['kind'] in ('plan', 'calendar', 'focus') for r in self.engine.store.records()))

    def test_change_result_keeps_identity_history_and_no_duplicate_task(self):
        choice = self.choose()
        payload = self.choose_payload('new-result', target='Smaller result')
        payload.update(id=choice['id'], expected_revision=1)
        changed = self.engine.run('choose-day', payload)['record']
        self.assertEqual(changed['id'], choice['id'])
        self.assertEqual(changed['revision'], 2)
        self.assertEqual(self.engine.store.get(choice['id'])['history'][0]['data']['target'], 'One finished example')
        self.assertEqual(len([r for r in self.engine.store.records() if r['kind'] == 'task']), 1)
        with self.assertRaisesRegex(Invalid, 'revision'):
            self.start(choice)

    def test_choice_and_session_keep_result_after_task_correction(self):
        choice = self.choose()
        self.control('edit', values={'title': 'Corrected title', 'next_action': 'A later suggestion'})
        session = self.start(choice, 2)['record']
        self.assertEqual(session['data']['first_action'], 'Open the fictional example')
        self.assertEqual(session['data']['target'], 'One finished example')
        self.assertEqual(session['data']['day_choice_id'], choice['id'])
        self.assertEqual(session['data']['task_revision'], 2)
        self.assertEqual(self.engine.store.get(choice['id'])['data'], choice['data'])
        self.engine.run('focus', dict(request_id='finish', source=self.source, id=session['id'], expected_revision=1,
            data={'status': 'closed', 'outcome': 'result', 'note': 'One example finished'}))
        self.assertEqual(self.engine.store.get(self.task['id'])['data']['status'], 'ready')
        self.assertEqual(self.engine.store.get(choice['id'])['data']['status'], 'selected')

    def test_midnight_does_not_carry_choice_or_allow_old_date_write(self):
        choice = self.choose()
        from datetime import date, timedelta
        tomorrow = (date.fromisoformat(self.date) + timedelta(days=1)).isoformat()
        with patch('personal_os.today.local_date', return_value=tomorrow):
            state = snapshot(self.engine)
            self.assertNotEqual(state['today'], choice['data']['date'])
            with self.assertRaisesRegex(Invalid, 'local day changed'):
                self.engine.run('choose-day', self.choose_payload('after-midnight'))
            with self.assertRaisesRegex(Invalid, 'today first'):
                self.start(choice)
            new_day = self.engine.run('choose-day', self.choose_payload('tomorrow-choice', date=tomorrow))['record']
            self.assertNotEqual(new_day['id'], choice['id'])

    def test_clear_choice_preserves_record_and_disallows_start(self):
        choice = self.choose()
        payload = dict(request_id='clear', source=self.source, id=choice['id'], expected_revision=1,
                       data={'action': 'clear', 'date': self.date, 'reason': 'Changed my mind'})
        cleared = self.engine.run('choose-day', payload)['record']
        self.assertEqual(cleared['data']['target'], choice['data']['target'])
        with self.assertRaisesRegex(Invalid, 'today first'):
            self.start(cleared)
        self.assertTrue(self.engine.run('choose-day', payload)['replayed'])

    def test_user_corrections_and_completion_survive_agent_refresh(self):
        self.control('edit', values={'title': 'User title', 'next_action': 'User action', 'chat_url': ''})
        self.control('done', revision=2)
        proposed = copy.deepcopy(self.task['record']['data'])
        proposed.update(title='Old automatic title', next_action='Rejected action', chat_url='codex://threads/old')
        result = self.engine.run('task', dict(request_id='refresh', source={'kind': 'agent_generated', 'reference': 'Synthetic reconciliation'},
            id=self.task['id'], expected_revision=3, data=proposed))
        data = result['record']['data']
        self.assertEqual(data['title'], 'User title')
        self.assertEqual(data['next_action'], 'User action')
        self.assertEqual(data['status'], 'done')
        self.assertEqual(data['chat_url'], '')
        self.assertNotIn('chat_ref', data)
        self.assertIn('status', result['protected_fields_retained'])
        self.assertEqual(len(snapshot(self.engine)['task_history'][self.task['id']]), 3)
        self.control('restore', revision=4)
        self.assertEqual(self.engine.store.get(self.task['id'])['data']['status'], 'ready')

    def test_later_waiting_and_closed_cannot_be_chosen_or_started(self):
        for action in ('later', 'wait', 'done', 'drop'):
            current = self.engine.store.get(self.task['id'])
            saved = self.control(action, current['revision'])['record']
            with self.assertRaisesRegex(Invalid, 'available'):
                self.engine.run('choose-day', self.choose_payload('choose-'+action, task_revision=saved['revision']))
            with self.assertRaisesRegex(Invalid, 'available'):
                self.engine.run('focus', dict(request_id='focus-'+action, source=self.source, data={
                    'task_id': self.task['id'], 'task_revision': saved['revision'], 'workstream_id': self.stream['id'],
                    'target': 'A result', 'minutes': 30}))
            self.control('restore', saved['revision'])

    def test_active_session_prevents_status_change_but_allows_text_correction(self):
        choice = self.choose()
        self.start(choice)
        with self.assertRaisesRegex(Invalid, 'already active'):
            self.control('done')
        self.control('edit', values={'title': 'Clarified title'})
        self.assertEqual(self.engine.store.get(self.task['id'])['data']['title'], 'Clarified title')

    def test_unassigned_task_can_be_chosen_and_worked_on(self):
        data = copy.deepcopy(self.stream['record']['data']); data.update(task_ids=[], questions=[])
        self.engine.run('workstream', dict(request_id='unassign', source=self.source, id=self.stream['id'], expected_revision=1, data=data))
        self.assertEqual(snapshot(self.engine)['tasks'][0]['id'], self.task['id'])
        choice = self.engine.run('choose-day', self.choose_payload(workstream_id=None))['record']
        self.assertIsNone(self.start(choice)['record']['data']['workstream_id'])

    def test_card_choice_links_same_task_and_preserves_manual_board(self):
        data = fixture(); data['cards'][0].update(selected=True, task_id=self.task['id'], task_revision=1,
            workstream_id=self.stream['id'], chat_url='codex://threads/fictional-plan-chat')
        board = self.engine.run('planner', dict(request_id='board', source=self.source, data=data))['record']
        choice = self.engine.run('choose-day', self.choose_payload(planner_id=board['id'], planner_revision=1, planner_card_id='example'))['record']
        session = self.start(choice)['record']
        self.assertEqual(session['data']['planner_card_id'], 'example')
        self.assertEqual(session['data']['chat_ref']['thread_id'], 'fictional-plan-chat')
        self.assertEqual(self.engine.store.get(board['id'])['revision'], 1)

    def test_stale_source_does_not_block_explicit_user_correction(self):
        source_id = self.stream['id']
        task = copy.deepcopy(self.task['record']['data']); task['sources'] = [{'id': source_id, 'revision': 1}]
        self.engine.run('task', dict(request_id='source-task', source=self.source, id=self.task['id'], expected_revision=1, data=task))
        source = self.engine.store.get(source_id); data = dict(source['data'], title='Updated source')
        self.engine.run('workstream', dict(request_id='source-change', source=self.source, id=source_id, expected_revision=1, data=data))
        updated = self.control('edit', revision=2, values={'title': 'User correction despite old evidence'})['record']
        self.assertEqual(updated['data']['sources'][0]['revision'], 1)
        self.assertTrue(updated['stale'])

    def test_rejects_invalid_actions_and_agent_day_choice(self):
        with self.assertRaises(Invalid): self.control('unknown')
        with self.assertRaises(Invalid): self.control('edit', values={'parents': []})
        with self.assertRaises(Invalid): self.control('edit', values={'chat_url': 'javascript:alert(1)'})
        with self.assertRaises(Invalid): self.control('later', until='2000-01-01')
        payload = self.choose_payload(); payload['source'] = {'kind': 'agent_generated', 'reference': 'A guess'}
        with self.assertRaises(Invalid): self.engine.run('choose-day', payload)

    def test_guard_requires_task_control_even_for_reported_source_updates(self):
        self.control('edit', values={'title': 'My wording'})
        data = copy.deepcopy(self.task['record']['data'])
        data.update(title='Old wording', next_action='New supported unprotected action')
        result = self.engine.run('task', dict(request_id='reported-source-refresh', source=self.source,
            id=self.task['id'], expected_revision=2, data=data))['record']
        self.assertEqual(result['data']['title'], 'My wording')
        self.assertEqual(result['data']['next_action'], 'New supported unprotected action')
        with self.assertRaisesRegex(Invalid, 'explicit user'):
            self.engine.run('task-control', dict(request_id='agent-cannot-unlock',
                source={'kind': 'agent_generated', 'reference': 'Guess'}, id=self.task['id'], expected_revision=3,
                data={'action': 'edit', 'reason': 'Guess', 'values': {'title': 'Old wording'}}))

    def test_http_routes_require_auth_preserve_revision_and_retry(self):
        server = make_server(self.root, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(origin + '/api/workspace') as response: token = json.load(response)['token']
        def post(path, payload, valid=True):
            return urllib.request.urlopen(urllib.request.Request(origin + path, data=json.dumps(payload).encode(), headers={
                'Content-Type': 'application/json', 'Origin': origin if valid else 'http://foreign.test', 'X-Workspace-Token': token}))
        payload = self.choose_payload()
        with self.assertRaises(urllib.error.HTTPError) as error: post('/api/day-choice', payload, False)
        self.assertEqual(error.exception.code, 403)
        with post('/api/day-choice', payload) as response: self.assertEqual(len(json.load(response)['day_choices']), 1)
        with post('/api/day-choice', payload) as response: self.assertEqual(len(json.load(response)['day_choices']), 1)
        payload['request_id'] = 'other-tab'
        with self.assertRaises(urllib.error.HTTPError) as error: post('/api/day-choice', payload)
        self.assertEqual(error.exception.code, 409)
        control = dict(request_id='http-later', id=self.task['id'], expected_revision=1, data={'action': 'later', 'reason': 'Not now'})
        with post('/api/task-control', control) as response: self.assertTrue(json.load(response)['tasks'][0]['data']['deferred'])
        with post('/api/task-control', control) as response: self.assertEqual(json.load(response)['tasks'][0]['revision'], 2)
        with urllib.request.urlopen(origin + '/today.js') as response: self.assertEqual(response.status, 200)


if __name__ == '__main__':
    unittest.main()
