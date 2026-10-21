"""Bounded immutable official C12 calendar capture; no market-data or order API."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

import requests

from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import USER_AGENT
from tradingbot.forward.c05_readiness import ProbeBudget

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/history/c12-macro-20261001'
INDEXES = {family: f'https://www.bls.gov/bls/news-release/{family}.htm' for family in ('empsit', 'cpi')}
EXAMPLES = {
    'empsit-20061208-pdf': 'https://www.bls.gov/news.release/archives/empsit_12082006.pdf',
    'cpi-20120119-html': 'https://www.bls.gov/news.release/archives/cpi_01192012.htm',
    'fed-advance-2006': 'https://www.federalreserve.gov/boarddocs/press/monetary/2005/20050629/default.htm',
}
FED_IDS = ('20060720b', '20070601b', '20080603b', '20090604a', '20100528b',
           '20110325a', '20120516b', '20130405a', '20140605b', '20150511a',
           '20160628a', '20170511b', '20180525a', '20190517a', '20200702a',
           '20210604a', '20220624a', '20230623a', '20240809a',
           '20060208a', '20081120a', '20090213a')
FED = {'fed-' + iid: f'https://www.federalreserve.gov/newsevents/pressreleases/monetary{iid}.htm'
       for iid in FED_IDS}
FED.update({
    'fed-20050909': 'https://www.federalreserve.gov/boarddocs/press/monetary/2005/20050909/default.htm',
    'fed-20110826-speech': 'https://www.federalreserve.gov/newsevents/speech/bernanke20110826a.htm',
    'fed-20200315-conference': 'https://www.federalreserve.gov/mediacenter/files/FOMCpresconf20200315.pdf',
    'fed-20200315-event': 'https://www.federalreserve.gov/monetarypolicy/fomcpresconf20200315.htm',
})
ALTERNATIVES = {
    'fraser-empsit-index': 'https://fraser.stlouisfed.org/title/employment-situation-144',
    'fraser-cpi-index': 'https://fraser.stlouisfed.org/title/consumer-price-index-6838?browse=2000s',
    'fraser-empsit-metadata': 'https://fraser.stlouisfed.org/metadata.php?type=title&id=144&json=1',
    'fraser-cpi-metadata': 'https://fraser.stlouisfed.org/metadata.php?type=title&id=6838&json=1',
    'omb-policies-index': 'https://statspolicy.gov/policies',
    'omb-resources-index': 'https://statspolicy.gov/resources',
    'omb-2025-publication': 'https://statspolicy.gov/fiscal-year-2024-news/',
    'fraser-revised-2025': 'https://fraser.stlouisfed.org/files/docs/releases/bls/bls_lapse_2025.pdf',
    'omb-calendar-2025': 'https://statspolicy.gov/assets/fcsm/files/docs/OMB_pfei_schedule_of_release_dates_2025.pdf',
    'omb-calendar-2026': 'https://statspolicy.gov/assets/fcsm/files/docs/OMB_pfei_schedule_release_dates_cy2026.pdf',
}
ALTERNATIVES.update({f'fraser-{family}-{decade}':
    f'https://fraser.stlouisfed.org/title/{title}?browse={decade}s'
    for family, title in (('empsit', 'employment-situation-144'), ('cpi', 'consumer-price-index-6838'))
    for decade in (2000, 2010, 2020)})
EXCEPTIONS = {
    'cpi-20120119-pdf': 'https://www.bls.gov/news.release/archives/cpi_01192012.pdf',
    'empsit-20130906-pdf': 'https://www.bls.gov/news.release/archives/empsit_09062013.pdf',
    'cpi-20130917-pdf': 'https://www.bls.gov/news.release/archives/cpi_09172013.pdf',
    'empsit-20250905-pdf': 'https://www.bls.gov/news.release/archives/empsit_09052025.pdf',
    'cpi-20250911-pdf': 'https://www.bls.gov/news.release/archives/cpi_09112025.pdf',
    'empsit-20260109-pdf': 'https://www.bls.gov/news.release/archives/empsit_01092026.pdf',
    'bls-cpi-reschedule-20251010': 'https://www.bls.gov/bls/092025-cpi-reschedule-notice.htm',
    'dol-empsit-cancellation-20131003': 'https://www.dol.gov/newsroom/releases/opa/opa20132030',
    'dol-revision-20131017': 'https://www.dol.gov/newsroom/releases/opa/opa20132044',
    'bls-revised-current': 'https://www.bls.gov/bls/2025-lapse-revised-release-dates.htm',
    'bls-december-2025': 'https://www.bls.gov/schedule/2025/12_sched_list.htm',
    'bls-february-2026': 'https://www.bls.gov/schedule/2026/02_sched_list.htm',
}
EXCEPTIONS.update({f'{family}-{ymd}-pdf':
    f'https://www.bls.gov/news.release/archives/{family}_{mdy}.pdf'
    for family, ymd, mdy in (
        ('cpi', '20131030', '10302013'), ('empsit', '20131022', '10222013'),
        ('empsit', '20240705', '07052024'), ('cpi', '20251024', '10242025'),
        ('empsit', '20251120', '11202025'), ('cpi', '20260113', '01132026'),
        ('empsit', '20260306', '03062026'))})
RELEASE = re.compile(r'/news\.release/archives/(empsit|cpi)_(\d{8})\.(htm|txt|pdf)')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def permitted(url):
    parsed = urlparse(url)
    fixed = set((INDEXES | EXAMPLES | FED | ALTERNATIVES | EXCEPTIONS).values())
    return (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and not parsed.fragment and (not parsed.query or url in fixed) and
            (url in fixed or
             (parsed.netloc == 'www.bls.gov' and RELEASE.fullmatch(parsed.path) is not None)))


def load(folder, url):
    meta = json.loads((folder / 'manifest.json').read_bytes())
    raw = (folder / 'raw').read_bytes()
    if (meta['url'] != url or meta['sha256'] != sha(raw) or meta['bytes'] != len(raw)):
        raise ValueError('C12 capture identity or bytes changed')
    return meta, raw


def capture(key, url, *, budget, archive=ARCHIVE, limit=8_000_000, transport='requests'):
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', key) or key in ('.', '..') or not permitted(url):
        raise ValueError('unregistered C12 key or public URL')
    if transport not in ('requests', 'urllib') or (transport == 'urllib' and
            urlparse(url).netloc not in ('fraser.stlouisfed.org', 'statspolicy.gov')):
        raise ValueError('unexpected public archive transport')
    folder = (archive / key).resolve()
    if not folder.is_relative_to(archive.resolve()) or folder == archive.resolve():
        raise ValueError('capture escaped C12 archive')
    if folder.exists():
        return load(folder, url)
    disk = CaptureDiskBudget(ROOT / 'data')
    disk.check_free(limit * 3 + 65536)
    def fetch():
        if transport == 'urllib':
            # Ordinary public-archive GET, default stdlib headers; no cookies,
            # authentication, challenge handling or proxy changes.
            try:
                response = urlopen(url, timeout=20)
            except HTTPError as error:
                response = error
            with response:
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError('C12 source exceeds bounded response size')
                meta = {'url': url, 'response_url': response.geturl(), 'status': response.status,
                        'retrieved_at': datetime.now(UTC).isoformat(), 'bytes': len(raw),
                        'sha256': sha(raw), 'content_type': response.headers.get('Content-Type'),
                        'transport': transport}
            if meta['response_url'] != url:
                raise ValueError('public archive redirected; review target separately')
            return meta, raw
        with requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=(5, 30),
                          stream=True, allow_redirects=False) as response:
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > limit:
                    raise ValueError('C12 source exceeds bounded response size')
                chunks.append(chunk)
            raw = b''.join(chunks)
            meta = {'url': url, 'response_url': response.url, 'status': response.status_code,
                    'retrieved_at': datetime.now(UTC).isoformat(), 'bytes': len(raw),
                    'sha256': sha(raw), 'content_type': response.headers.get('Content-Type')}
        return meta, raw
    try:
        meta, raw = budget.call(fetch)
    except (requests.RequestException, URLError, TimeoutError) as error:
        raw = b''
        meta = {'url': url, 'response_url': None, 'status': None,
                'retrieved_at': datetime.now(UTC).isoformat(), 'bytes': 0,
                'sha256': sha(raw), 'content_type': None, 'error_type': type(error).__name__}
    if meta['status'] is not None and meta['status'] != 200:
        budget.failure()
    with disk.reserve(3 * len(raw) + 65536):
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'raw').write_bytes(raw)
        (folder / 'manifest.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    return meta, raw


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a' and (href := dict(attrs).get('href')):
            self.urls.append(href)


def release_links(raw, family):
    if family not in INDEXES:
        raise ValueError('unexpected BLS family')
    page = Links()
    page.feed(raw.decode())
    grouped = {}
    for href in page.urls:
        url = urljoin(INDEXES[family], href)
        parsed = urlparse(url)
        match = RELEASE.fullmatch(parsed.path)
        if parsed.netloc != 'www.bls.gov' or match is None or match[1] != family:
            continue
        # These official archive links sometimes use HTTP in older HTML.
        if parsed.scheme == 'http':
            url = 'https:' + url[5:]
        if not permitted(url):
            raise ValueError('unexpected archive link identity')
        day = datetime.strptime(match[2], '%m%d%Y').date()
        if not datetime(2005, 12, 1).date() <= day < datetime(2026, 10, 1).date():
            continue
        grouped.setdefault(day, {})[match[3]] = url
    if not grouped:
        raise ValueError('no bounded release links; index may be an error page')
    out = []
    for day, links in sorted(grouped.items()):
        selected = next(links[k] for k in ('htm', 'txt', 'pdf') if k in links)
        out.append({'family': family, 'release_date_from_url': day.isoformat(),
                    'url': selected, 'alternatives': links})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('indexes', 'examples', 'fed', 'alternatives', 'exceptions', 'releases'))
    parser.add_argument('--family', choices=('empsit', 'cpi'))
    parser.add_argument('--limit', type=int, default=300)
    parser.add_argument('--transport', choices=('requests', 'urllib'), default='requests')
    args = parser.parse_args()
    if not 1 <= args.limit <= 600:
        raise ValueError('bounded capture requires limit 1-600')
    budget = ProbeBudget()
    if args.stage == 'indexes':
        sources = [('index-' + k, v) for k, v in INDEXES.items()]
    elif args.stage in ('examples', 'fed', 'alternatives', 'exceptions'):
        sources = list({'examples': EXAMPLES, 'fed': FED, 'alternatives': ALTERNATIVES,
                        'exceptions': EXCEPTIONS}[args.stage].items())
    else:
        sources = []
        for family in ([args.family] if args.family else INDEXES):
            meta, raw = load(ARCHIVE / ('index-' + family), INDEXES[family])
            if meta['status'] != 200:
                raise ValueError('unsuccessful BLS index cannot select releases')
            for row in release_links(raw, family):
                key = family + '-' + row['release_date_from_url'].replace('-', '')
                sources.append((key, row['url']))
    for key, url in sources[:args.limit]:
        if args.transport != 'requests':
            key += '-' + args.transport
        meta, _ = capture(key, url, budget=budget, transport=args.transport)
        print(json.dumps({'source': key, 'status': meta['status'], 'sha256': meta['sha256'],
                          'bytes': meta['bytes']}), flush=True)


if __name__ == '__main__':
    main()
