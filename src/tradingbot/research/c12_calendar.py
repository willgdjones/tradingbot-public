"""Immutable free C12 calendar evidence and causal announcement reconstruction."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from concurrent.futures import ThreadPoolExecutor
from html import unescape
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.research.c12_sources import public_sources, issue_index

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/research/c12-total-return'
HOSTS = {'www.bls.gov', 'www.dol.gov', 'fraser.stlouisfed.org',
         'www.federalreserve.gov', 'statspolicy.gov', 'www.linkedin.com',
         'www.aila.org', 'www.banking.senate.gov', 'web.archive.org', 'cdn.sanity.io', 'www.ncai.org',
         'www.whitehouse.gov', 'obamawhitehouse.archives.gov', 'georgewbush-whitehouse.archives.gov',
         'www.cbsnews.com', 'www.upi.com', 'wtop.com', 'www.clickorlando.com'}
MONTH = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
WEEKDAY = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
NY = ZoneInfo('America/New_York')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def capture(key, url, *, limit=8_000_000):
    """No authentication, paid API, automatic retries or replaced evidence."""
    p = urlparse(url)
    if (not re.fullmatch(r'[a-zA-Z0-9_.-]+', key) or key in ('.', '..') or
            p.scheme != 'https' or p.netloc not in HOSTS or p.username or p.password or p.fragment):
        raise ValueError('unexpected calendar capture identity')
    folder = ARCHIVE / 'captures' / key
    if folder.exists():
        meta = json.loads((folder / 'manifest.json').read_text())
        raw = (folder / 'raw').read_bytes()
        if meta['url'] != url or meta['sha256'] != sha(raw) or meta['bytes'] != len(raw):
            raise ValueError('immutable calendar evidence changed')
        return meta, raw
    disk = CaptureDiskBudget(ROOT / 'data')
    disk.check_free(limit * 3 + 65536)
    meta = {'url': url, 'retrieved_at': datetime.now(UTC).isoformat()}
    try:
        try:
            response = urlopen(url, timeout=25)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('calendar response exceeds bounded size')
            meta.update(status=response.status, response_url=response.geturl(),
                        content_type=response.headers.get('Content-Type'))
        if meta['response_url'] != url:
            raise ValueError('redirect requires separate source review')
    except (URLError, TimeoutError) as error:
        raw = b''
        meta.update(status=None, response_url=None, error_type=type(error).__name__)
    meta.update(bytes=len(raw), sha256=sha(raw))
    with disk.reserve(3 * len(raw) + 65536):
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'raw').write_bytes(raw)
        (folder / 'manifest.json').write_text(json.dumps(meta, sort_keys=True, indent=2) + '\n')
    return meta, raw


def existing_issues():
    _, bodies = public_sources()
    result = {}
    for family in ('empsit', 'cpi'):
        rows = {}
        for decade in (2000, 2010, 2020):
            for month, url in issue_index(bodies[f'fraser-{family}-{decade}-urllib'], family).items():
                if month in rows and rows[month] != url:
                    raise ValueError('conflicting original issue identity')
                rows[month] = url
        result[family] = rows
    return result


def capture_issue(family, month, url):
    """Archive monthly originals; item metadata is discovery, never the signal."""
    key = f'{family}-{month}'
    meta, raw = capture(key + '-item', url)
    if meta['status'] != 200:
        return {'key': key, 'error': 'item unavailable', 'status': meta['status']}
    links = re.findall(r'<meta\s+name="citation_pdf_url"\s+content="([^"]+)"',
                       raw.decode())
    if len(links) != 1:
        raise ValueError(f'{key}: missing unique archived original PDF')
    pdf_meta, pdf = capture(key + '-pdf', unescape(links[0]))
    return {'key': key, 'status': pdf_meta['status'], 'bytes': len(pdf),
            'ok': pdf_meta['status'] == 200 and pdf.startswith(b'%PDF-')}


def capture_monthly_issues():
    """Four bounded public readers; stop a batch after three failures, no retries."""
    issues = existing_issues()
    tasks = [(f, m, u) for f, rows in issues.items() for m, u in sorted(rows.items())]
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for start in range(0, len(tasks), 4):
            batch = list(pool.map(lambda t: capture_issue(*t), tasks[start:start + 4]))
            results.extend(batch)
            print(json.dumps({'completed': len(results), 'of': len(tasks), 'batch': batch}), flush=True)
            if sum(not r.get('ok') for r in results) >= 3:
                raise ValueError('three source failures; retained evidence requires review')
    return results


def parse_release(text, family, month):
    """Read explicit embargo and forward sentence, never realized values/dates."""
    if family not in ('empsit', 'cpi') or not re.fullmatch(r'\d{4}-\d{2}', month):
        raise ValueError('unknown release identity')
    text = ' '.join(text.split())
    header = text[:900]
    embargo = re.search('embargoed', header, re.I)
    if embargo is None:
        raise ValueError('missing embargo identity')
    header = header[embargo.end():]
    when = re.search(rf'(?:(?P<weekday>{WEEKDAY}),? )?(?P<day>{MONTH} \d{{1,2}}, \d{{4}})', header, re.I)
    zone = re.search(r'8:30\s+[aA]\.[mM]\.\s+\((EST|EDT|ET)\)', header)
    if when is None or zone is None:
        raise ValueError('missing embargo day/time')

    def stamp(day, weekday, zone):
        value = datetime.combine(datetime.strptime(day, '%B %d, %Y').date(), time(8, 30), NY)
        if (weekday and value.strftime('%A').lower() != weekday.lower()
                or zone != 'ET' and value.tzname() != zone):
            raise ValueError('contradictory weekday/timezone')
        return value

    published = stamp(when['day'], when['weekday'], zone[1])
    reference = datetime.strptime(month, '%Y-%m').date()
    if not 0 < (published.date() - reference).days < 100:
        raise ValueError('release/reference identity contradiction')
    name = 'Employment Situation' if family == 'empsit' else 'Consumer Price Index'
    title = re.search(rf'{name}\s*[:—–-]+\s*{reference.strftime("%B %Y")}', text[:1600], re.I)
    if title is None:
        raise ValueError('missing expected release title/reference identity')
    pattern = (rf'(?:The )?{name}(?: data| news release)? for (?P<reference>{MONTH}(?: \d{{4}})?) '
               rf'(?:is|are) scheduled (?:to be released|to be published|for release) on (?P<weekday>{WEEKDAY}), '
               rf'(?P<day>{MONTH} \d{{1,2}})(?:, (?P<year>\d{{4}}))?,? at '
               r'8:30\s+[aA]\.[mM]\.\s+\((?P<zone>EST|EDT|ET)\)\.?')
    matches = list(re.finditer(pattern, text, re.I))
    available = published
    reissued = re.search(rf'reissued on (?:{WEEKDAY}, )?(?P<day>{MONTH} \d{{1,2}}, \d{{4}})', text[:2000], re.I)
    if reissued:
        day = datetime.strptime(reissued['day'], '%B %d, %Y').date()
        if day < published.date():
            raise ValueError('reissue precedes original embargo')
        available = datetime.combine(day + timedelta(days=1), time(), NY)
        # A later agency erratum explicitly attests the original text unchanged.
        # Its date is retained, while the forward sentence keeps its embargo vintage.
        if 'There were no changes made to the text of the release.' in text[:2000]:
            available = published
    result = {'family': family, 'reference_month': month,
              'published_at': published.astimezone(UTC).isoformat(),
              'available_at': available.astimezone(UTC).isoformat(),
              'publication_weekday_explicit': when['weekday'] is not None,
              'reissued_date_only': reissued['day'] if reissued else None,
              'reissue_attests_text_unchanged': bool(reissued and available == published),
              'next_announcement': None}
    if not matches:
        return result
    announcements = []
    for match in matches:
        years = [int(match['year'])] if match['year'] else [published.year, published.year + 1]
        candidates = [datetime.strptime(f'{match["day"]}, {y}', '%B %d, %Y').date() for y in years]
        candidates = [d for d in candidates if 0 < (d - published.date()).days < 100]
        if len(candidates) != 1:
            raise ValueError('next release year is not unique')
        planned = stamp(candidates[0].strftime('%B %d, %Y'), match['weekday'], match['zone'])
        bits = match['reference'].split()
        m = datetime.strptime(bits[0], '%B').month
        y = int(bits[1]) if len(bits) == 2 else planned.year - (m > planned.month)
        next_reference = date(y, m, 1)
        if not reference < next_reference < planned.date():
            raise ValueError('next reference chronology contradicts release')
        announcements.append({'reference_month': next_reference.isoformat()[:7],
            'announced_at': planned.astimezone(UTC).isoformat(), 'announced_date': str(planned.date())})
    if any(a != announcements[0] for a in announcements):
        raise ValueError('ambiguous next release')
    result['next_announcement'] = {**announcements[0], 'sentence': matches[0][0]}
    return result


def parsed_captures():
    """Source-only inventory; unresolved parses stay visible and fail admission."""
    rows, failures = {}, {}
    for path in sorted((ARCHIVE / 'captures').glob('*-pdf/manifest.json')):
        key = path.parent.name
        if not re.fullmatch(r'(empsit|cpi)-\d{4}-\d{2}-pdf', key):
            continue
        meta = json.loads(path.read_text())
        raw = (path.parent / 'raw').read_bytes()
        if meta['sha256'] != sha(raw) or meta['bytes'] != len(raw):
            raise ValueError('PDF integrity changed')
        if meta['status'] != 200 or not raw.startswith(b'%PDF-'):
            if key == 'empsit-2023-07-pdf':
                fallback = path.parent.parent / 'empsit-2023-07-pdf-corrected-path' / 'manifest.json'
                if fallback.exists():
                    path = fallback
                    meta = json.loads(path.read_text())
                    raw = (path.parent / 'raw').read_bytes()
                    if meta['sha256'] != sha(raw) or meta['bytes'] != len(raw):
                        raise ValueError('fallback PDF integrity changed')
            if meta['status'] == 200 and raw.startswith(b'%PDF-'):
                pass
            else:
                failures[key] = 'missing original PDF'
                continue
        text = subprocess.check_output(['pdftotext', '-layout', str(path.parent / 'raw'), '-'],
                                       text=True, timeout=20)
        corrected_reference = key == 'cpi-2007-09-pdf'
        if corrected_reference:
            if meta['sha256'] != '202651263f1c255ccf3dc2f94927ed06d970113cbe1b69848aa92acab4f1a78c':
                raise ValueError('reviewed CPI reference typo source changed')
            schedule = ARCHIVE / 'captures/omb-calendar-2007-assets/raw'
            if sha(schedule.read_bytes()) != 'b72282c2ba8344c76c1408ee8fbe25f749eae29ae1cb099027226a345324f602':
                raise ValueError('independent 2007 reference correction evidence changed')
            # OMB page 4, publicly issued September 12, 2006, explicitly says
            # Nov 15 CPI covers the previous month. Preserve the source typo.
            text = text.replace('Consumer Price Index data for September are scheduled',
                                'Consumer Price Index data for October are scheduled')
        transcribed = key == 'cpi-2018-10-pdf'
        if transcribed:
            if meta['sha256'] != 'b1e7912f5ecc5d70f76d50f25f8e7caaf51c4e68210462c514f6b547416fff60':
                raise ValueError('visually transcribed CPI original changed')
            # Broken embedded font encoding. Visually checked pages 1 and 4;
            # retain the exact printed text, not a guessed recurring date.
            text = ('Transmission of material in this release is embargoed until '
                    '8:30 a.m. (EST) November 14, 2018. CONSUMER PRICE INDEX – OCTOBER 2018. '
                    'The Consumer Price Index for November 2018 is scheduled to be released on '
                    'Wednesday, December 12, 2018, at 8:30 a.m. (EST).')
        family, year, month, _ = key.split('-')
        try:
            rows[key] = {**parse_release(text, family, year + '-' + month),
                         'source_sha256': meta['sha256'], 'url': meta['url'],
                         'visually_transcribed': transcribed,
                         'reference_typo_reconciled_with_omb_2007': corrected_reference}
        except ValueError as error:
            failures[key] = str(error)
    # FRASER's monthly index omits this published issue; the original BLS
    # capture already belongs to the immutable earlier evidence receipt.
    inventory, bodies = public_sources()
    key = 'empsit-20240705-pdf'
    path = ROOT / 'data/history/c12-macro-20261001' / key / 'raw'
    text = subprocess.check_output(['pdftotext', '-layout', str(path), '-'], text=True, timeout=20)
    rows['empsit-2024-06-pdf'] = {**parse_release(text, 'empsit', '2024-06'),
        'source_sha256': inventory[key]['sha256'], 'url': inventory[key]['url'],
        'visually_transcribed': False, 'index_omission_repaired': True}
    return rows, failures


FED_BASELINES = {
    2006: 'fed-advance-2006', 2007: 'fed-20060720b', 2008: 'fed-20070601b',
    2009: 'fed-20080603b', 2010: 'fed-20090604a', 2011: 'fed-20100528b',
    2012: 'fed-20110325a', 2013: 'fed-20120516b', 2014: 'fed-20130405a',
    2015: 'fed-20140605b', 2016: 'fed-20150511a', 2017: 'fed-20160628a',
    2018: 'fed-20170511b', 2019: 'fed-20180525a', 2020: 'fed-20190517a',
    2021: 'fed-20200702a', 2022: 'fed-20210604a', 2023: 'fed-20220624a',
    2024: 'fed-20230623a', 2025: 'fed-20240809a', 2026: 'fed-20240809a',
}


def html_text(raw):
    return ' '.join(unescape(re.sub('<[^>]*>', ' ', raw)).split())


def fed_calendar():
    """Original annual plans plus dated amendments, not actual-date hindsight."""
    inventory, bodies = public_sources()
    events, baseline_dates = [], {}

    def row(key, identity, day, published=None):
        raw = bodies[key].decode()
        if published is None:
            pattern = r'(?:class=[\'\"]article__time[\'\"][^>]*>|Release Date:\s*)([^<]+)'
            hit = re.search(pattern, raw)
            if hit is None:
                raise ValueError('missing Fed publication date')
            published = datetime.strptime(hit[1].strip(), '%B %d, %Y').date()
        available = datetime.combine(published + timedelta(days=1), time(), NY)
        return {'meeting_id': identity, 'announced_date': day,
                'available_at': available.astimezone(UTC).isoformat(),
                'date_only_conservative': True, 'source_key': key,
                'source_sha256': inventory[key]['sha256'], 'url': inventory[key]['url']}

    for year, key in FED_BASELINES.items():
        raw = bodies[key].decode()
        text = html_text(raw)
        if f'schedule for {year}' not in text and f'For {year}:' not in text:
            raise ValueError('annual Fed notice identity missing')
        current_year = year
        dates = []
        paragraphs = re.split(r'</?(?:p|li)\b[^>]*>|<br\b[^>]*>', raw, flags=re.I)
        for block in paragraphs:
            block = html_text(block)
            heading = re.search(r'(?:schedule for|For) (20\d\d):$', block, re.I)
            if heading:
                current_year = int(heading[1])
                continue
            match = re.fullmatch(rf'(?P<month>{MONTH}) (?P<first>\d{{1,2}})'
                rf'(?:\s*-\s*(?:(?P<endmonth>{MONTH}) )?(?P<last>\d{{1,2}}))?'
                rf'(?:, (?P<year>20\d\d))?(?: \((?P<weekdays>{WEEKDAY}(?:-{WEEKDAY})?)\))?\*?', block)
            if match:
                y = int(match['year']) if match['year'] else current_year
                m = match['endmonth'] or match['month']
                d = match['last'] or match['first']
                parsed = datetime.strptime(f'{m} {d}, {y}', '%B %d, %Y').date()
                if match['weekdays'] and parsed.strftime('%A') != match['weekdays'].split('-')[-1]:
                    raise ValueError('Fed date/weekday mismatch')
            else:
                # Modern notices spell out both weekday/month dates.
                modern = re.fullmatch(rf'{WEEKDAY}, {MONTH} \d{{1,2}}, and '
                    rf'(?P<weekday>{WEEKDAY}), (?P<month>{MONTH}) (?P<day>\d{{1,2}})'
                    r'(?:, (?P<year>20\d\d))?', block)
                if not modern:
                    continue
                y = int(modern['year']) if modern['year'] else current_year
                parsed = datetime.strptime(f'{modern["month"]} {modern["day"]}, {y}', '%B %d, %Y').date()
                if parsed.strftime('%A') != modern['weekday']:
                    raise ValueError('modern Fed date/weekday mismatch')
            if parsed.year == year:
                dates.append(str(parsed))
        if len(dates) != 8 or dates != sorted(set(dates)):
            raise ValueError(f'{year}: expected eight original scheduled decisions, got {dates}')
        for number, day in enumerate(dates, 1):
            identity = f'{year}-{number:02}'
            baseline_dates[day] = identity
            events.append(row(key, identity, day))

    revisions = [
        ('fed-20050909', '2006-02-01', '2006-01-31'),
        ('fed-20060720b', '2006-10-24', '2006-10-25'),
        ('fed-20090213a', '2009-03-17', '2009-03-18'),
        ('fed-20090213a', '2009-08-11', '2009-08-12'),
        ('fed-20090213a', '2009-09-22', '2009-09-23'),
        ('fed-20090213a', '2009-12-15', '2009-12-16'),
        ('fed-20110826-speech', '2011-09-20', '2011-09-21'),
        ('fed-20120516b', '2012-07-31', '2012-08-01'),
        ('fed-20120516b', '2012-09-12', '2012-09-13'),
        ('fed-20120516b', '2012-12-11', '2012-12-12'),
    ]
    for key, old, new in revisions:
        events.append({**row(key, baseline_dates[old], new), 'replaces': old})
    # March 15 emergency action replaced the March 17-18 scheduled meeting.
    # Its announcement is too late to retroactively exclude a prior BLS window.
    transcript = subprocess.check_output(['pdftotext', '-layout',
        str(ROOT / 'data/history/c12-macro-20261001/fed-20200315-conference/raw'), '-'], text=True)
    normalized = ' '.join(transcript.split())
    if ('March 15, 2020' not in normalized or
            'in lieu of the meeting scheduled for next Tuesday and Wednesday.' not in normalized):
        raise ValueError('March 2020 replacement evidence changed')
    events.append({**row('fed-20200315-event', baseline_dates['2020-03-18'], None,
                        date(2020, 3, 15)), 'replaces': '2020-03-18',
                   'note': 'emergency Sunday decision; not an advance scheduled exclusion'})
    return {'announcements': sorted(events, key=lambda e:(e['available_at'], e['meeting_id'])),
            'baseline_decisions': len(baseline_dates), 'reviewed_unchanged_decision_dates': [
                {'source_key': 'fed-20060208a', 'decision': '2006-03-28'},
                {'source_key': 'fed-20081120a', 'decision': '2008-12-16'}],
            'emergency_actions_not_retrospective_exclusions': True}


def read_capture(key):
    path = ARCHIVE / 'captures' / key
    meta = json.loads((path / 'manifest.json').read_text())
    raw = (path / 'raw').read_bytes()
    if meta['status'] != 200 or meta['sha256'] != sha(raw) or meta['bytes'] != len(raw):
        raise ValueError('calendar evidence failed or changed: ' + key)
    return meta, raw


def date_available(day):
    return datetime.combine(date.fromisoformat(day) + timedelta(days=1), time(), NY).astimezone(UTC).isoformat()


def source_file(relative, expected, needles=()):
    raw = (ROOT / relative).read_bytes()
    if sha(raw) != expected or any(needle not in raw.decode() for needle in needles):
        raise ValueError('reviewed browser/source text changed: ' + relative)
    return {'source_path': relative, 'source_sha256': expected}


def annual_announcements():
    """Visually checked original OMB rows; all are dates for the prior month."""
    old, _ = public_sources()
    index, index_raw = read_capture('omb-prior-schedules-index')
    specifications = [
        (2006, 'omb-calendar-2006-assets', '2005-09-14', 'September 14, 2005',
         [6,3,10,7,5,2,7,4,1,6,3,8], [18,22,16,19,17,14,19,16,15,18,16,15]),
        (2007, 'omb-calendar-2007-assets', '2006-09-12', 'September 12, 2006',
         [5,2,9,6,4,1,6,3,7,5,2,7], [18,21,16,17,15,15,18,15,19,17,15,14]),
        (2013, 'omb-calendar-2013', '2012-09-28', 'September 28, 2012',
         [4,1,8,5,3,7,5,2,6,4,1,6], [16,21,15,16,16,18,16,15,17,16,15,17]),
        (2025, 'omb-calendar-2025', '2024-09-27', None,
         [10,7,7,4,2,6,3,1,5,3,7,5], [15,12,12,10,13,11,15,12,11,15,13,10]),
        (2026, 'omb-calendar-2026-urllib', '2025-09-26', None,
         [9,6,6,3,8,5,2,7,4,2,6,4], [13,11,11,10,12,10,14,12,11,14,10,10]),
    ]
    result = []
    for year, key, published, printed, employment, cpi in specifications:
        if year < 2025:
            meta, raw = read_capture(key)
            if printed not in html_text(index_raw.decode()):
                raise ValueError('OMB first-publication record changed')
            path = ARCHIVE / 'captures' / key / 'raw'
            publication = index['sha256']
        else:
            meta = old[key]
            path = ROOT / 'data/history/c12-macro-20261001' / key / 'raw'
            publication = old['omb-2025-publication-urllib' if year == 2025 else 'omb-resources-index-urllib']['sha256']
        text = ' '.join(subprocess.check_output(['pdftotext', '-layout', str(path), '-'], text=True).split())
        for family, values in [('empsit', employment), ('cpi', cpi)]:
            if ' '.join(map(str, values)) not in text:
                raise ValueError('visually reviewed OMB date row changed')
            for month, day in enumerate(values, 1):
                planned = date(year, month, day)
                reference = (date(year, month, 1) - timedelta(days=1)).isoformat()[:7]
                if not '2005-12' <= reference <= '2026-08':
                    continue
                result.append({'family': family, 'reference_month': reference,
                    'announced_date': str(planned), 'available_at': date_available(published),
                    'source_key': key, 'source_sha256': meta['sha256'], 'url': meta['url'],
                    'availability_evidence_sha256': publication, 'kind': 'original_annual_schedule'})
    return result


def exceptional_announcements():
    """Dates transcribed from archived official notices and first-hand records.

    Browser extractions are identified as such; failed direct HTTP responses
    are never treated as notice content. No actual release date is substituted.
    """
    old = 'data/history/c12-macro-20261001/'
    new = 'data/research/c12-total-return/'
    notices, suspensions = [], []

    def add(family, reference, target, available, provenance, **extra):
        notices.append({'family': family, 'reference_month': reference,
            'announced_date': target, 'available_at': available, 'kind': 'official_notice',
            **provenance, **extra})

    # Date-only withdrawal and replacement notices. Store the failed raw HTTP
    # capture separately from the successful public browser extraction.
    cpi_2013 = source_file(new+'2013-cpi-suspension-web.txt',
        '0d4786f6398be1765c79e4d200a09a5fcca56f406fc6506945f38cb485124f7f',
        ('October 3, 2013', 'will not be released on Oct. 16.'))
    add('cpi', '2013-09', None, date_available('2013-10-03'), cpi_2013,
        url='https://www.dol.gov/newsroom/releases/opa/opa20132033')
    replacement = source_file(new+'2013-replacement-web.txt',
        '6b1109d3dcfaf8e98133f750bb7bcfd7ea983380d1552020e5c928d84bed4680',
        ('October 17, 2013', '8:30 a.m. on Oct. 22.', '8:30 a.m. on Oct. 30.', 'issued on Nov. 8.'))
    for family, reference, target in [('empsit','2013-09','2013-10-22'),
            ('empsit','2013-10','2013-11-08'), ('cpi','2013-09','2013-10-30')]:
        add(family, reference, target, date_available('2013-10-17'), replacement,
            url='https://www.dol.gov/newsroom/releases/opa/opa20132044')
    old_notice = source_file(old+'web-exception-discovery.txt',
        'ae4e53589e69f60e63a772308c9eaf484fdeae0f0c6e76fbe9337ede9ae3a091',
        ('October 3, 2013', 'Friday, October 4, 2013', 'October 10, 2025', 'Friday, October 24, 2025'))
    add('empsit','2013-09',None,date_available('2013-10-03'),old_notice,
        url='https://www.dol.gov/newsroom/releases/opa/opa20132030')
    add('cpi','2025-09','2025-10-24',date_available('2025-10-10'),old_notice,
        url='https://www.bls.gov/bls/092025-cpi-reschedule-notice.htm')

    # Issuer-authored September 2025 Employment notice is marked edited. An
    # independent AP dispatch confirms its relevant target on Nov 14, so use
    # the later AP publication, not the social post's creation clock.
    ap, ap_raw = read_capture('bls-20251114-statement-ap-orlando')
    if not all(s in ap_raw.decode() for s in ('2025-11-14T22:15:55Z',
            'September hiring and unemployment next Thursday', 'Associated Press')):
        raise ValueError('AP contemporaneous availability confirmation changed')
    for key, expected_day, family, reference, target in [
        ('bls-official-september-employment-notice','2025-11-14','empsit','2025-09','2025-11-20'),
        ('bls-official-cpi-november-notice','2025-11-21','cpi','2025-11','2025-12-18')]:
        meta, raw = read_capture(key)
        scripts = [json.loads(s) for s in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', raw.decode(), re.S)]
        posts = [s for s in scripts if s.get('@type') == 'SocialMediaPosting' and s.get('@id') == meta['url']]
        if len(posts) != 1 or posts[0]['author']['url'] != 'https://www.linkedin.com/company/bureau-of-labor-statistics':
            raise ValueError('official social notice identity changed')
        post = posts[0]
        if not post['datePublished'].startswith(expected_day):
            raise ValueError('official social publication date changed')
        label = datetime.strptime(target, '%Y-%m-%d').strftime('%B %d, %Y')
        if label not in post['articleBody'] or reference[:4] not in post['articleBody']:
            raise ValueError('official notice target changed')
        proof = {'source_key': key, 'source_sha256': meta['sha256'], 'url': meta['url']}
        available = post['datePublished']
        if family == 'empsit':
            available = '2025-11-14T22:15:55+00:00'
            proof.update(edited_notice=True, availability_evidence_sha256=ap['sha256'],
                         availability_evidence_url=ap['url'])
        add(family, reference, target, available, proof)
        if family == 'cpi':
            if 'Survey data for October 2025 cannot be collected retroactively and will not be published.' not in post['articleBody']:
                raise ValueError('October CPI cancellation text changed')
            add('cpi','2025-10',None,available,proof)

    # The November 20 original release explicitly cancels the missing October
    # Employment issue, independently of the earlier active suspension.
    meta, raw = read_capture('empsit-2025-09-pdf')
    txt = ' '.join(subprocess.check_output(['pdftotext','-layout',str(ARCHIVE/'captures/empsit-2025-09-pdf/raw'),'-'],text=True).split())
    if 'BLS will not publish an October 2025 Employment Situation news release.' not in txt:
        raise ValueError('October Employment cancellation changed')
    add('empsit','2025-10',None,'2025-11-20T13:30:00+00:00',
        {'source_key':'empsit-2025-09-pdf','source_sha256':meta['sha256'],'url':meta['url']})

    # BLS spokeswoman's email is a first-hand quotation. The email itself is
    # unavailable; use the latest dated publisher revision conservatively.
    meta, raw = read_capture('bls-20260202-statement-cbs')
    if not all(s in raw.decode() for s in ('2026-02-02T14:09:11-0500',
            'will not be released as scheduled on Friday, February 6, 2026.',
            'told CBS News in an email')):
        raise ValueError('first-hand BLS cancellation record changed')
    add('empsit','2026-01',None,date_available('2026-02-02'),
        {'source_key':'bls-20260202-statement-cbs','source_sha256':meta['sha256'],'url':meta['url']},
        original_email_unavailable=True, clock_basis='day after publisher last modification')
    feb = source_file(old+'web-late-calendar-excerpt.txt',
        '3ad7872f787bd8c6c45da5c2026df0020b77a80e11614364b8aa1ebab2946c3f',
        ('Last Modified Date: February 04, 2026',
         'Wednesday, February 11, 2026 08:30 AM Employment Situation for January 2026',
         'Friday, February 13, 2026 08:30 AM Consumer Price Index for January 2026'))
    for family, target in [('empsit','2026-02-11'),('cpi','2026-02-13')]:
        add(family,'2026-01',target,date_available('2026-02-04'),feb,
            url='https://www.bls.gov/schedule/2026/02_sched_list.htm')

    # Activated agency-wide suspension is a state, not a prediction about the
    # future shutdown end. A later explicit target reinstates that identity.
    for year, plan_key, plan_digest, directive_digest in [
        (2013,'dol-2013-aila-mirror-canonical','0f2f4a8603f837a9a34f5a518cc1416595ebed1615c565c0406d5706b33f8725',
         'ce8d80804ee28985bcef78d19d2d57771c078e6643f7ecdef9c19236c013eeb0'),
        (2025,'dol-20250926-ncai-mirror','95972b83cedcff9b6f9aea131f6bb10cc0f6788a266b474448478a18cb42b4ae',
         'cde65f82110bb8455cbe7f8212ce713328964e340b2dc82f856e2d19c1cc1f8f')]:
        plan, _ = read_capture(plan_key)
        directive, _ = read_capture(f'omb-start-{year}')
        if plan['sha256'] != plan_digest or directive['sha256'] != directive_digest:
            raise ValueError('reviewed suspension/directive changed')
        confirmation_key = 'bls-20130930-statement-ap-cbs' if year == 2013 else 'senate-20251002-letter'
        confirmation, _ = read_capture(confirmation_key)
        suspensions.append({'available_at':date_available(f'{year}-09-30'),
            'source_key':plan_key,'source_sha256':plan_digest,'url':plan['url'],
            'activation_sha256':directive_digest,'activation_url':directive['url'],
            'plan_publication_confirmation_sha256':confirmation['sha256'],
            'plan_publication_confirmation_url':confirmation['url'],
            'review':'Signed agency plan, independently dated prior public availability; OMB activation. No assumed shutdown end.'})
    return notices, suspensions


def reconcile_calendar(rows, failures):
    """Fail on missing identities or unreconciled dates before price outcomes."""
    if failures:
        raise ValueError('unresolved monthly release parses: ' + repr(failures))
    expected = {(f, f'{y:04}-{m:02}') for f in ('empsit','cpi')
        for y in range(2005,2027) for m in range(1,13)
        if '2005-12' <= f'{y:04}-{m:02}' <= '2026-08'}
    canceled = {(f,'2025-10') for f in ('empsit','cpi')}
    observed = {(r['family'],r['reference_month']) for r in rows.values()}
    if observed != expected-canceled or len(rows) != len(observed):
        raise ValueError('published/canceled monthly denominator incomplete')
    announcements = annual_announcements()
    for key, row in rows.items():
        n = row['next_announcement']
        if n is not None and (row['family'],n['reference_month']) in expected:
            announcements.append({**n,'family':row['family'],'available_at':row['available_at'],
                'source_key':key,'source_sha256':row['source_sha256'],'url':row['url'],
                'kind':'prior_release_forward_sentence'})
    special, suspensions = exceptional_announcements()
    announcements.extend(special)
    for family, reference in expected:
        chain = [a for a in announcements if (a['family'],a['reference_month']) == (family,reference)]
        if not chain or not any(a['announced_date'] for a in chain):
            raise ValueError('missing original event denominator')
        latest = max(chain,key=lambda a:datetime.fromisoformat(a['available_at']))
        actual = next((r for r in rows.values() if (r['family'],r['reference_month']) == (family,reference)),None)
        if actual is None:
            if latest['announced_date'] is not None:
                raise ValueError('canceled monthly issue lacks official notice')
        elif (latest['announced_date'] != datetime.fromisoformat(actual['published_at']).astimezone(NY).date().isoformat()
              or datetime.fromisoformat(latest['available_at']) >= datetime.fromisoformat(actual['published_at'])):
            raise ValueError('announced/occurred date not independently reconciled: '+family+':'+reference)
    return {'announcements': sorted(announcements,key=lambda a:(a['available_at'],a['family'],a['reference_month'])),
        'suspensions':suspensions,'published_releases':rows,'canceled_identities':[list(x) for x in sorted(canceled)],
        'expected_monthly_identities':len(expected),'published_monthly_issues':len(rows),
        'fed':fed_calendar(),'reconciliation':'All published/canceled identities and final announced dates reconcile; occurrence dates never enter windows.'}


def causal_windows(calendar, sessions):
    """Freeze each candidate using only notices available at its decision close."""
    days = [r['date'] for r in sessions]
    if days != sorted(set(days)):
        raise ValueError('regular sessions must be unique and ordered')
    indices = {day:i for i,day in enumerate(days)}
    grouped = {}
    for a in calendar['announcements']:
        stamp = datetime.fromisoformat(a['available_at'])
        if stamp.tzinfo is None:
            raise ValueError('announcement timestamp must be timezone-aware')
        grouped.setdefault((a['family'],a['reference_month']),[]).append(a)
    result, skips = [], []
    for (family, reference), chain in sorted(grouped.items()):
        identity = family+':'+reference
        candidates = sorted({a['announced_date'] for a in chain if a['announced_date']})
        for day in candidates:
            key = identity+'@'+day
            if day not in indices:
                skips.append({'id':key,'identity':identity,'reason':'announced date is not an in-source equity session'})
                continue
            i = indices[day]
            if i < 2 or i+1 >= len(days):
                skips.append({'id':key,'identity':identity,'reason':'incomplete source window'})
                continue
            decision = datetime.fromisoformat(sessions[i-2]['closes_at'])
            known = [a for a in chain if datetime.fromisoformat(a['available_at']) <= decision]
            if not known:
                skips.append({'id':key,'identity':identity,'reason':'no announcement by decision'})
                continue
            stamp = max(datetime.fromisoformat(a['available_at']) for a in known)
            latest = [a for a in known if datetime.fromisoformat(a['available_at']) == stamp]
            if len({a['announced_date'] for a in latest}) != 1:
                raise ValueError('simultaneous contradictory official announcements')
            notice = latest[0]
            suspended = [s for s in calendar['suspensions']
                if stamp < datetime.fromisoformat(s['available_at']) <= decision]
            if notice['announced_date'] != day or suspended:
                skips.append({'id':key,'identity':identity,
                    'reason':'active agency suspension' if suspended else 'predecision cancellation or replacement',
                    'latest_notice':notice,'suspensions':suspended})
                continue
            result.append({'id':key,'identity':identity,'family':family,'reference_month':reference,
                'announced_date':day,'announcement_at':notice['available_at'],
                'announcement_source_sha256':notice['source_sha256'],
                'decision':days[i-2],'entry':days[i-1],'exit':days[i+1],'exit_phase':'open',
                'entry_index':i-1,'exit_index':i+1,'diagnostic_shifted':False})
    return sorted(result,key=lambda w:(w['decision'],w['identity'],w['announced_date'])), skips


def fed_conflicts(calendar, sessions, window):
    days = [r['date'] for r in sessions]
    indices = {day:i for i,day in enumerate(days)}
    decision = datetime.fromisoformat(sessions[indices[window['decision']]]['closes_at'])
    known = {}
    for a in sorted(calendar['fed']['announcements'],key=lambda a:datetime.fromisoformat(a['available_at'])):
        if datetime.fromisoformat(a['available_at']) <= decision:
            known[a['meeting_id']] = a
    covered = {key[:4] for key in known}
    if {window['entry'][:4],window['exit'][:4]}-covered:
        raise ValueError('advance Fed annual calendar provenance unavailable')
    blocked = []
    for key, a in known.items():
        day = a['announced_date']
        if day not in indices:
            continue
        i = indices[day]
        if any(window['entry_index'] <= j < window['exit_index'] for j in (i-1,i)):
            blocked.append({'meeting_id':key,'decision_date':day,'notice':a})
    return blocked


def windows(calendar, sessions, family, *, control=False):
    if family not in ('empsit','cpi'):
        raise ValueError('unknown C12 variant')
    raw, skips = causal_windows(calendar,sessions)
    days = [r['date'] for r in sessions]
    indices = {day:i for i,day in enumerate(days)}
    result = []
    for original in raw:
        if original['family'] != family:
            continue
        w = dict(original)
        if control:
            start = str(date.fromisoformat(w['entry'])-timedelta(days=7))
            end = str(date.fromisoformat(w['exit'])-timedelta(days=7))
            if (start not in indices or end not in indices or indices[start] == 0
                    or indices[end]-indices[start] != w['exit_index']-w['entry_index']):
                skips.append({'id':w['id'],'identity':w['identity'],'reason':'shifted endpoints/duration unavailable'})
                continue
            w.update(decision=days[indices[start]-1],entry=start,exit=end,
                     entry_index=indices[start],exit_index=indices[end],diagnostic_shifted=True)
            if datetime.fromisoformat(w['announcement_at']) > datetime.fromisoformat(sessions[indices[start]-1]['closes_at']):
                skips.append({'id':w['id'],'identity':w['identity'],'reason':'announcement after control decision'})
                continue
            overlaps = [other['id'] for other in raw if max(w['entry_index'],other['entry_index']) < min(w['exit_index'],other['exit_index'])]
            if overlaps:
                skips.append({'id':w['id'],'identity':w['identity'],'reason':'control intersects BLS window','intersections':overlaps})
                continue
        blocked = fed_conflicts(calendar,sessions,w)
        if blocked:
            skips.append({'id':w['id'],'identity':w['identity'],'reason':'scheduled FOMC or preceding session','conflicts':blocked})
            continue
        result.append(w)
    return result, [s for s in skips if s['identity'].startswith(family+':')]
