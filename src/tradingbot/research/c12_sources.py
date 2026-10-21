"""C12 source-only calendar checks; no price arithmetic or strategy replay."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
import json
import re
import subprocess
from zoneinfo import ZoneInfo

from tradingbot.research.c06_sources import spy_source
from tradingbot.research.c12_capture import ROOT, ARCHIVE, load, permitted, sha

NY = ZoneInfo('America/New_York')
FAMILIES = {'empsit': 'Employment Situation', 'cpi': 'Consumer Price Index'}
TITLES = {'empsit': 'employment-situation-144', 'cpi': 'consumer-price-index-6838'}
MONTH = r'(January|February|March|April|May|June|July|August|September|October|November|December)'
WEEKDAY = r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
DATE = MONTH + r' \d{1,2}, \d{4}'
NEXT = re.compile(r'The (?P<family>Employment Situation|Consumer Price Index) for '
    r'(?P<reference>' + MONTH + r'(?: \d{4})?) is scheduled to be released on '
    r'(?P<weekday>' + WEEKDAY + r'), (?P<day>' + DATE + r'), at '
    r'8:30 [aA]\.[mM]\. \((?P<zone>EST|EDT|ET)\)\.')
REVIEWED_NEXT = {
    'empsit-20061208-pdf': '2007-01-05', 'cpi-20120119-pdf': '2012-02-17',
    'empsit-20130906-pdf': '2013-10-04', 'cpi-20130917-pdf': '2013-10-16',
    'empsit-20131022-pdf': '2013-11-08', 'cpi-20131030-pdf': '2013-11-20',
    'empsit-20240705-pdf': '2024-08-02', 'empsit-20250905-pdf': '2025-10-03',
    'cpi-20250911-pdf': '2025-10-15', 'cpi-20251024-pdf': None,
    'empsit-20251120-pdf': '2025-12-16', 'empsit-20260109-pdf': '2026-02-06',
    'cpi-20260113-pdf': '2026-02-11', 'empsit-20260306-pdf': '2026-04-03',
}


def public_sources(root=ROOT, archive=ARCHIVE):
    inventory = json.loads((root / 'docs/research/32-c12-evidence.json').read_bytes())['sources']
    bodies = {}
    for key, expected in inventory.items():
        folder = archive / key
        if not permitted(expected['url']):
            raise ValueError('unregistered C12 source')
        meta, raw = load(folder, expected['url'])
        if ({k: v for k, v in expected.items() if k not in ('path', 'manifest_sha256')} != meta
                or expected['path'] != str(folder.relative_to(root))
                or expected['manifest_sha256'] != sha((folder / 'manifest.json').read_bytes())):
            raise ValueError('C12 pinned capture changed')
        bodies[key] = raw
    return inventory, bodies


def issue_index(raw, family):
    """Document discovery only. An issue's existence is not advance knowledge."""
    title = 'https://fraser.stlouisfed.org/title/' + TITLES[family]
    scripts = re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
                         raw.decode(), re.S)
    works = [json.loads(s) for s in scripts]
    works = [w for w in works if w.get('url') == title
             and w.get('@type') in ('CreativeWork', 'Periodical')]
    if len(works) != 1 or not works[0].get('hasPart'):
        raise ValueError('missing or ambiguous FRASER issue inventory')
    rows = {}
    for row in works[0]['hasPart']:
        if row['name'] in (
                'Announcement: Revised news release dates following the 2025 lapse in appropriations',
                'Notice: Revised news release dates following the 2025 lapse in appropriations',
                'Notice: 2025 federal government shutdown impact on the Consumer Price Index'):
            continue  # Separately captured notice; never an observed monthly issue.
        name = row['name'].removeprefix('Consumer Price Index - ')
        match = re.match(MONTH + r' \d{4}(?=$|,| :| Consumer Price Index)', name)
        if match is None:
            raise ValueError('unknown issue title format')
        day = datetime.strptime(match[0], '%B %Y').date()
        if (not row['url'].startswith(title + '/')
                or row.get('@type') not in ('CreativeWork', 'Periodical')):
            raise ValueError('wrong family or type in issue inventory')
        if not date(2005, 12, 1) <= day < date(2026, 9, 1):
            continue
        key = day.isoformat()[:7]
        if key in rows and rows[key] != row['url']:
            raise ValueError('conflicting issue identity')
        rows[key] = row['url']
    return rows


def stamp(day, weekday, zone):
    day = datetime.strptime(day, '%B %d, %Y').date()
    result = datetime.combine(day, time(8, 30), NY)
    if day.strftime('%A') != weekday or (zone != 'ET' and result.tzname() != zone):
        raise ValueError('release weekday or daylight-saving timezone contradiction')
    return result


def release_metadata(text, family, expected_publication):
    """Only embargo identity and explicit next-release sentence are extracted."""
    normalized = ' '.join(text.split())
    header = normalized[:600]
    when = re.search(r'(?P<weekday>' + WEEKDAY + r'), (?P<day>' + DATE + r')', header)
    zone = re.search(r'8:30 [aA]\.[mM]\. \((EST|EDT|ET)\)', header)
    if 'embargoed until' not in header or when is None or zone is None:
        raise ValueError('dated BLS embargo identity missing')
    publication = stamp(when['day'], when['weekday'], zone[1])
    if publication.date() != expected_publication:
        raise ValueError('BLS publication identity disagrees with archived URL')
    matches = list(NEXT.finditer(normalized))
    if len(matches) > 1 or (matches and matches[0]['family'] != FAMILIES[family]):
        raise ValueError('ambiguous or wrong-family next release')
    result = {'family': family, 'published_at': publication.astimezone(UTC).isoformat(),
              'next_announcement': None}
    if not matches:
        return result
    match = matches[0]
    planned = stamp(match['day'], match['weekday'], match['zone'])
    reference = match['reference'].split()
    month = datetime.strptime(reference[0], '%B').month
    year = int(reference[1]) if len(reference) == 2 else planned.year - (month > planned.month)
    if planned <= publication or date(year, month, 1) >= planned.date():
        raise ValueError('next release does not follow source or reference month')
    result['next_announcement'] = {
        'reference_month': f'{year:04}-{month:02}', 'announced_at': planned.astimezone(UTC).isoformat(),
        'announced_date': str(planned.date()), 'sentence': match[0],
    }
    return result


def decision_example(announced_date, sessions):
    """Calendar diagnostic only, using frozen regular sessions. Never rolls D."""
    days = [r['date'] for r in sessions]
    if days != sorted(set(days)):
        raise ValueError('regular session inventory is not unique and ordered')
    if announced_date not in days:
        return {'announced_date': announced_date, 'equity_session': False,
                'decision_at': None, 'entry_at': None, 'exit_at': None}
    i = days.index(announced_date)
    if i < 2 or i + 1 >= len(days):
        raise ValueError('announcement window outside session inventory')
    return {'announced_date': announced_date, 'equity_session': True,
            'decision_at': sessions[i - 2]['closes_at'],
            'entry_at': sessions[i - 1]['opens_at'], 'exit_at': sessions[i + 1]['opens_at']}


def date_only_available_before(day, decision_at):
    """A date-only notice cannot be assumed available before that day's close."""
    boundary = datetime.combine(day + timedelta(days=1), time(), NY)
    decision = datetime.fromisoformat(decision_at)
    if decision.tzinfo is None:
        raise ValueError('decision must be timezone-aware')
    return boundary <= decision


def pdf_text(key, archive=ARCHIVE):
    raw = (archive / key / 'raw').read_bytes()
    if not raw.startswith(b'%PDF-'):
        raise ValueError('source is not PDF')
    return subprocess.check_output(['pdftotext', '-layout', str(archive / key / 'raw'), '-'],
                                   text=True, timeout=20)


def audit_sources(root=ROOT, archive=ARCHIVE):
    inventory, bodies = public_sources(root, archive)
    indices = {}
    expected = {f'{y:04}-{m:02}' for y in range(2005, 2027) for m in range(1, 13)
                if date(2005, 12, 1) <= date(y, m, 1) < date(2026, 9, 1)}
    for family in FAMILIES:
        issues = {}
        for decade in (2000, 2010, 2020):
            for key, url in issue_index(bodies[f'fraser-{family}-{decade}-urllib'], family).items():
                if key in issues and issues[key] != url:
                    raise ValueError('FRASER decade inventories disagree')
                issues[key] = url
        indices[family] = {'expected_reference_months': len(expected), 'issues_found': len(issues),
            'missing_reference_months': sorted(expected - issues.keys()),
            'issues': dict(sorted(issues.items())), 'advance_availability_proven': False}
    if (indices['empsit']['missing_reference_months'] != ['2024-06', '2025-10']
            or indices['cpi']['missing_reference_months'] != ['2025-10']):
        raise ValueError('reviewed FRASER coverage changed')
    releases = {}
    for key, expected_day in REVIEWED_NEXT.items():
        if inventory[key]['status'] != 200:
            raise ValueError('failed response cannot establish a BLS announcement')
        family, day, _ = key.split('-')
        row = release_metadata(pdf_text(key, archive), family, datetime.strptime(day, '%Y%m%d').date())
        next_day = row['next_announcement']['announced_date'] if row['next_announcement'] else None
        if next_day != expected_day:
            raise ValueError('reviewed next announcement changed')
        releases[key] = {**row, 'source_sha256': inventory[key]['sha256']}
    revised = ' '.join(pdf_text('fraser-revised-2025-urllib', archive).split())
    if 'Last modified date: January 23, 2026' not in revised:
        raise ValueError('retrospective calendar vintage changed')
    for key, day in [('omb-2025-publication-urllib', 'September 27, 2024'),
                     ('omb-resources-index-urllib', 'September 26, 2025')]:
        if day not in bodies[key].decode():
            raise ValueError('OMB publication-date evidence changed')
    receipt, spy = spy_source(root)
    examples = {d: decision_example(d, spy['prices']) for d in (
        '2013-10-04', '2013-10-16', '2025-10-03', '2025-10-15', '2025-10-24',
        '2025-11-07', '2025-11-13', '2025-12-10', '2026-02-06', '2026-02-11', '2026-04-03')}
    return {'public_sources': inventory, 'issue_indices': indices, 'sampled_prior_releases': releases,
        'calendar_examples': examples,
        'revision_chronology_admitted': False,
        'original_omb_dates': {
            '2025': {'empsit': [10, 7, 7, 4, 2, 6, 3, 1, 5, 3, 7, 5],
                     'cpi': [15, 12, 12, 10, 13, 11, 15, 12, 11, 15, 13, 10]},
            '2026': {'empsit': [9, 6, 6, 3, 8, 5, 2, 7, 4, 2, 6, 4],
                     'cpi': [13, 11, 11, 10, 12, 10, 14, 12, 11, 14, 10, 10]},
            'review': 'Visually checked page 4 of both hash-bound original PDFs; dates, not 08:30 timing.',
            'publication_dates': {'2025': '2024-09-27', '2026': '2025-09-26'}},
        'retrospective_calendar': {'snapshot_modified_date': '2026-01-23',
            'establishes_2025_revision_announcement_times': False},
        'fed': {'captured_keys': sorted(k for k in inventory if k.startswith('fed-')),
            'annual_advance_notice_years_located': list(range(2006, 2027)),
            'full_as_of_reconciliation_admitted': False,
            'note': 'Advance annual notices and specific date changes are archived; current/actual meeting dates cannot replace versioned notices. Full event-by-event reconciliation stopped at failed BLS gate.'},
        'spy': {'receipt_sha256': receipt['receipt_sha256'], 'data_sha256': receipt['identity']['data_sha256'],
            'sessions': len(spy['prices']), 'distributions': len(spy['distributions']),
            'excluded_fields': receipt['excluded_fields'], 'policies': receipt['identity']['policies'],
            'source_split': receipt['split'], 'full_share_action_inventory_admitted': False},
        'price_or_event_returns_computed': False}
