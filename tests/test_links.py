import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from personal_os.engine import Engine
from personal_os.links import chat_reference, projection
from personal_os.store import Invalid
from personal_os.workspace_server import make_server
from test_planner import fixture
from test_workspace import seed


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine, self.source, self.task, self.stream = seed(self.root)
        board = fixture()
        board['cards'][0].update(selected=True, chat_url='codex://threads/fictional-chat',
                                 placement={'date': '2026-11-03', 'start_minute': 600})
        self.board = self.run_op('planner', 'board', board)

    def run_op(self, op, request, data, **extra):
        return self.engine.run(op, dict(request_id=request, source=self.source, data=data, **extra))

    def link_payload(self):
        return dict(request_id='link', source=self.source, id=self.board['id'], expected_revision=1,
                    data={'links': [{'card_id': 'example', 'task_id': self.task['id'], 'task_revision': 1,
                                     'workstream_id': self.stream['id'], 'reason': 'Reviewed synthetic identity'}]})

    def linked(self):
        return self.engine.run('link-planner-cards', self.link_payload())['record']

    def start(self, board):
        return self.run_op('focus', 'start', dict(workstream_id=self.stream['id'], task_id=self.task['id'],
            task_revision=1, planner_id=board['id'], planner_revision=board['revision'], planner_card_id='example',
            target=board['data']['cards'][0]['outcome'], minutes=60))

    def test_migration_only_links_and_replay(self):
        before = copy.deepcopy(self.board['record']['data']['cards'][0])
        board = self.linked()
        after = board['data']['cards'][0]
        self.assertEqual({k: after[k] for k in before}, before)
        self.assertEqual(board['revision'], 2)
        self.assertTrue(self.engine.run('link-planner-cards', self.link_payload())['replayed'])
        self.assertEqual(len([r for r in self.engine.store.records() if r['kind'] == 'task']), 1)

    def test_session_preserves_snapshot_and_close_does_not_complete_card_or_task(self):
        board = self.linked()
        session = self.start(board)['record']
        self.assertEqual(session['data']['first_action'], 'Open a blank file')
        self.assertEqual(session['data']['chat_ref']['thread_id'], 'fictional-chat')
        data = copy.deepcopy(board['data'])
        data['cards'] = []
        self.run_op('planner', 'remove', data, id=board['id'], expected_revision=2)
        result = projection(Engine(self.root).store.records())['sessions'][0]
        self.assertTrue(result['planner_changed'])
        self.assertTrue(result['card_missing'])
        closed = self.run_op('focus', 'finish', {'status': 'closed', 'outcome': 'result', 'note': 'Fictional result'},
                            id=session['id'], expected_revision=1)['record']
        self.assertEqual(closed['data']['target'], 'A draft')
        self.assertEqual(closed['data']['planner_revision'], 2)
        self.assertEqual(self.engine.store.get(self.task['id'])['data']['status'], 'ready')

    def test_refresh_does_not_rewrite_manual_card(self):
        board = self.linked()
        task = copy.deepcopy(self.task['record']['data'])
        task.update(title='Updated context', next_action='A new possible action')
        self.run_op('task', 'refresh', task, id=self.task['id'], expected_revision=1)
        data = copy.deepcopy(board['data'])
        data['cards'][0]['note'] = 'Still my choice'
        saved = self.run_op('planner', 'note', data, id=board['id'], expected_revision=2)['record']
        self.assertEqual(saved['data']['cards'][0]['task_revision'], 1)
        self.assertEqual(saved['data']['cards'][0]['first_action'], 'Open a blank file')
        self.assertTrue(projection(self.engine.store.records())['cards'][0]['task_changed'])
        data['cards'][0]['task_revision'] = 2
        with self.assertRaisesRegex(Invalid, 'Relink explicitly'):
            self.run_op('planner', 'rewrite', data, id=board['id'], expected_revision=3)

    def test_invalid_link_and_stale_start_are_rejected(self):
        payload = self.link_payload()
        payload['data']['links'][0]['task_revision'] = 2
        with self.assertRaises(Invalid):
            self.engine.run('link-planner-cards', payload)
        board = self.linked()
        stale = copy.deepcopy(board); stale['revision'] = 1
        with self.assertRaisesRegex(Invalid, 'Planner revision'):
            self.start(stale)
        data = copy.deepcopy(board['data'])
        data['cards'][0].update(selected=False, placement=None)
        unselected = self.run_op('planner', 'unselect', data, id=board['id'], expected_revision=2)['record']
        with self.assertRaisesRegex(Invalid, 'Select the planner card'):
            self.start(unselected)
        self.assertFalse(any(r['kind'] == 'focus' for r in self.engine.store.records()))

    def test_membership_change_preserves_unrelated_board_edits_but_not_new_links(self):
        board = self.linked()
        data = copy.deepcopy(board['data'])
        unrelated = copy.deepcopy(fixture()['cards'][0])
        unrelated['id'] = 'unrelated'
        data['cards'].append(unrelated)
        board = self.run_op('planner', 'add-unrelated', data, id=board['id'], expected_revision=2)['record']
        original = copy.deepcopy(board['data']['cards'][0])
        stream = copy.deepcopy(self.stream['record']['data'])
        stream.update(task_ids=[], questions=[])
        self.run_op('workstream', 'move-task', stream, id=self.stream['id'], expected_revision=1)
        data = copy.deepcopy(board['data'])
        data['cards'][1].update(note='Only unrelated choice', selected=True, minutes=90,
                                placement={'date': '2026-11-04', 'start_minute': 900})
        saved = self.run_op('planner', 'unrelated-edit', data, id=board['id'], expected_revision=3)['record']
        self.assertEqual(saved['data']['cards'][0], original)
        self.assertEqual(saved['data']['cards'][1], data['cards'][1])
        self.assertTrue(projection(self.engine.store.records())['cards'][0]['membership_changed'])
        with self.assertRaisesRegex(Invalid, 'workstream'):
            self.start(saved)
        # A new card cannot copy a stale association, nor can explicit relinking bless it.
        invalid = copy.deepcopy(saved['data'])
        invalid['cards'].append(dict(original, id='new-stale-card'))
        with self.assertRaisesRegex(Invalid, 'outside the workstream'):
            self.run_op('planner', 'new-stale', invalid, id=saved['id'], expected_revision=4)
        payload = self.link_payload()
        payload.update(request_id='relink-stale', expected_revision=4)
        with self.assertRaisesRegex(Invalid, 'outside the workstream'):
            self.engine.run('link-planner-cards', payload)
        invalid = copy.deepcopy(saved['data'])
        invalid['cards'][0]['task_revision'] = 2
        with self.assertRaisesRegex(Invalid, 'Relink explicitly'):
            self.run_op('planner', 'rewrite-stale-revision', invalid, id=saved['id'], expected_revision=4)
        self.assertEqual(self.engine.store.get(saved['id'])['revision'], 4)
        # UI recovery can explicitly clear both identities without touching manual choices.
        payload.update(request_id='unlink-stale')
        payload['data']['links'][0].update(task_id=None, task_revision=None, workstream_id=None)
        cleared = self.engine.run('link-planner-cards', payload)['record']
        self.assertEqual({k: v for k, v in cleared['data']['cards'][0].items()
                          if k not in ('link_reason',)},
                         {k: v for k, v in original.items()
                          if k not in ('task_id', 'task_revision', 'workstream_id', 'link_reason')})

    def test_explicit_reassignment_after_membership_change(self):
        board = self.linked()
        old = copy.deepcopy(self.stream['record']['data'])
        old.update(task_ids=[], questions=[])
        self.run_op('workstream', 'remove', old, id=self.stream['id'], expected_revision=1)
        new = copy.deepcopy(self.stream['record']['data'])
        new['title'] = 'New direction'
        stream = self.run_op('workstream', 'new-direction', new)
        payload = self.link_payload()
        payload.update(request_id='reassign', expected_revision=2)
        payload['data']['links'][0]['workstream_id'] = stream['id']
        saved = self.engine.run('link-planner-cards', payload)['record']
        self.assertFalse(projection(self.engine.store.records())['cards'][0]['membership_changed'])
        for key in ('selected', 'placement', 'minutes', 'title', 'outcome', 'first_action'):
            self.assertEqual(saved['data']['cards'][0][key], board['data']['cards'][0][key])
        session = self.run_op('focus', 'new-start', dict(workstream_id=stream['id'], task_id=self.task['id'],
            task_revision=1, planner_id=saved['id'], planner_revision=saved['revision'], planner_card_id='example',
            target='Preserved result', minutes=60))
        self.assertEqual(session['record']['data']['workstream_id'], stream['id'])

    def test_chat_identity_deduplicates_owners_but_keeps_hosts_separate(self):
        board = self.linked()
        second = copy.deepcopy(board['data']['cards'][0]); second['id'] = 'another'
        board['data']['cards'].append(second)
        index = projection([board, self.task['record']])
        self.assertEqual(len(index['cards']), 2)
        self.assertEqual(len(index['chats']), 1)
        self.assertEqual(len(index['chats'][0]['owners']), 2)
        remote = copy.deepcopy(second)
        remote['chat_ref']['host_id'] = 'remote'
        remote.pop('chat_url')
        board['data']['cards'].append(remote)
        self.assertEqual(len(projection([board])['chats']), 2)
        with self.assertRaises(Invalid):
            chat_reference({'chat_url': 'codex://threads/a', 'chat_ref': {'provider': 'codex', 'host_id': 'local', 'thread_id': 'b'}})

    def test_shared_server_planner_save_and_diagnostics(self):
        self.linked()
        server = make_server(self.root, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        endpoint = origin + '/api/board?board=' + self.board['id']
        with urllib.request.urlopen(endpoint) as response:
            boot = json.load(response)
        self.assertEqual(boot['workspace_url'], '/')
        data = boot['record']['data']; data['cards'][0]['note'] = 'UI choice'
        payload = {'request_id': 'ui', 'expected_revision': 2, 'data': data}
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={
            'Origin': origin, 'Content-Type': 'application/json', 'X-Planner-Token': boot['token']})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(json.load(response)['record']['revision'], 3)
        with urllib.request.urlopen(origin + '/api/agent-status') as response:
            self.assertFalse(json.load(response)['live'])
        with urllib.request.urlopen(origin + '/planner?board=' + self.board['id']) as response:
            self.assertIn(b'planner.js', response.read())
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(origin + '/api/board?board=../../personal/config')

    def test_agreed_plan_uses_same_optional_task_identity(self):
        from scenario import Scenario
        with tempfile.TemporaryDirectory() as directory:
            scenario = Scenario(Path(directory))
            task = scenario.call('task', data={'title': 'One example', 'parents': [scenario.outcome],
                'intent': 'proposed', 'status': 'ready', 'priority': 'unranked', 'next_action': 'Draft it',
                'rationale': 'Synthetic only', 'sources': []})
            scenario.plan['actions'][0].update(task_id=task['id'], task_revision=1,
                                              chat_url='codex://threads/fictional-action')
            agreed = scenario.agree()
            index = projection(scenario.engine.store.records())
            action = next(a for a in index['actions'] if a['action_id'] == 'draft')
            self.assertEqual(action['phase'], 'agreed')
            self.assertEqual(action['task_id'], task['id'])
            self.assertEqual(action['chat_ref']['thread_id'], 'fictional-action')
            self.assertEqual(agreed['record']['data']['agreed']['actions'][0]['minutes'], 40)


if __name__ == '__main__':
    unittest.main()
