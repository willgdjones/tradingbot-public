"""Source integrity failures must never become an auction signal."""
import json

import pytest

from tradingbot.research.c09_capture import digest, document_url, index_params, read, relevant
from tradingbot.research.c09_sources import offering, occurrence, xml_occurrence


OLD = '''EMBARGOED UNTIL 9:00 A.M. CONTACT: Office of Financing
May 3, 2006

TREASURY MAY QUARTERLY FINANCING
Term and type of security.......... 3-year notes          10-year notes
CUSIP number....................... 912828 FE 5           912828 FF 2
Auction date....................... May 9, 2006           May 11, 2006
Issue date......................... May 15, 2006          May 15, 2006
Maturity date...................... May 15, 2009          May 15, 2016
'''
ROW = {'a':'912828FF2', 'h':'2006-05-03T00:00:00', 'i':'2006-05-11T00:00:00',
       'z3a':'Note', 't3a':'10-Year', 'd':'10-Year'}

NEW = '''Embargoed Until 10:30 A.M. CONTACT: Office of Financing
October 08, 2008

TREASURY OFFERING ANNOUNCEMENT
Term and Type of Security             6-Year 4-Month 4% Note
CUSIP Number                         912828DM9
Auction Date                         October 09, 2008
Original Issue Date                  February 15, 2005
Issue Date                           October 15, 2008
Maturity Date                        February 15, 2015
Corpus CUSIP Number                  912820LJ4
CUSIP Number(s)                      None
'''
REOPEN = {'a':'912828DM9', 'h':'2008-10-08T00:00:00', 'i':'2008-10-09T00:00:00',
          'z3a':'Note', 't3a':'10-Year', 'd':'6-Year 4-Month'}


def test_old_multi_maturity_notice_selects_exact_cusip_column():
    result = offering(OLD, ROW)
    assert result['column'] == 1
    assert result['auction_date'] == '2006-05-11'
    assert result['maturity_date'] == '2016-05-15'


def test_emergency_reopening_is_original_ten_year_despite_short_remaining_term():
    assert relevant(REOPEN)
    result = offering(NEW, REOPEN)
    assert result['original_issue_date'] == '2005-02-15'
    assert result['maturity_date'] == '2015-02-15'


@pytest.mark.parametrize('change', [
    {'a':'912828XX9'}, {'i':'2006-05-12T00:00:00'}, {'h':'2006-05-02T00:00:00'}])
def test_conflicting_index_never_overrides_dated_notice(change):
    with pytest.raises(ValueError):
        offering(OLD, {**ROW, **change})


@pytest.mark.parametrize('text', [
    OLD.replace('912828 FE 5', '912828 FF 2'),
    OLD.replace('May 9, 2006', ''),
    OLD.replace('EMBARGOED UNTIL 9:00 A.M.', 'RETRIEVED TODAY'),
    NEW + 'Original Issue Date    February 16, 2005\n',
])
def test_ambiguous_or_missing_notice_metadata_fails(text):
    with pytest.raises(ValueError):
        offering(text, REOPEN if '912828DM9' in text else ROW)


@pytest.mark.parametrize('change', [{'z3a':'TIPS'}, {'z3a':'FRN'}, {'t3a':'30-Year'}])
def test_non_nominal_or_other_original_maturity_is_excluded(change):
    assert not relevant({**REOPEN, **change})


def test_result_document_proves_occurrence_without_reading_yield():
    text = 'FOR IMMEDIATE RELEASE CONTACT: Treasury Auctions\nMay 11, 2006\nCUSIP No: 912828FF2 Maturity Date: May 15, 2016\nHigh Yield: NEVER PARSE\n'
    assert occurrence(text, ROW) == {'release_date':'2006-05-11', 'cusip':'912828FF2'}
    for bad in [text.replace('May 11, 2006','May 12, 2006'), text.replace('912828FF2','912810FT0')]:
        with pytest.raises(ValueError): occurrence(bad, ROW)


def test_immutable_capture_binds_bytes_and_request(tmp_path):
    body = b'original Treasury bytes'
    url = document_url(2006, 'ofg050306.pdf')
    meta = {'url':url, 'status':200, 'params':None, 'sha256':digest(body), 'bytes':len(body)}
    (tmp_path/'raw.pdf').write_bytes(body)
    (tmp_path/'manifest.json').write_text(json.dumps(meta))
    assert read(tmp_path,'raw.pdf',url)[1] == body
    with pytest.raises(ValueError): read(tmp_path,'raw.pdf',url+'?changed=true')
    (tmp_path/'raw.pdf').write_bytes(b'changed Treasury bytes')
    with pytest.raises(ValueError): read(tmp_path,'raw.pdf',url)


@pytest.mark.parametrize('year,name', [('2026','../notice.pdf'), ('../x','notice.pdf'), ('2026','notice.xml')])
def test_pdf_paths_cannot_escape_capture(year,name):
    with pytest.raises(ValueError): document_url(year,name)


def test_latest_year_ends_at_fixed_boundary():
    assert index_params(2026)['endDate'] == '2026-09-30'
    assert index_params(2006)['endDate'] == '2006-12-31'


XML = b'''<td:AuctionData xmlns:td="http://www.treasurydirect.gov/">
<AuctionAnnouncement><SecurityType>NOTE</SecurityType><CUSIP>912828FF2</CUSIP>
<AnnouncementDate>2006-05-03</AnnouncementDate><AuctionDate>2006-05-11</AuctionDate></AuctionAnnouncement>
<AuctionResults><OriginalCUSIP/><ReleaseTime>13:02</ReleaseTime><HighYield>DO NOT PARSE</HighYield></AuctionResults>
</td:AuctionData>'''


def test_dated_official_xml_alternative_uses_only_identity_and_release_clock():
    assert xml_occurrence(XML,ROW) == {'release_date':'2006-05-11','release_clock_et':'13:02','cusip':'912828FF2'}


@pytest.mark.parametrize('old,new', [
    (b'13:02',b'16:01'), (b'13:02',b'12:99'),
    (b'<OriginalCUSIP/>',b'<OriginalCUSIP>912810FT0</OriginalCUSIP>'),
    (b'<SecurityType>NOTE',b'<SecurityType>BOND'),
    (b'<CUSIP>912828FF2</CUSIP>',b'<CUSIP>912828FF2</CUSIP><CUSIP>912828FF2</CUSIP>'),
    (b'2006-05-11',b'2006-05-12'),
])
def test_xml_identity_conversion_ambiguity_or_late_release_fails(old,new):
    with pytest.raises(ValueError): xml_occurrence(XML.replace(old,new),ROW)


def test_xml_entity_declaration_rejected():
    with pytest.raises(ValueError,match='declarations'):
        xml_occurrence(b'<!DOCTYPE x>'+XML,ROW)
