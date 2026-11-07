import duckdb

import load_sources
import query_layer


def test_roof_age_uses_a_closed_permit_and_not_an_open_one(tmp_path):
    path = tmp_path / "roof.duckdb"
    previous = query_layer.DB_PATH
    query_layer.DB_PATH = path
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE county_record (source VARCHAR, object_id BIGINT, prclid VARCHAR, attrs JSON, fetched_at TIMESTAMP);
        CREATE TABLE parcel_seed (
          prclid VARCHAR, prclkey BIGINT, parcel_url VARCHAR, address VARCHAR, city VARCHAR, state VARCHAR,
          zip VARCHAR, owner_name VARCHAR, owner_address VARCHAR, owner_city VARCHAR, owner_state VARCHAR,
          owner_zip VARCHAR, property_class VARCHAR, subdivision VARCHAR, lot_acres DOUBLE, source_edited_at TIMESTAMP
        );
        CREATE TABLE parcel_point (prclid VARCHAR, lon DOUBLE, lat DOUBLE);
        INSERT INTO parcel_seed VALUES
          ('1', 1, 'url', '1 MAIN', 'WILMINGTON', 'DE', '19801', 'OWNER', '1 MAIN', 'WILMINGTON', 'PA', '19801', 'R', 'SUB', 1, NULL);
        INSERT INTO parcel_point VALUES ('1', -75.5, 39.7);
        INSERT INTO county_record VALUES
          ('structures', 1, '1', '{"YEAR_BUILT": 0, "ROOF_MATERIAL": "AP"}', now()),
          ('permits_open', 2, '1', '{"APNO": "open", "APTYPE": "BUILDING", "COMMENTS": "RE-ROOF", "ISSDTTM": 1762000000000}', now()),
          ('permits_released', 3, '1', '{"APNO": "closed", "APTYPE": "BUILDING", "COMMENTS": "RE-ROOF", "ISSDTTM": 1262304000000, "CONTNAME": "ACME ROOFING"}', now());
        """
    )
    connection.close()
    connection = query_layer.connect()
    summary = load_sources.assemble(connection, run_id="test")
    connection.close()
    assert summary["parcels"] == 1
    query_layer.install()
    connection = query_layer.connect(read_only=True)
    row = connection.execute(
        "SELECT roof_age_basis, roof_age_years, year_built, last_roof_contractor_name, owner_out_of_area FROM lead_property"
    ).fetchone()
    connection.close()
    basis, age, year_built, contractor, out_of_area = row
    query_layer.DB_PATH = previous
    assert year_built is None
    assert basis == "latest_closed_roof_permit"
    assert age > 10
    assert contractor == "ACME ROOFING"
    assert out_of_area is True
