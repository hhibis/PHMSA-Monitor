import json
from pathlib import Path
import tempfile
import unittest
from datetime import date
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import monitor as m


def doc(number):
    return {'document_number': number, 'title': 'Special Permits Applications',
            'publication_date': '2026-09-01',
            'html_url': 'https://www.federalregister.gov/documents/' + number}


class Notice:
    def __init__(self, fail=False):
        self.keys = set()
        self.fail = fail

    def ensure(self, key, title, body):
        if self.fail:
            raise RuntimeError('notification failed')
        self.keys.add(key)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state.json'
        self.result = Path(self.temp.name) / 'result.json'
        self.docs = [doc('2026-00001')]
        self.notice = Notice()

    def fetch(self, url):
        return {'count': len(self.docs), 'results': self.docs}

    def run_monitor(self, **kwargs):
        return m.run(self.state, self.result, kwargs.get('notifier', self.notice),
                     kwargs.get('fetch', self.fetch), kwargs.get('today', date(2026, 9, 7)))

    def test_baseline_new_and_repeated(self):
        self.assertEqual(self.run_monitor()['status'], 'BASELINE')
        self.assertEqual(self.notice.keys, set())
        self.docs.append(doc('2026-00002'))
        self.assertEqual(self.run_monitor()['status'], 'ALERT')
        self.assertEqual(self.notice.keys, {'document:2026-00002'})
        self.assertEqual(self.run_monitor()['status'], 'OK')

    def test_api_failure_preserves_exact_bytes(self):
        self.run_monitor()
        original = self.state.read_bytes()
        def broken(url):
            raise RuntimeError('403')
        with self.assertRaises(RuntimeError):
            self.run_monitor(fetch=broken)
        self.assertEqual(self.state.read_bytes(), original)

    def test_notification_failure_preserves_state_and_can_retry(self):
        self.run_monitor()
        original = self.state.read_bytes()
        self.docs.append(doc('2026-00002'))
        with self.assertRaises(RuntimeError):
            self.run_monitor(notifier=Notice(True))
        self.assertEqual(self.state.read_bytes(), original)
        self.assertEqual(self.run_monitor()['status'], 'ALERT')

    def test_corrupt_state_is_not_reset(self):
        self.state.write_text('{bad')
        with self.assertRaises(ValueError):
            self.run_monitor()
        self.assertEqual(self.state.read_text(), '{bad')

    def test_incompatible_config_rejected(self):
        self.run_monitor()
        state = json.loads(self.state.read_text())
        state['config']['rin']['number'] = '1789'
        self.state.write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            self.run_monitor()

    def test_zero_results_valid_baseline(self):
        self.docs = []
        self.assertEqual(self.run_monitor()['status'], 'BASELINE')
        self.assertEqual(json.loads(self.state.read_text())['seen'], [])

    def test_live_api_empty_response_shape(self):
        self.assertEqual(self.run_monitor(fetch=lambda url: {'count': 0})['status'], 'BASELINE')

    def test_missing_notification_does_not_consume_alert(self):
        self.run_monitor()
        original = self.state.read_bytes()
        self.docs.append(doc('2026-00002'))
        with self.assertRaises(ValueError):
            self.run_monitor(notifier=None)
        self.assertEqual(self.state.read_bytes(), original)

    def test_rin_due_once_and_expiration(self):
        self.run_monitor()
        self.assertEqual(self.run_monitor(today=date(2027, 6, 18))['status'], 'ALERT')
        self.assertEqual(self.run_monitor(today=date(2027, 6, 19))['status'], 'OK')
        self.assertEqual(self.run_monitor(today=date(2027, 8, 17))['status'], 'ALERT')
        self.assertEqual(len(self.notice.keys), 2)

    def test_overdue_baseline_defers_reminder_to_second_run(self):
        self.assertEqual(self.run_monitor(today=date(2028, 1, 1))['status'], 'BASELINE')
        self.assertEqual(len(self.notice.keys), 0)
        self.assertEqual(self.run_monitor(today=date(2028, 1, 1))['status'], 'ALERT')

    def test_pagination(self):
        def pages(url):
            page = int(parse_qs(urlparse(url).query)['page'][0])
            return {'count': 2, 'results': [doc(str(page))]}
        records, counts = m.collect(pages)
        self.assertEqual(set(records), {'1', '2'})
        self.assertTrue(all(n == 2 for n in counts.values()))

    def test_partial_response_rejected(self):
        def partial(url):
            return {'count': 2, 'results': []}
        with self.assertRaises(ValueError):
            self.run_monitor(fetch=partial)
        self.assertFalse(self.state.exists())

    def test_closed_issue_marker_prevents_duplicate(self):
        with patch.dict('os.environ', {'GH_TOKEN': 'test', 'GITHUB_REPOSITORY': 'owner/repo'}):
            github = m.GitHub()
        with patch.object(m, 'request', return_value=[{
                'body': '<!-- phmsa-monitor:document:123 -->', 'state': 'closed'}]) as call:
            github.ensure('document:123', 'title', 'body')
            self.assertEqual(call.call_count, 1)


if __name__ == '__main__':
    unittest.main()
