import pytest

from investigator.facts import extract_quantities, parse_dates, dates_compatible
from investigator.textutil import contains_quote, sentences, stem, find_span


@pytest.mark.parametrize("a,b", [("terminated", "termination"), ("terminate", "terminates"), ("headquartered", "headquarters"),
                                 ("employees", "employee"), ("capped", "cap"), ("payments", "payment")])
def test_stemmer_conflates_variants(a, b):
    assert stem(a) == stem(b)


def test_sentence_split_keeps_abbreviations_and_decimals():
    s = sentences("Dr. Smith paid $3.5 million to Acme Inc. on Monday. The fee is 1.5% per month. Net 30 applies.")
    assert len(s) == 3
    assert s[0].startswith("Dr. Smith") and "Acme Inc. on Monday" in s[0]


def test_newline_ends_sentence():
    assert sentences("Item one\nItem two") == ["Item one", "Item two"]


def kinds(text):
    return [(q.kind, q.value, q.unit) for q in extract_quantities(text)]


def test_money_variants():
    assert ("money", 480000.0, "USD") in kinds("The value is $480,000.")
    assert ("money", 2400000.0, "USD") in kinds("A budget of $2.4 million was approved.")
    assert ("money", 1500.0, "EUR") in kinds("It costs EUR 1,500 per seat.")


def test_duration_normalised_to_days_and_number_words():
    assert ("duration", 60.0, "day") in kinds("Written notice of sixty (60) days is required.")
    assert ("duration", 60.0, "day") in kinds("Notice of 2 months is required.")
    assert ("duration", 720.0, "day") in kinds("a term of twenty-four months")        # spelled-out numbers (24 months = 720 days)
    assert ("duration", 720.0, "day") in kinds("a term of twenty-four (24) months")
    assert ("duration", 45.0, "day") in kinds("Invoices are payable Net 45.")
    assert ("duration", 3.0, "hour") in kinds("It lasted 3 hours.")


def test_percent_and_dates():
    assert ("percent", 1.5, "%") in kinds("interest of 1.5% per month")
    assert ("date", "2023-03-03", "") in kinds("signed on March 3, 2023")
    assert ("date", "2023-03-03", "") in kinds("signed on 3 March 2023")
    assert ("date", "2024-06", "") in kinds("as of June 2024")


def test_years_and_section_refs_are_not_values():
    qs = extract_quantities("Under Section 4.2 of the 2023 policy, see Table 3 on page 12.")
    assert not [q for q in qs if q.kind == "number"]


def test_plain_counts_are_numbers():
    assert ("number", 142.0, "") in kinds("Northwind has 142 employees.")


def test_date_compat_precision():
    assert dates_compatible("2023-03", "2023-03-05")
    assert not dates_compatible("2023-03-04", "2023-03-05")
    assert parse_dates("no dates here") == []


def test_contains_quote_is_whitespace_and_quote_insensitive():
    passage = "Invoices are payable\nNet 45 from the “invoice date”."
    assert contains_quote(passage, "payable Net 45 from the \"invoice date\"")
    assert not contains_quote(passage, "payable Net 90 from the invoice date")
    assert not contains_quote(passage, "net")          # too short to count as evidence


def test_find_span_whitespace_tolerant():
    t = "alpha  beta\ngamma"
    a, b = find_span(t, "beta gamma")
    assert t[a:b] == "beta\ngamma"
