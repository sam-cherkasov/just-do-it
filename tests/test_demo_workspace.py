import tempfile
import unittest
from pathlib import Path

from scripts.demo_workspace import prepare
from personal_os.engine import Engine
from personal_os.workspace import snapshot


class DemoWorkspaceTests(unittest.TestCase):
    def test_demo_is_synthetic_and_separate_from_application(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'demo'
            result = prepare(root, 'America/New_York')
            engine = Engine(root)
            data = snapshot(engine)
            self.assertTrue(data['synthetic'])
            self.assertEqual(data['timezone'], 'America/New_York')
            self.assertEqual(len(data['tasks']), 1)
            self.assertEqual(data['planners'][0]['data']['cards'][0]['task_id'], result['task_id'])
            self.assertEqual(data['sessions'][0]['data']['status'], 'closed')
            self.assertEqual(data['day_choices'], [])
            self.assertEqual(data['relationships']['chats'], [])
            self.assertIsNone(data['auto_refresh'])
            self.assertFalse(any(r['kind'] in ('calendar', 'plan', 'source') for r in engine.store.records()))
            before = (root/'personal/config.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'empty directory'):
                prepare(root)
            self.assertEqual((root/'personal/config.json').read_bytes(), before)

    def test_existing_unrelated_directory_is_not_initialized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'keep.txt').write_text('Original')
            with self.assertRaises(ValueError):
                prepare(root)
            self.assertFalse((root/'personal').exists())
