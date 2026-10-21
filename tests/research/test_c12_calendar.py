from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from tradingbot.research import c12_calendar as c


TEXT = '''Transmission of material is embargoed until
8:30 a.m. (EST) Friday, January 6, 2006
THE EMPLOYMENT SITUATION -- DECEMBER 2005
The Employment Situation for January 2006 is scheduled to be released on
Friday, February 3, at 8:30 A.M. (EST).'''


def test_forward_sentence_year_inference_and_semantic_duplicate():
    row = c.parse_release(TEXT, 'empsit', '2005-12')
    assert row['published_at'] == '2006-01-06T13:30:00+00:00'
    assert row['next_announcement']['reference_month'] == '2006-01'
    assert row['next_announcement']['announced_date'] == '2006-02-03'
    duplicate = TEXT + TEXT[TEXT.index('The Employment'):].replace('January 2006', 'January')
    assert c.parse_release(duplicate, 'empsit', '2005-12') == row


@pytest.mark.parametrize('old,new', [('Friday, February 3','Thursday, February 3'),
    ('(EST).','(EDT).'),('for January 2006','for January 2005')])
def test_bad_weekday_zone_and_reference_year_are_rejected(old,new):
    with pytest.raises(ValueError):
        c.parse_release(TEXT.replace(old,new), 'empsit', '2005-12')


def test_reissue_availability_needs_explicit_unchanged_text_attestation():
    revised = 'This release was reissued on July 16, 2010. '+TEXT
    row = c.parse_release(revised,'empsit','2005-12')
    assert row['available_at'] == '2010-07-17T04:00:00+00:00'
    attested = revised + ' There were no changes made to the text of the release.'
    row = c.parse_release(attested,'empsit','2005-12')
    assert row['available_at'] == row['published_at'] and row['reissue_attests_text_unchanged']


def test_wrong_family_and_changed_month_not_inferred():
    with pytest.raises(ValueError,match='title'):
        c.parse_release(TEXT,'cpi','2005-12')
    with pytest.raises(ValueError):
        c.parse_release(TEXT,'empsit','2005-11')
    with pytest.raises(ValueError,match='identity'):
        c.parse_release(TEXT,'invalid','2005-12')


def test_capture_writes_inside_one_nonreentrant_budget_and_reuses_verified_bytes(tmp_path,monkeypatch):
    calls, active = [], []
    @contextmanager
    def reserve(amount):
        assert not active
        active.append(amount)
        yield
        active.pop()
    class Response:
        status=200
        headers={'Content-Type':'application/pdf'}
        def read(self,n): return b'%PDF-test'
        def geturl(self): return 'https://www.bls.gov/test.pdf'
        def __enter__(self): return self
        def __exit__(self,*args): pass
    def opening(*args,**kwargs):
        calls.append(args)
        return Response()
    monkeypatch.setattr(c,'ARCHIVE',tmp_path)
    monkeypatch.setattr(c,'urlopen',opening)
    monkeypatch.setattr(c,'CaptureDiskBudget',lambda _:SimpleNamespace(check_free=lambda n:None,reserve=reserve))
    first=c.capture('test','https://www.bls.gov/test.pdf')
    assert c.capture('test','https://www.bls.gov/test.pdf')==first and len(calls)==1 and not active
    (tmp_path/'captures/test/raw').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='changed'):
        c.capture('test','https://www.bls.gov/test.pdf')
    with pytest.raises(ValueError,match='identity'):
        c.capture('../escape','https://www.bls.gov/test.pdf')


def sessions():
    rows=[]
    start=datetime(2026,2,2,9,30,tzinfo=c.NY)
    for i in range(35):
        stamp=start+timedelta(days=i)
        if stamp.weekday()>=5 or stamp.date().isoformat()=='2026-02-16': continue
        rows.append({'date':str(stamp.date()),'opens_at':stamp.isoformat(),
                     'closes_at':stamp.replace(hour=16,minute=0).isoformat()})
    return rows


def announcement(day='2026-02-13',available='2026-01-09T13:30:00+00:00',family='empsit',reference='2026-01'):
    return {'family':family,'reference_month':reference,'announced_date':day,
            'available_at':available,'source_sha256':'synthetic'}


def calendar(*notices):
    return {'announcements':list(notices or [announcement()]),'suspensions':[],
            'fed':{'announcements':[{'meeting_id':'2026-01','announced_date':'2026-01-28',
             'available_at':'2025-08-01T04:00:00+00:00','source_sha256':'synthetic'}]}}


def test_predecision_cancellation_vs_late_revision_and_fixed_exit():
    days=sessions()
    notice=announcement(None,'2026-02-11T20:59:00+00:00')
    assert not c.causal_windows(calendar(announcement(),notice),days)[0]
    notice['available_at']='2026-02-11T21:00:01+00:00'
    windows,_=c.causal_windows(calendar(announcement(),notice),days)
    assert len(windows)==1 and (windows[0]['decision'],windows[0]['entry'],windows[0]['exit'])==('2026-02-11','2026-02-12','2026-02-17')
    replacement=announcement('2026-02-20','2026-02-12T05:00:00+00:00')
    windows,_=c.causal_windows(calendar(announcement(),replacement),days)
    assert len(windows)==2 and windows[0]['exit']=='2026-02-17'
    assert windows[0]['identity']==windows[1]['identity']  # reactor enforces one entry


def test_activated_suspension_requires_new_target_and_does_not_rewrite_old_decision():
    data=calendar();data['suspensions']=[{'available_at':'2026-02-10T05:00:00+00:00'}]
    assert not c.causal_windows(data,sessions())[0]
    data['announcements'].append(announcement('2026-02-20','2026-02-12T05:00:00+00:00'))
    windows,_=c.causal_windows(data,sessions())
    assert len(windows)==1 and windows[0]['announced_date']=='2026-02-20'
    data['suspensions'][0]['available_at']='2026-02-12T05:00:00+00:00'
    assert len(c.causal_windows(data,sessions())[0])==2


def test_ambiguous_same_time_notice_fails_and_non_session_never_rolls():
    data=calendar(announcement(),announcement('2026-02-20'))
    with pytest.raises(ValueError,match='contradictory'):
        c.causal_windows(data,sessions())
    windows,skips=c.causal_windows(calendar(announcement('2026-02-16')),sessions())
    assert not windows and 'not an in-source equity session' in skips[0]['reason']


def test_fed_asof_revision_and_preceding_session_half_open_interval():
    data=calendar();days=sessions();w=c.causal_windows(data,days)[0][0]
    # Exit Tuesday open; a Wednesday decision's preceding Tuesday session is
    # outside the holding interval. A Tuesday decision blocks via Friday.
    fed=data['fed']['announcements'][0]
    fed['announced_date']='2026-02-18'
    assert not c.fed_conflicts(data,days,w)
    revised={**fed,'announced_date':'2026-02-17','available_at':'2026-02-11T21:00:01+00:00'}
    data['fed']['announcements'].append(revised)
    assert not c.fed_conflicts(data,days,w)
    revised['available_at']='2026-02-11T20:59:00+00:00'
    assert c.fed_conflicts(data,days,w)
    data['fed']['announcements']=[]
    with pytest.raises(ValueError,match='provenance'):
        c.fed_conflicts(data,days,w)


def test_shifted_control_exact_endpoints_duration_and_other_family_exclusion():
    data=calendar(announcement('2026-02-17'))
    controls,_=c.windows(data,sessions(),'empsit',control=True)
    assert not controls  # Presidents Day changes the shifted interval's session count.
    data=calendar(announcement('2026-03-04'))
    controls,_=c.windows(data,sessions(),'empsit',control=True)
    assert len(controls)==1 and controls[0]['entry']=='2026-02-24' and controls[0]['exit']=='2026-02-26'
    data['announcements'].append(announcement('2026-02-25',family='cpi'))
    controls,skips=c.windows(data,sessions(),'empsit',control=True)
    assert not controls and any(s['reason']=='control intersects BLS window' for s in skips)


def test_reconciliation_does_not_drop_missing_or_failed_months():
    with pytest.raises(ValueError,match='parses'):
        c.reconcile_calendar({}, {'month':'unreadable'})
    with pytest.raises(ValueError,match='denominator'):
        c.reconcile_calendar({}, {})
