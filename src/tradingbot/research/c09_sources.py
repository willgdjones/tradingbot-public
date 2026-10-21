"""C09 public-notice and IEF integrity audit; never calculate strategy returns."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D
import json
import re
import subprocess
from xml.etree import ElementTree

from tradingbot.research.c09_capture import ARCHIVE, HOST, ROOT, digest, document_url, index, read, relevant

MONTH = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
DATE = MONTH + r'\s+\d{1,2},\s+\d{4}'
CUSIP = r'\b912[A-Z0-9]{3}\s*[A-Z0-9]{2}\s*\d\b'


def day(value):
    return datetime.strptime(' '.join(value.split()), '%B %d, %Y').date()


def field(text, label):
    rows = re.findall(r'^[ \t]*' + label + r'(?=[ \t.])[ \t.]+(.*?)[ \t]*$', text, re.I | re.M)
    if len(rows) != 1:
        raise ValueError(f'missing or ambiguous offering field: {label}')
    return rows[0]


def offering(text, row):
    """Read the target CUSIP column; old notices can contain several maturities."""
    cusips = [re.sub(r'\s', '', v) for v in re.findall(CUSIP, field(text, r'CUSIP number'))]
    if len(set(cusips)) != len(cusips) or cusips.count(row['a']) != 1:
        raise ValueError('offering CUSIP missing or ambiguous')
    column = cusips.index(row['a'])

    def dates(label, required=True):
        if not required and not re.search(r'^[ \t]*' + label + r'(?=[ \t.])', text, re.I | re.M):
            return None
        found = re.findall(DATE, field(text, label), re.I)
        if len(found) != len(cusips):
            raise ValueError('offering date/CUSIP columns disagree')
        return day(found[column])

    auction, issue, maturity = (dates(label) for label in ('Auction date', 'Issue date', 'Maturity date'))
    original = dates('Original issue date', False)
    header = '\n'.join(text.splitlines()[:4])
    stamped = re.findall(DATE, header, re.I)
    embargo = re.search(r'EMBARGOED\s+UNTIL\s+(\d{1,2}:\d{2})\s*([AP])\.?M', header, re.I)
    if len(stamped) != 1 or not embargo:
        raise ValueError('offering lacks unambiguous dated embargo header')
    announcement = day(stamped[0])
    if (str(auction) != row['i'][:10] or str(announcement) != row['h'][:10]
            or not announcement <= auction <= issue < maturity):
        raise ValueError('dated offering disagrees with index or chronology')
    term = field(text, 'Term and type of security')
    return {'cusip': row['a'], 'auction_date': str(auction), 'announcement_date': str(announcement),
            'embargo_clock': embargo[1] + ' ' + embargo[2].upper() + 'M',
            'issue_date': str(issue), 'original_issue_date': str(original) if original else None,
            'maturity_date': str(maturity), 'index_term': row['d'],
            'original_ten_year_index': relevant(row), 'term_row': term,
            'column': column, 'columns': len(cusips)}


def pdf_text(folder, url):
    meta, raw = read(folder, 'raw.pdf', url)
    if meta['status'] != 200 or not raw.startswith(b'%PDF-'):
        raise ValueError('Treasury PDF HTTP/content failure')
    text = subprocess.check_output(['pdftotext', '-layout', str(folder / 'raw.pdf'), '-'],
                                   timeout=15).decode()
    if not text.strip():
        raise ValueError('empty PDF text')
    return meta, text


def occurrence(text, row):
    """Only release date and instrument identity; no auction result is a signal."""
    release = re.search(r'FOR\s+IMMEDIATE\s+RELEASE[^\n]*\n\s*(' + DATE + ')', text, re.I)
    cusip = re.findall(r'^\s*CUSIP (?:Number|No):?\s+(' + CUSIP + ')', text, re.I | re.M)
    if not release or len(cusip) != 1 or re.sub(r'\s', '', cusip[0]) != row['a']:
        raise ValueError('auction occurrence release/CUSIP mismatch')
    if str(day(release[1])) != row['i'][:10]:
        raise ValueError('auction occurrence date differs from schedule')
    return {'release_date': str(day(release[1])), 'cusip': row['a']}


def xml_occurrence(raw, row):
    """Official linked XML alternative; inspect identity/clock, never yield."""
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('XML document declarations are not allowed')
    doc = ElementTree.fromstring(raw)
    if (doc.tag != '{http://www.treasurydirect.gov/}AuctionData'
            or [v.tag for v in doc] != ['AuctionAnnouncement', 'AuctionResults']):
        raise ValueError('auction XML schema/sections changed')
    announcement, results = doc

    def scalar(section, name):
        values = section.findall(name)
        if len(values) != 1 or len(values[0]):
            raise ValueError('ambiguous XML identity field')
        return values[0].text

    if (scalar(announcement,'CUSIP') != row['a']
            or scalar(announcement,'AnnouncementDate') != row['h'][:10]
            or scalar(announcement,'AuctionDate') != row['i'][:10]
            or scalar(announcement,'SecurityType') != 'NOTE'
            or scalar(results,'OriginalCUSIP') not in (None, row['a'])):
        raise ValueError('auction XML identity/date mismatch')
    release = scalar(results, 'ReleaseTime')
    if not re.fullmatch(r'\d{2}:\d{2}', release or '') or not '00:00' <= release < '16:00':
        raise ValueError('auction XML release not before regular close')
    datetime.strptime(release, '%H:%M')
    return {'release_date': row['i'][:10], 'release_clock_et': release, 'cusip': row['a']}


def occurrence_source(row):
    name, year = row['f3'], row['i'][:4]
    if not name:
        raise ValueError('missing auction occurrence PDF')
    url = document_url(year, name)
    folder = ARCHIVE / 'results' / year / name
    meta, _ = read(folder, 'raw.pdf', url)
    if meta['status'] == 200:
        meta, text = pdf_text(folder, url)
        return {**occurrence(text, row), 'url':url, 'sha256':meta['sha256'], 'format':'pdf'}
    # This explicit source exception preserves the failed PDF and uses only
    # the XML link supplied by the same official index/JavaScript.
    if not (name == 'R_20201209_3.pdf' and row['ia1'] == 'R_20201209_3.xml' and meta['status'] == 404):
        raise ValueError('auction occurrence PDF unavailable without reviewed alternative')
    xml_url = HOST + '/xml/' + row['ia1']
    xm, raw = read(ARCHIVE/'published-xml'/year/row['ia1'], 'raw.xml', xml_url)
    if xm['status'] != 200:
        raise ValueError('auction occurrence XML HTTP failure')
    return {**xml_occurrence(raw, row), 'url':xml_url, 'sha256':xm['sha256'], 'format':'xml',
            'failed_pdf':{'url':url, 'status':404, 'sha256':meta['sha256']}}


def treasury_audit():
    sources, records, failures, specials = {}, [], [], {}
    for year in range(2005, 2027):
        meta, rows = index(year)
        sources[str(year)] = {'sha256': meta['sha256'], 'all_rows': len(rows),
                              'nominal_ten_year_rows': sum(relevant(r) for r in rows)}
        for row in rows:
            if not relevant(row):
                continue
            name, pdf_year = row['e3'], row['h'][:4]
            base = {'cusip': row['a'], 'auction_date': row['i'][:10], 'filename': name,
                    'source_year': year, 'use': 'lineage_only' if year == 2005 else 'candidate_event'}
            try:
                if not name:
                    raise ValueError('missing offering PDF link')
                url = document_url(pdf_year, name)
                receipt, text = pdf_text(ARCHIVE / 'offering' / pdf_year / name, url)
                record = {**base, **offering(text, row), 'url': url, 'sha256': receipt['sha256']}
                record['occurrence'] = occurrence_source(row)
                records.append(record)
            except (ValueError, FileNotFoundError, subprocess.SubprocessError) as exc:
                failures.append({**base, 'error': str(exc)})
            for special in filter(None, (s.strip() for s in row['f32'].split(','))):
                match = re.search(r'SPL_(\d{4})', special)
                special_year = match[1] if match else row['i'][:4]
                key = special_year + '/' + special
                if key not in specials:
                    url = document_url(special_year, special)
                    try:
                        sm, text = pdf_text(ARCHIVE / 'special' / special_year / special, url)
                        specials[key] = {'url': url, 'sha256': sm['sha256'], 'text': text,
                                         'linked_events': []}
                    except (ValueError, FileNotFoundError, subprocess.SubprocessError) as exc:
                        failures.append({**base, 'special': key, 'error': str(exc)})
                        continue
                specials[key]['linked_events'].append(base)
    originals = {}
    for record in records:
        if record['index_term'] == '10-Year':
            original = date.fromisoformat(record['issue_date'])
            maturity = date.fromisoformat(record['maturity_date'])
            # Coupon issue dates can roll off weekends; explicit original date wins.
            if record['original_issue_date']:
                original = date.fromisoformat(record['original_issue_date'])
            if not 3645 <= (maturity-original).days <= 3665:
                failures.append({**record, 'error': 'original-ten-year date span mismatch'})
            if record['cusip'] in originals:
                failures.append({**record, 'error': 'duplicate original CUSIP offering'})
            originals[record['cusip']] = record
    for record in records:
        original = originals.get(record['cusip'])
        if original is None or original['maturity_date'] != record['maturity_date']:
            failures.append({**record, 'error': 'original CUSIP lineage unavailable or inconsistent'})
        elif (record['original_issue_date'] and original['original_issue_date']
              and record['original_issue_date'] != original['original_issue_date']):
            failures.append({**record, 'error': 'original issue dates conflict'})
        else:
            record['lineage_offering_sha256'] = original['sha256']
    review_path = ROOT/'docs/research/29-c09-special-notice-review.json'
    reviews = json.loads(review_path.read_text())
    if set(reviews) != set(specials):
        raise ValueError('special notice review inventory changed')
    for key, special in specials.items():
        review = reviews[key]
        stamps = re.findall(DATE, '\n'.join(special['text'].splitlines()[:3]), re.I)
        if (review['sha256'] != special['sha256'] or len(stamps) != 1
                or str(day(stamps[0])) != review['date']
                or any(review['date'] > e['auction_date'] for e in special['linked_events'])):
            raise ValueError('special notice bytes/date/availability conflict')
        special['review'] = review
        del special['text']
    return {'annual_indexes': sources, 'offering_records': sorted(records, key=lambda r:(r['auction_date'],r['cusip'])),
            'failures': failures, 'special_announcements': specials,
            'events_enumerated': sum(v['nominal_ten_year_rows'] for y,v in sources.items() if y != '2005'),
            'parsed_events': sum(r['use'] == 'candidate_event' for r in records),
            'review_status': 'DATED_NOTICES_AND_OCCURRENCE_RECONCILED' if not failures else 'DATA_FAIL',
            'special_review_sha256':digest(review_path.read_bytes()),
            'scope':'Dated Treasury schedule and occurrence evidence only; not strategy admission or historical broker latency proof.'}


def ief_audit():
    """Recheck existing original bytes, including both open and close references."""
    from tradingbot.connectors.cash import NEW_YORK
    from tradingbot.data.free_history import parse_yahoo
    from tradingbot.research.c03_source_audit import load_source, inspect_source
    from tradingbot.research.c03_c04_c03_audit import document, reference, reconcile
    from tradingbot.research.c06_sources import ishares_distributions, spy_source
    from tradingbot.research.equity_data import load_equities

    yahoo, raw = load_source(ROOT / 'data/research/c03/IEF', 'IEF')
    if yahoo['status_code'] != 200:
        raise ValueError('IEF source HTTP failure')
    calendar = load_equities(ROOT / 'data/equities/c04', 'c04-20261001')
    coverage = inspect_source(raw, 'IEF', calendar.sessions)
    if not coverage['coverage_ok']:
        raise ValueError('IEF complete session/field integrity failure')
    _, bars = parse_yahoo(raw.decode())
    by_day = {b.date:b for b in bars}
    issuer, body = document(ROOT / 'data/research/c06/ief-issuer-page', 'raw.html',
        'https://www.ishares.com/us/products/239456/ishares-7-10-year-treasury-bond-etf')
    distributions = reconcile(bars, ishares_distributions(body.decode()))
    if any(distributions[k] for k in ('missing_issuer_dates','issuer_only_dates','amount_conflicts')):
        raise ValueError('IEF issuer distribution inventory does not reconcile')
    overlaps = {}
    for feed in ('sip', 'iex'):
        params = {'symbols':'IEF','timeframe':'1Day','start':'2016-01-01T00:00:00Z',
            'end':'2026-10-01T00:00:00Z','adjustment':'raw','feed':feed,'limit':10000,'sort':'asc','asof':'-'}
        ref, payload = reference('bars_IEF_'+feed, 'https://data.alpaca.markets/v2/stocks/bars', params, 'bars', 'IEF')
        seen, worst = set(), {'open':D(0), 'close':D(0)}
        for row in payload['bars']['IEF']:
            when = datetime.fromisoformat(row['t'].replace('Z','+00:00')).astimezone(NEW_YORK).date()
            if when in seen or when not in by_day:
                raise ValueError('IEF reference date mismatch')
            seen.add(when)
            for name in ('open','close'):
                price = D(row[name[0]])
                if not price.is_finite() or price <= 0:
                    raise ValueError('IEF reference price invalid')
                distance = abs(getattr(by_day[when],name)/price-1)
                worst[name] = max(worst[name],distance)
                if distance > D('.01'):
                    raise ValueError('IEF price exceeds frozen 1% reconciliation bound')
        if not seen:
            raise ValueError('IEF independent reference empty')
        missing = sorted(d for d in calendar.sessions if min(seen)<=d<=max(seen) and d not in seen)
        if feed == 'sip' and missing:
            raise ValueError('IEF consolidated overlap missing sessions')
        overlaps[feed] = {'source':ref, 'first':str(min(seen)), 'last':str(max(seen)),
                          'sessions':len(seen), 'missing_sessions':list(map(str,missing)),
                          'worst_relative_difference':{k:str(v) for k,v in worst.items()},
                          'tolerance':'0.01', 'breaches':0}
    action_ref, payload = reference('corporate_actions', 'https://data.alpaca.markets/v1/corporate-actions',
        {'symbols':'EFA,GLD,IEF,SPY,VNQ','start':'2006-01-01','end':'2026-09-30','limit':1000,'sort':'asc'}, 'actions')
    actions = payload['corporate_actions']
    if set(actions) != {'cash_dividends'}:
        raise ValueError('unreviewed noncash corporate action')
    cash = [r for r in actions['cash_dividends'] if r['symbol'] == 'IEF']
    if not cash:
        raise ValueError('IEF broker action overlap empty')
    earliest = min(r['ex_date'] for r in cash)
    observed_dates = {r['ex_date'] for r in cash}
    omitted = [r['ex_date'] for r in distributions['rows'] if r['ex_date'] not in observed_dates]
    spy_receipt, _ = spy_source()
    return {'yahoo':yahoo, 'coverage':coverage, 'issuer':issuer, 'distributions':distributions,
            'overlap':overlaps, 'broker_action_source':action_ref,
            'broker_actions':{'ief_cash_rows':len(cash), 'all_symbols_cash_rows':len(actions['cash_dividends']),
                              'first_ief_ex_date':earliest, 'noncash_rows':0,
                              'known_issuer_cash_dates_absent_from_broker_inventory':omitted,
                              'known_missing_before_first_date':sum(d<earliest for d in omitted),
                              'known_missing_inside_observed_span':[d for d in omitted if d>=earliest]},
            'calendar_source_sha256':digest((ROOT/'docs/research/13-equity-data-repair-calendar.json').read_bytes()),
            'cash_calendar_reference_receipt':spy_receipt['receipt_sha256'],
            'admission':'INCOMPLETE_SHARE_ACTION_COVERAGE',
            'limitation':'Yahoo has no split events; issuer table establishes cash distributions only. '
                'The requested 2006 broker action query actually starts in 2016 and omits known prior cash events. '
                'Neither a current prospectus nor a web search supplies a complete earlier noncash-action inventory. '
                'C06 never owned IEF and its reference-only admission cannot authorize C09 execution.'}


if __name__ == '__main__':
    from collections import Counter
    result = treasury_audit()
    print(json.dumps({'events': result['events_enumerated'], 'parsed': result['parsed_events'],
                      'failure_counts': dict(Counter(r['error'] for r in result['failures'])),
                      'failure_examples': result['failures'][:4],
                      'specials': list(result['special_announcements'])}, indent=2))
