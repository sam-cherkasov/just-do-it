import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from scripts.demo_workspace import prepare
from personal_os.planner_server import make_server as planner_server
from personal_os.workspace_server import make_server as workspace_server


class LocalizationHttpTests(unittest.TestCase):
    def test_workspace_and_standalone_planner_serve_language_urls_and_catalog_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'fictional'
            demo = prepare(root)
            def records():
                return {str(p.relative_to(root)): p.read_bytes() for p in (root / 'personal').rglob('*') if p.is_file()}
            before = records()
            for server in (workspace_server(root, 0), planner_server(root, demo['planner_id'], 0)):
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base = 'http://127.0.0.1:' + str(server.server_port)
                    for language in ('uk', 'ru', 'en'):
                        with urllib.request.urlopen(base + '/?lang=' + language) as response:
                            html = response.read().decode()
                            self.assertIn('/i18n.js', html)
                            self.assertIn('data-language-switcher', html)
                    for asset in ('i18n.js', 'i18n-catalog.js'):
                        with urllib.request.urlopen(base + '/' + asset) as response:
                            self.assertIn('text/javascript', response.headers['Content-Type'])
                            self.assertEqual(response.read(), (Path(__file__).resolve().parents[1] / 'web' / asset).read_bytes())
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
            self.assertEqual(before, records())
