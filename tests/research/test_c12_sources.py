from datetime import date
import json

import pytest

from tradingbot.research import c12_sources as c


@pytest.fixture(scope='module')
def evidence():
    return c.audit_sources()


def test_missing_and_canceled_issues_do_not_shrink_original_denominator(evidence):
    for family, count, missing in [('empsit', 247, ['2024-06', '2025-10']),
                                   ('cpi', 248, ['2025-10'])]:
        row = evidence['issue_indices'][family]
        assert row['expected_reference_months'] == 249
        assert row['issues_found'] == count and row['missing_reference_months'] == missing
        assert not row['advance_availability_proven']
    assert evidence['sampled_prior_releases']['empsit-20240705-pdf']['published_at'].startswith('2024-07-05')


def test_original_and_revised_next_announcements_remain_separate(evidence):
    rows = evidence['sampled_prior_releases']
    assert rows['empsit-20130906-pdf']['next_announcement']['announced_date'] == '2013-10-04'
    assert rows['empsit-20131022-pdf']['next_announcement']['announced_date'] == '2013-11-08'
    assert rows['cpi-20131030-pdf']['next_announcement']['announced_date'] == '2013-11-20'
    assert rows['cpi-20251024-pdf']['next_announcement'] is None
    assert rows['empsit-20260109-pdf']['next_announcement']['announced_date'] == '2026-02-06'
    assert not evidence['revision_chronology_admitted']


def test_good_friday_is_excluded_without_rolling_and_original_windows_are_fixed(evidence):
    examples = evidence['calendar_examples']
    assert not examples['2026-04-03']['equity_session']
    assert examples['2026-04-03']['entry_at'] is None
    assert examples['2013-10-04']['decision_at'].startswith('2013-10-02')
    assert examples['2013-10-04']['exit_at'].startswith('2013-10-07')
    assert examples['2025-10-03']['decision_at'].startswith('2025-10-01')
    assert examples['2025-10-24']['entry_at'].startswith('2025-10-23')
    assert examples['2025-10-24']['exit_at'].startswith('2025-10-27')


def test_date_only_update_cannot_establish_availability_before_same_day_close(evidence):
    examples = evidence['calendar_examples']
    assert not c.date_only_available_before(date(2026, 2, 4), examples['2026-02-06']['decision_at'])
    assert c.date_only_available_before(date(2026, 2, 4), examples['2026-02-11']['decision_at'])
    assert not c.date_only_available_before(date(2025, 12, 11), examples['2025-12-10']['decision_at'])
    with pytest.raises(ValueError, match='timezone'):
        c.date_only_available_before(date(2026, 2, 4), '2026-02-05T16:00:00')


@pytest.mark.parametrize('old,new', [('Friday, February 6', 'Thursday, February 6'),
    ('(ET)', '(EDT)'), ('January 9, 2026', 'January 8, 2026'),
    ('The Employment Situation for January', 'The Consumer Price Index for January')])
def test_publication_daylight_saving_and_family_contradictions_fail(old, new):
    text = c.pdf_text('empsit-20260109-pdf')
    normalized = ' '.join(text.split()).replace(old, new)
    with pytest.raises(ValueError):
        c.release_metadata(normalized, 'empsit', date(2026, 1, 9))


def test_issue_inventory_rejects_foreign_family_and_conflicting_reference_identity():
    root = 'https://fraser.stlouisfed.org/title/employment-situation-144'
    doc = {'@type': 'CreativeWork', 'url': root, 'hasPart': [
        {'@type': 'CreativeWork', 'name': 'January 2006', 'url': root + '/one'},
        {'@type': 'Periodical', 'name': 'January 2006', 'url': root + '/two'}]}
    def encoded(): return ('<script type="application/ld+json">' + json.dumps(doc) + '</script>').encode()
    with pytest.raises(ValueError, match='conflicting'):
        c.issue_index(encoded(), 'empsit')
    doc['hasPart'].pop()
    doc['hasPart'][0]['url'] = 'https://attacker.invalid/release'
    with pytest.raises(ValueError, match='family'):
        c.issue_index(encoded(), 'empsit')


def test_successful_capture_and_known_source_scope_do_not_imply_dataset_admission(evidence):
    assert len(evidence['public_sources']) == 74
    assert any(s['status'] == 403 for s in evidence['public_sources'].values())
    assert evidence['spy']['sessions'] == 5218 and evidence['spy']['distributions'] == 83
    assert evidence['fed']['annual_advance_notice_years_located'] == list(range(2006, 2027))
    assert not evidence['fed']['full_as_of_reconciliation_admitted']
    assert not evidence['spy']['full_share_action_inventory_admitted']
    assert not evidence['price_or_event_returns_computed']
