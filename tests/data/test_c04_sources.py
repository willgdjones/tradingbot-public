from datetime import date
from dataclasses import replace
from decimal import Decimal
import hashlib
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest

from tradingbot.data.c04_sources import Distribution, PaymentDateAmendment, issuer_distributions

HEADERS = {'B':'TICKER', 'D':'EX-DATE', 'E':'RECORD DATE', 'F':'PAYABLE DATE',
           'G':'DIVIDEND ($)', 'H':'SHORT TERM CAPITAL GAIN ($)', 'I':'LONG TERM CAPITAL GAIN ($)'}
ROW = {'B':'SPY', 'D':'06/16/2006', 'E':'06/20/2006', 'F':'07/31/2006',
       'G':'0.555470', 'H':'', 'I':''}


def workbook(tmp_path, rows, *, formula=False):
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet = ET.Element('worksheet', xmlns=ns)
    data = ET.SubElement(sheet, 'sheetData')
    strings = ET.Element('sst', xmlns=ns)
    for index, row in enumerate([HEADERS, *rows], 1):
        element = ET.SubElement(data, 'row', r=str(index))
        for col, value in row.items():
            si = ET.SubElement(strings, 'si'); ET.SubElement(si, 't').text = value
            c = ET.SubElement(element, 'c', r=f'{col}{index}', t='s')
            ET.SubElement(c, 'v').text = str(len(strings)-1)
            if formula and col == 'G' and index > 1:
                ET.SubElement(c, 'f').text = 'SUM(1,2)'
    path = tmp_path / 'issuer.xlsx'
    with ZipFile(path, 'w') as z:
        z.writestr('xl/sharedStrings.xml', ET.tostring(strings))
        z.writestr('xl/worksheets/sheet1.xml', ET.tostring(sheet))
    return path


def test_actual_pay_date_and_all_cash_components(tmp_path):
    rows = [{**ROW, 'H':'0.003400', 'I':'0.001100'}]
    result = issuer_distributions(workbook(tmp_path, rows))[date(2006,6,16)]
    assert result.pay_date == date(2006,7,31)
    assert result.amount == Decimal('0.559970')


def test_rejects_payment_before_record_date(tmp_path):
    with pytest.raises(ValueError, match='record=2006-06-20, pay=2006-06-16'):
        issuer_distributions(workbook(tmp_path, [{**ROW, 'F':'06/16/2006'}]))


def test_duplicate_ex_date_requires_explicit_reconciliation(tmp_path):
    with pytest.raises(ValueError, match='duplicated'):
        issuer_distributions(workbook(tmp_path, [ROW, ROW]))


def test_formula_distribution_is_not_treated_as_verified_cached_value(tmp_path):
    with pytest.raises(ValueError, match='formulas'):
        issuer_distributions(workbook(tmp_path, [ROW], formula=True))


def test_changed_date_layout_fails_instead_of_guessing(tmp_path):
    with pytest.raises(ValueError):
        issuer_distributions(workbook(tmp_path, [{**ROW, 'F':'2006-07-31'}]))


def amendment(path, tmp_path):
    proof = tmp_path / 'primary-prospectus.html'
    proof.write_text('fixture: the reviewed primary payment schedule')
    return PaymentDateAmendment(hashlib.sha256(path.read_bytes()).hexdigest(), 'SPY',
        Distribution(date(2006,6,16), date(2006,6,20), date(2006,6,16), Decimal('0.555470')),
        date(2006,7,31), proof, hashlib.sha256(proof.read_bytes()).hexdigest())


def test_explicit_amendment_preserves_raw_and_default_failure(tmp_path):
    path = workbook(tmp_path, [{**ROW, 'F':'06/16/2006'}])
    original_bytes = path.read_bytes()
    correction = amendment(path,tmp_path)
    result = issuer_distributions(path,payment_amendment=correction)
    assert result[date(2006,6,16)].pay_date == date(2006,7,31)
    assert result[date(2006,6,16)].amount == Decimal('0.555470')
    assert path.read_bytes() == original_bytes
    with pytest.raises(ValueError,match='invalid'):
        issuer_distributions(path)


@pytest.mark.parametrize('change', ['source','evidence','original_row','symbol','unused'])
def test_amendment_cannot_silently_apply_to_different_evidence_or_rows(tmp_path,change):
    path = workbook(tmp_path, [{**ROW, 'F':'06/16/2006'}])
    correction = amendment(path,tmp_path)
    if change == 'source':
        correction = replace(correction,source_sha256='0'*64)
    elif change == 'evidence':
        correction.evidence_path.write_text('changed primary evidence')
    elif change == 'original_row':
        correction = replace(correction,original=replace(correction.original,amount=Decimal('1')))
    elif change == 'symbol':
        correction = replace(correction,symbol='XLF')
    else:
        path = workbook(tmp_path,[ROW])
        correction = replace(correction,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             original=replace(correction.original,ex_date=date(2006,6,15)))
    with pytest.raises(ValueError):
        issuer_distributions(path,payment_amendment=correction)
