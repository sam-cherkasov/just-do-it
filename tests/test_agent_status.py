import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from personal_os.agent_status import normalize, probe, project_status, read_status


class AgentStatusTests(unittest.TestCase):
    def test_signal_semantics(self):
        self.assertEqual(normalize({'type': 'idle'})['execution'], 'idle')
        self.assertEqual(normalize({'type': 'notLoaded'})['execution'], 'unknown')
        self.assertEqual(normalize({'type': 'systemError'})['execution'], 'error')
        self.assertEqual(normalize({'type': 'new-provider-state'})['execution'], 'unknown')
        active = normalize({'type': 'active', 'activeFlags': ['waitingOnApproval', 'waitingOnUserInput']})
        self.assertEqual(active['execution'], 'active')
        self.assertEqual(len(active['attention']), 2)
        self.assertEqual(normalize({'type': 'idle', 'activeFlags': ['waitingOnApproval']})['attention'], [])

    def test_stale_disconnected_and_recovered(self):
        at = datetime.now(timezone.utc)
        receipt = {'state': 'snapshot', 'observed_at': at.isoformat(), 'threads': [normalize({'type': 'active', 'activeFlags': ['waitingOnApproval']})]}
        self.assertEqual(project_status(receipt, at)['threads'][0]['execution'], 'active')
        stale = project_status(receipt, at + timedelta(seconds=31))
        self.assertEqual(stale['state'], 'stale')
        self.assertEqual(stale['threads'][0]['execution'], 'unknown')
        self.assertEqual(stale['threads'][0]['attention'], [])
        receipt['state'] = 'unavailable'
        self.assertEqual(project_status(receipt, at)['threads'][0]['execution'], 'unknown')
        receipt['state'] = 'snapshot'
        self.assertEqual(project_status(receipt, at)['threads'][0]['execution'], 'active')
        self.assertFalse(project_status(receipt, at)['live'])

    def test_missing_corrupt_and_failed_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(read_status(root)['state'], 'unavailable')
            with patch('personal_os.agent_status.subprocess.Popen', side_effect=FileNotFoundError('secret provider details')):
                result = probe(root, [])
            self.assertEqual(result['state'], 'unavailable')
            self.assertNotIn('secret', json.dumps(result))
            (root / '.local/agent-status.json').write_text('invalid')
            self.assertEqual(read_status(root)['state'], 'unavailable')

    def test_probe_reads_only_registered_loaded_chats_and_saves_no_messages(self):
        calls = []
        class FakeProxy:
            def __init__(self, command): pass
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def send(self, method, params, notification=False):
                calls.append((method, params))
                if method == 'thread/loaded/list': return {'data': ['chat-1', 'unrelated'], 'nextCursor': 'more'}
                if method == 'thread/read': return {'thread': {'id': 'chat-1', 'status': {'type': 'active'}, 'preview': 'secret chat text'}}
                return {}
        refs = [{'provider': 'codex', 'host_id': 'local', 'thread_id': value} for value in ('chat-1', 'unloaded')]
        with tempfile.TemporaryDirectory() as directory, patch('personal_os.agent_status.ReadOnlyProxy', FakeProxy):
            result = probe(directory, refs)
        self.assertEqual(result['state'], 'snapshot')
        self.assertEqual(result['threads'][1]['execution'], 'unknown')
        self.assertTrue(result['loaded_list_truncated'])
        self.assertFalse(result['desktop_coverage_verified'])
        self.assertNotIn('secret', json.dumps(result))
        self.assertEqual([c[0] for c in calls], ['initialize', 'initialized', 'thread/loaded/list', 'thread/read'])
        self.assertFalse(calls[-1][1]['includeTurns'])
