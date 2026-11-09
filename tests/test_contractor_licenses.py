from datetime import date

from contractor_licenses import PLACEHOLDER_NAMES, build_matches, name_key

TODAY = date(2026, 11, 7)


def license_record(business, trade=None, category="RESIDENT CONTRACTOR", valid_to="2027-12-31T00:00:00.000", state="DE", number="1"):
    return {
        "business_name": business,
        "trade_name": trade,
        "category": category,
        "current_license_valid_to": valid_to,
        "city": "WILMINGTON",
        "state": state,
        "license_number": number,
    }


def test_name_key_ignores_case_punctuation_and_spacing():
    assert name_key("  M Davis & Sons,  Inc. ") == "M DAVIS AND SONS INC"
    assert name_key("M DAVIS AND SONS INC") == name_key("M Davis & Sons, Inc.")


def test_exact_name_matches_with_license_fields():
    licenses = [license_record("AMES CONSTRUCTION INC", category="NON-RESIDENT CONTRACTOR", valid_to="2026-12-31T00:00:00.000", state="PA")]
    rows = build_matches(["AMES CONSTRUCTION, INC"], licenses, today=TODAY)
    assert len(rows) == 1
    row = rows[0]
    assert row["contractor_name"] == "AMES CONSTRUCTION, INC"
    assert row["license_name"] == "AMES CONSTRUCTION INC"
    assert row["license_category"] == "NON-RESIDENT CONTRACTOR"
    assert row["license_valid_to"] == date(2026, 12, 31)
    assert row["license_state"] == "PA"
    assert row["license_match_basis"].startswith("exact name")


def test_suffix_only_difference_does_not_match():
    licenses = [license_record("ADVANCE LLC")]
    assert build_matches(["ADVANCE INC"], licenses, today=TODAY) == []


def test_trade_name_matches_when_business_name_differs():
    licenses = [license_record("JOHNNY SPENCE", trade="ALL-STAR PLUMBING")]
    rows = build_matches(["ALL-STAR PLUMBING"], licenses, today=TODAY)
    assert rows[0]["license_name"] == "JOHNNY SPENCE"


def test_placeholder_names_never_match():
    licenses = [license_record("HOMEOWNER PERMIT")]
    assert "HOMEOWNER PERMIT" in PLACEHOLDER_NAMES
    assert build_matches(["HOMEOWNER PERMIT"], licenses, today=TODAY) == []


def test_prefers_active_delaware_record_when_names_repeat():
    licenses = [
        license_record("ACME ROOFING LLC", valid_to="2026-01-31T00:00:00.000", state="DE", number="old"),
        license_record("ACME ROOFING LLC", category="NON-RESIDENT CONTRACTOR", valid_to="2028-06-30T00:00:00.000", state="PA", number="pa"),
        license_record("ACME ROOFING LLC", valid_to="2027-06-30T00:00:00.000", state="DE", number="de"),
    ]
    rows = build_matches(["ACME ROOFING LLC"], licenses, today=TODAY)
    assert rows[0]["license_number"] == "de"
    assert rows[0]["license_records"] == 3


def test_same_record_on_business_and_trade_name_is_counted_once():
    licenses = [license_record("SAME CO", trade="SAME CO")]
    rows = build_matches(["SAME CO"], licenses, today=TODAY)
    assert rows[0]["license_records"] == 1
