from published import property_record, query_select, radius_search, source_summary


def test_summary_names_both_contractor_counts():
    summary = source_summary()
    coverage = summary["coverage"]
    assert summary["source"] == "published-json"
    assert "with_contractor_name" not in coverage
    assert coverage["with_any_permit_contractor"] > coverage["with_last_roof_contractor"] > 0
    assert "open-permit layer has no contractor field" in coverage["contractor_count_note"]


def test_radius_search_reads_published_leads():
    result = radius_search(39.739072, -75.539787, radius_miles=1, min_roof_age_years=15, limit=5)
    assert result["source"] == "published-json"
    assert result["returned"] == len(result["properties"])
    assert result["returned"] > 0
    assert result["properties"][0]["distance_miles"] <= 1


def test_property_record_includes_last_roof_contractor_when_present():
    found = query_select(
        "SELECT prclid, last_roof_contractor_name FROM leads WHERE last_roof_contractor_name IS NOT NULL LIMIT 1"
    )
    named = found["rows"][0]
    record = property_record(named["prclid"])
    assert record["property"]["last_roof_contractor_name"] == named["last_roof_contractor_name"]
