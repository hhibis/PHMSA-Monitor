"""Federal Register early warnings; Python 3.12+, standard library only."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PERMITS = ['5861', '7026', '7945', '8162', '8495', '10867', '10915',
           '10945', '10964', '11194', '12955', '20248']
RIN = {'number': 'I789', 'facility': 'Turkish Technic Inc.',
       'expiration': '2027-08-17', 'renewal_recommended_by': '2027-06-18',
       'tracking_number': '2026084156'}
CONFIG = {'permits': PERMITS, 'rin': RIN}
API = 'https://www.federalregister.gov/api/v1/documents.json'
AGENCY = 'pipeline-and-hazardous-materials-safety-administration'


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def request(url, token=None, payload=None):
    headers = {'User-Agent': 'PHMSA-SP-Monitor/1.0', 'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
        headers['X-GitHub-Api-Version'] = '2022-11-28'
    data = None if payload is None else json.dumps(payload).encode()
    if data:
        headers['Content-Type'] = 'application/json'
    for attempt in range(4):
        try:
            with urlopen(Request(url, data=data, headers=headers), timeout=60) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            # Never retry a possibly successful POST. Next run reconciles its marker.
            if data or attempt == 3:
                raise
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(2 ** attempt)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_state(path):
    if not Path(path).exists():
        return None
    state = json.loads(Path(path).read_text(encoding='utf-8'))
    if (not isinstance(state, dict) or state.get('schema_version') != 1
            or state.get('config') != CONFIG or state.get('baseline_complete') is not True
            or not isinstance(state.get('seen'), list)
            or not all(isinstance(x, str) for x in state['seen'])
            or not isinstance(state.get('reminders'), list)
            or not all(isinstance(x, str) for x in state['reminders'])):
        raise ValueError('Invalid/incompatible state; restore the last valid state. No automatic reset.')
    return state


def collect(fetch=request):
    """Full-history, separately paginated searches catch late indexed old records.

    Search results are deliberately candidates, not proof of permit validity.
    """
    records = {}
    counts = {}
    for term in PERMITS + [RIN['number'], RIN['tracking_number']]:
        page, received, total = 1, 0, None
        unique = set()
        while True:
            params = {'conditions[agencies][]': AGENCY, 'conditions[term]': '"' + term + '"',
                      'per_page': 1000, 'page': page, 'order': 'oldest'}
            result = fetch(API + '?' + urlencode(params))
            # The live API omits results entirely for zero matches.
            if isinstance(result, dict) and result.get('count') == 0 and 'results' not in result:
                result['results'] = []
            if not isinstance(result, dict) or not isinstance(result.get('results'), list):
                raise ValueError('Malformed Federal Register response: ' + str(result)[:500])
            count = result.get('count')
            if type(count) is not int or count < 0 or (total is not None and total != count):
                raise ValueError('Invalid or changing result count; retry next run')
            total = count
            for doc in result['results']:
                number = doc.get('document_number')
                if not isinstance(number, str) or not number or number in unique:
                    raise ValueError('Missing/duplicate document number in pagination')
                unique.add(number)
                for field in ('title', 'publication_date', 'html_url'):
                    if not isinstance(doc.get(field), str) or not doc[field]:
                        raise ValueError('Missing document metadata: ' + field)
                entry = records.setdefault(number, {k: doc[k] for k in
                    ('document_number', 'title', 'publication_date', 'html_url')})
                entry.setdefault('matched_terms', []).append(term)
            received += len(result['results'])
            if received == total:
                break
            if received > total or not result['results'] or page >= 100:
                raise ValueError('Incomplete or excessive pagination')
            page += 1
        counts[term] = total
    return records, counts


class GitHub:
    def __init__(self):
        self.token = os.environ['GH_TOKEN']
        repository = os.environ['GITHUB_REPOSITORY']
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
            raise ValueError('Invalid GITHUB_REPOSITORY')
        self.url = 'https://api.github.com/repos/' + repository + '/issues'
        self.markers = None

    def ensure(self, key, title, body):
        marker = '<!-- phmsa-monitor:' + key + ' -->'
        if self.markers is None:
            self.markers = set()
            page = 1
            while True:
                issues = request(self.url + f'?state=all&per_page=100&page={page}', self.token)
                if not isinstance(issues, list):
                    raise ValueError('Invalid GitHub issue listing')
                for issue in issues:
                    if 'pull_request' not in issue:
                        self.markers.update(re.findall(r'<!-- phmsa-monitor:[^\n]+? -->', issue.get('body') or ''))
                if len(issues) < 100:
                    break
                page += 1
        if marker not in self.markers:
            response = request(self.url, self.token, {'title': title[:240], 'body': marker + '\n\n' + body})
            if not isinstance(response, dict) or not response.get('number'):
                raise ValueError('Issue creation was not confirmed')
            self.markers.add(marker)


def run(state_path, result_path, notifier=None, fetch=request, today=None):
    old = read_state(state_path)
    records, counts = collect(fetch)
    baseline = old is None
    state = copy.deepcopy(old) if old else {
        'schema_version': 1, 'config': CONFIG, 'baseline_complete': True,
        'baseline_at': now(), 'seen': [], 'reminders': []}
    new_ids = sorted(set(records) - set(state['seen']))
    due = []
    today = today or datetime.now(timezone.utc).date()
    for field in ('renewal_recommended_by', 'expiration'):
        key = field + ':' + RIN[field]
        if today >= date.fromisoformat(RIN[field]) and key not in state['reminders']:
            due.append(key)
    if not baseline:
        if (new_ids or due) and notifier is None:
            raise ValueError('Notifications required: run with --notify-github; state unchanged')
        for number in new_ids:
            doc = records[number]
            notifier.ensure('document:' + number,
                '[PHMSA] Federal Register erken uyarı: ' + number,
                f"{doc['title']}\n\nYayın: {doc['publication_date']}\n\n"
                f"Arama eşleşmeleri: {', '.join(doc['matched_terms'])}\n\n"
                f"Kaynak: {doc['html_url']}\n\n"
                'Bu bir arama eşleşmesidir. SP tablosunu ve resmi izin durumunu elle doğrulayın. '
                'Federal Register kaydı izin onayı, yenilemesi veya geçerlilik teyidi değildir.')
        for key in due:
            notifier.ensure('rin:' + key, '[PHMSA] RIN I789: ' + key,
                'Turkish Technic Inc. — RIN I789\n\n'
                'Önerilen yenileme tarihi: 2027-06-18\n\nSon geçerlilik: 2027-08-17\n\n'
                'Tracking: 2026084156\n\nKullanıcının sağladığı tarihlerden üretilen hatırlatma; '
                'canlı PHMSA geçerlilik sorgusu değildir.')
        state['reminders'] = sorted(set(state['reminders']) | set(due))
    state['seen'] = sorted(set(state['seen']) | set(records))
    state['last_success_at'] = now()
    result = {'schema_version': 1, 'status': 'BASELINE' if baseline else
              ('ALERT' if new_ids or due else 'OK'), 'checked_at': now(), 'config': CONFIG,
              'successful_searches': len(counts), 'failed_searches': 0,
              'search_counts': counts, 'matching_documents': list(records.values()),
              'new_document_ids': [] if baseline else new_ids,
              'rin_reminders': [] if baseline else due}
    # Result first; only commit state after all required notifications succeeded.
    atomic_json(result_path, result)
    atomic_json(state_path, state)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', default='state.json')
    parser.add_argument('--result', default='monitor_result.json')
    parser.add_argument('--notify-github', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args.state, args.result, GitHub() if args.notify_github else None)
        print(result['status'])
    except Exception as exc:
        atomic_json(args.result, {'schema_version': 1, 'status': 'ERROR', 'checked_at': now(),
                                 'error': str(exc), 'state_preserved': True})
        print('Monitor failed: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
