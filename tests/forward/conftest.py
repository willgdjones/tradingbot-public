"""All forward fixtures, including directly imported session factories, isolate DB writes."""
import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_forward_database(paper_test_database):
    return paper_test_database
