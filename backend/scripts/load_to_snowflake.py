"""
Pushes relief_requests.csv into Snowflake: PUT to an internal stage, then
TRUNCATE + COPY INTO (full refresh). Run after generate_data.py.

Only RELIEF_REQUESTS is loaded. RELIEF_DELIVERIES is deliberately left alone -
those rows come from live dashboard submissions, not from a seed file.

Assumes schema.sql / the migrations have been run in Snowsight already.

Run (from backend/): python -m scripts.load_to_snowflake
"""

import os
import sys

from dotenv import load_dotenv

from app.db import get_cursor

load_dotenv()

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "data"))
REQUIRED_ENV_VARS = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER"]

TABLES = {
    "RELIEF_REQUESTS": {
        "csv": os.path.join(DATA_DIR, "relief_requests.csv"),
        "stage": "RELIEF_REQUESTS_STAGE",
        "format": "RELIEF_REQUESTS_CSV_FORMAT",
        "columns": [
            "REQUEST_ID",
            "ZONE_NAME",
            "RESOURCE_TYPE",
            "QUANTITY_NEEDED",
            "QUANTITY_FULFILLED",
            "URGENCY_LEVEL",
            "REQUEST_DATE",
            "UNIT",
            "AFFECTED_POPULATION",
        ],
    },
}


def load_table(cur, table_name: str, cfg: dict) -> None:
    if not os.path.exists(cfg["csv"]):
        print(f"{cfg['csv']} not found. Run: python -m scripts.generate_data")
        sys.exit(1)

    cur.execute(
        f"""
        CREATE FILE FORMAT IF NOT EXISTS {cfg['format']}
            TYPE = 'CSV'
            FIELD_DELIMITER = ','
            SKIP_HEADER = 1
            FIELD_OPTIONALLY_ENCLOSED_BY = '"'
            NULL_IF = ('')
            EMPTY_FIELD_AS_NULL = TRUE
        """
    )
    cur.execute(f"CREATE STAGE IF NOT EXISTS {cfg['stage']}")

    csv_abspath = os.path.abspath(cfg["csv"])
    cur.execute(f"PUT file://{csv_abspath} @{cfg['stage']} OVERWRITE = TRUE AUTO_COMPRESS = TRUE")

    # dev convenience: full refresh each run so re-running after regenerating
    # the CSVs doesn't duplicate rows
    cur.execute(f"TRUNCATE TABLE {table_name}")

    filename = os.path.basename(cfg["csv"])
    columns = ", ".join(cfg["columns"])
    copy_result = cur.execute(
        f"""
        COPY INTO {table_name} ({columns})
        FROM @{cfg['stage']}/{filename}.gz
        FILE_FORMAT = (FORMAT_NAME = '{cfg['format']}')
        ON_ERROR = 'ABORT_STATEMENT'
        """
    ).fetchall()

    print(f"COPY INTO {table_name} result:")
    for row in copy_result:
        print(row)


def main():
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}. Check your .env.")
        sys.exit(1)

    with get_cursor() as cur:
        for table_name, cfg in TABLES.items():
            load_table(cur, table_name, cfg)
        cur.connection.commit()

    print("Load complete.")


if __name__ == "__main__":
    main()
