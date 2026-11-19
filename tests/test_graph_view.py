"""Synthetic offline view integration; no personal records are fixtures."""

import json
import tempfile
import unittest
from pathlib import Path

from personal_os.view import render
from tests.scenario import Scenario


class GraphViewTests(unittest.TestCase):
    def test_offline_renderer_is_embedded_and_original_record_text_cannot_close_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            scenario = Scenario(Path(temporary))
            note = scenario.call('remember', data={
                'title': 'Cyrillic and script boundaries',
                'text': '</script><script>evil()</script> — ґ є і ї €',
                'evidence_kind': 'user_statement', 'scope': 'Synthetic escaping check',
                'event_date': '2026-10-24', 'sources': []
            })
            path = render(scenario.engine)
            html = path.read_text()
            self.assertIn('PersonalOs3D', html)
            self.assertIn('PersonalOsGraph', html)
            self.assertIn('PersonalOsLifeMap', html)
            self.assertNotIn('/* INLINE_GRAPH_', html)
            self.assertIn("connect-src 'none'", html)
            self.assertNotIn('<script src=', html)
            self.assertNotIn('</script><script>evil()', html)
            text = html.split('<script type="application/json" id="snapshot">', 1)[1].split('</script>', 1)[0]
            decoded = json.loads(text)
            saved = next(r for r in decoded['records'] if r['id'] == note['id'])
            self.assertEqual(saved['data']['text'], '</script><script>evil()</script> — ґ є і ї €')


if __name__ == '__main__':
    unittest.main()
