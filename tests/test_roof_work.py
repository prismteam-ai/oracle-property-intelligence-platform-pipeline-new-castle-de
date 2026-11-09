import duckdb

from query_layer import INSTALL_SQL

MACROS = INSTALL_SQL.split("CREATE OR REPLACE VIEW")[0]

CASES = [
    ("REPLACE ROOF SHINGLES", "BUILDING", True),
    ("REROOF ENTIRE HOUSE", "BUILDING", True),
    ("ROOFING JOB", "BUILDING", True),
    ("ROOFTOP HVAC UNIT REPLACEMENT", "HVAC", False),
    ("WATERPROOFING DECK", "BUILDING", False),
    ("PORCH ROOF OVER PATIO", "BUILDING", False),
    ("SOLAR PANELS MOUNTED ON ROOF", "BUILDING", False),
    ("TEAR OFF AND REPLACE ROOF", "BUILDING", True),
    ("PLUMBING STACK", "PLUMBING", False),
    ("PLUMBING RE-ROOF FLASHING", "PLUMBING", True),
]


def test_roof_work_classifies_known_comments():
    connection = duckdb.connect()
    connection.execute(MACROS)
    for comments, aptype, expected in CASES:
        got = connection.execute("SELECT roof_work(?, ?)", [comments, aptype]).fetchone()[0]
        assert got is expected, (comments, aptype, got)
