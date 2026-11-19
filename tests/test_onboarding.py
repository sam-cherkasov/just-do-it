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


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'workspace'
        self.engine = Engine(self.root)
        self.engine.init({'display_name': 'Example', 'timezone': 'UTC', 'synthetic': True})
        self.source = {'kind': 'synthetic', 'reference': 'Fictional first-use test'}

    def payload(self, key, data):
        return {'request_id': key, 'source': self.source, 'data': data}

    def direction(self):
        return self.engine.run('create-workstream', self.payload('direction',
            {'title': 'Learning', 'outcome': 'A clear explanation', 'color': 'mint'}))

    def test_empty_profile_needs_no_calendar_and_cannot_be_overwritten(self):
        config = self.engine.store.config()
        self.assertIsNone(config['calendar_account'])
        self.assertIsNone(config['calendar_provider'])
        self.assertEqual(snapshot(self.engine)['tasks'], [])
        with self.assertRaises(Invalid):
            self.engine.init({'display_name': 'Other', 'timezone': 'UTC'})
        self.assertEqual(self.engine.store.config(), config)
        with self.assertRaisesRegex(Invalid, 'not configured'):
            self.engine.run('calendar', self.payload('calendar', {}))

    def test_direction_task_choice_session_and_continuation_survive_restart(self):
        stream = self.direction()
        p = self.payload('task', {'workstream_id': stream['id'], 'title': 'Draft an example', 'next_action': 'Open an empty page'})
        task_id = self.engine.run('create-task', p)['created_task_id']
        self.assertEqual(self.engine.run('create-task', p)['created_task_id'], task_id)
        self.assertEqual(len(snapshot(self.engine)['tasks']), 1)
        self.engine = Engine(self.root)
        choice = self.engine.run('choose-day', {**self.payload('today', {'action': 'choose', 'date': snapshot(self.engine)['today'],
            'task_id': task_id, 'task_revision': 1, 'workstream_id': stream['id'], 'target': 'One useful example',
            'first_action': 'Open a page', 'reason': 'My choice'}), 'expected_revision': 0})
        session = self.engine.run('focus', self.payload('focus', {'task_id': task_id, 'task_revision': 1,
            'workstream_id': stream['id'], 'target': 'One example', 'minutes': 30,
            'day_choice_id': choice['id'], 'day_choice_revision': 1}))
        self.engine.run('focus', {**self.payload('finish', {'status': 'closed', 'outcome': 'progress',
            'note': 'Drafted the opening', 'next_action': 'Write the ending'}), 'id': session['id'], 'expected_revision': 1})
        continued = self.engine.run('focus', self.payload('continue', {'task_id': task_id, 'task_revision': 1,
            'workstream_id': stream['id'], 'target': 'Finish example', 'minutes': 30,
            'continuation_id': session['id'], 'continuation_revision': 2}))
        self.assertEqual(continued['record']['data']['first_action'], 'Write the ending')
        self.assertEqual(self.engine.store.get(task_id)['data']['status'], 'ready')
        self.assertFalse(any(r['kind'] in ('calendar', 'plan', 'source') for r in self.engine.store.records()))

    def test_invalid_creation_writes_nothing_and_does_not_allow_generated_intent(self):
        for data in ({'title': '', 'outcome': 'Text', 'color': 'mint'},
                     {'title': 'Name', 'outcome': 'Text', 'color': 'invalid'}):
            with self.assertRaises(Invalid):
                self.engine.run('create-workstream', self.payload('invalid', data))
        self.assertEqual(self.engine.store.records(), [])
        stream = self.direction()
        before = len(self.engine.store.records())
        for changes in ({'title': ''}, {'next_action': ''}, {'workstream_id': stream['record']['data']['area_id']}):
            with self.assertRaises(Invalid):
                self.engine.run('create-task', self.payload('bad-task', {'title': 'Task', 'next_action': 'Step', 'workstream_id': stream['id'], **changes}))
        with self.assertRaises(Invalid):
            self.engine.run('create-workstream', {'request_id': 'agent', 'source': {'kind': 'agent_generated', 'reference': 'Not user choice'},
                'data': {'title': 'Name', 'outcome': 'Text'}})
        self.assertEqual(len(self.engine.store.records()), before)

    def test_retry_recovers_interrupted_task_link_and_preserves_concurrent_direction(self):
        stream = self.direction()
        p = self.payload('task', {'workstream_id': stream['id'], 'title': 'Draft example', 'next_action': 'Open page'})
        original = self.engine.store.save
        def interrupted(kind, *args, **kwargs):
            if kind == 'workstream':
                raise OSError('Synthetic disk interruption')
            return original(kind, *args, **kwargs)
        with patch.object(self.engine.store, 'save', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.engine.run('create-task', p)
        self.assertEqual(len(snapshot(self.engine)['tasks']), 1)
        self.engine.run('workstream', {**self.payload('edit', {**stream['record']['data'], 'summary': 'Concurrent update'}),
            'id': stream['id'], 'expected_revision': 1})
        result = self.engine.run('create-task', p)
        self.assertEqual(self.engine.store.get(stream['id'])['data']['summary'], 'Concurrent update')
        self.assertEqual(self.engine.store.get(stream['id'])['data']['task_ids'], [result['created_task_id']])
        self.assertTrue(self.engine.run('create-task', p)['replayed'])
        self.assertEqual(len(snapshot(self.engine)['tasks']), 1)
        changed = copy.deepcopy(p); changed['data']['title'] = 'Different input'
        with self.assertRaisesRegex(Invalid, 'different input'):
            self.engine.run('create-task', changed)

    def test_retry_recovers_direction_without_duplicate_area(self):
        original = self.engine.store.save
        def interrupted(kind, *args, **kwargs):
            if kind == 'workstream':
                raise OSError('Synthetic interruption')
            return original(kind, *args, **kwargs)
        with patch.object(self.engine.store, 'save', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.direction()
        self.direction(); self.direction()
        self.assertEqual(len(self.engine.store.records()), 2)

    def test_existing_direction_without_area_can_accept_new_task(self):
        stream = self.engine.run('workstream', self.payload('old', {'title': 'Existing', 'summary': 'Saved context',
            'outcome': 'Result', 'color': 'blue', 'task_ids': []}))
        self.engine.run('create-task', self.payload('new', {'workstream_id': stream['id'], 'title': 'Task', 'next_action': 'Step'}))
        self.assertEqual(len(self.engine.store.get(stream['id'])['data']['task_ids']), 1)

    def test_http_first_run_auth_repeat_and_existing_profile_protection(self):
        root = Path(self.temp.name) / 'fresh'
        server = make_server(root, 0, allow_setup=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(origin + '/api/workspace') as response:
            boot = json.load(response)
        self.assertTrue(boot['needs_setup']); self.assertFalse(root.exists())
        def post(route, data, valid=True):
            request = urllib.request.Request(origin + route, data=json.dumps({'request_id': route, 'data': data}).encode(),
                headers={'Content-Type': 'application/json', 'Origin': origin if valid else 'http://foreign.test', 'X-Workspace-Token': boot['token']})
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        setup = {'display_name': 'Fictional user', 'timezone': 'Pacific/Auckland'}
        with self.assertRaises(urllib.error.HTTPError) as error:
            post('/api/setup', setup, False)
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError):
            post('/api/setup', {**setup, 'timezone': 'Invalid/Zone'})
        self.assertFalse((root/'personal/config.json').exists())
        data = post('/api/setup', setup)
        self.assertFalse(data['needs_setup']); self.assertFalse(data['calendar_configured'])
        self.assertEqual(post('/api/setup', setup)['tasks'], [])
        with self.assertRaises(urllib.error.HTTPError):
            post('/api/setup', {**setup, 'display_name': 'Changed'})
        stream = post('/api/create-workstream', {'title': 'Study', 'outcome': 'Explain one idea', 'color': 'mint'})['created_id']
        data = post('/api/create-task', {'workstream_id': stream, 'title': 'Draft', 'next_action': 'Open page'})
        self.assertEqual(data['tasks'][0]['id'], data['created_id'])
        again = post('/api/create-task', {'workstream_id': stream, 'title': 'Draft', 'next_action': 'Open page'})
        self.assertEqual(again['created_id'], data['created_id'])
        self.assertEqual(len(again['tasks']), 1)

    def test_launcher_rejects_unrelated_nonempty_data_directory(self):
        root = Path(self.temp.name)/'unrelated'; root.mkdir(); (root/'keep.txt').write_text('Keep')
        with self.assertRaisesRegex(ValueError, 'пустой'):
            make_server(root, 0, allow_setup=True)
        self.assertFalse((root/'personal').exists())
