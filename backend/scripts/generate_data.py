"""
Relief-need dataset for ReliefTrace, grounded in real disaster events.

The need side is NOT synthetic. It is 15 real districts hit by the
2024 Assam floods and the 2025 Punjab floods, each with its reported
affected-population figure (distributed evenly within the state, since public
per-district figures aren't available), and per-resource quantities computed
from Sphere Handbook (2018) humanitarian minimum standards.

The delivery side is intentionally NOT generated here any more - deliveries
come only from live submissions through the dashboard.

Sources
  - Assam 2024 floods: ~400,000 people affected across 19 districts.
  - Punjab 2025 floods: ~3.54 million people affected across 13+ districts.
  Even split per state (400,000 / 19; 3,540,000 / 13) - exact per-district
  numbers are not public.

Sphere Handbook minimum standards applied per affected person:
  - Water:    15 litres / person / day
  - Food:     ~2.1 kg   / person / day  (basic ration)
  - Medical:  ~1 kit    / 500 people
  - Shelter:  ~1 tent   / 5 people
  - Clothing: 1 set     / person
Water and food are projected over DAYS_OF_NEED days of relief-phase supply.

Run (from backend/): python -m scripts.generate_data
Output: data/relief_requests.csv
"""

import math
import os
import random
import uuid
from datetime import date, timedelta

import pandas as pd

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "data"))

random.seed(42)

# --- real event parameters --------------------------------------------------
DAYS_OF_NEED = 30  # relief-phase planning window for water/food projections

ASSAM_TOTAL_AFFECTED = 400_000
ASSAM_AFFECTED_DISTRICTS = 19
PUNJAB_TOTAL_AFFECTED = 3_540_000
PUNJAB_AFFECTED_DISTRICTS = 13

ASSAM_PER_DISTRICT = round(ASSAM_TOTAL_AFFECTED / ASSAM_AFFECTED_DISTRICTS)      # ~21,053
PUNJAB_PER_DISTRICT = round(PUNJAB_TOTAL_AFFECTED / PUNJAB_AFFECTED_DISTRICTS)   # ~272,308

ASSAM_ONSET = date(2024, 7, 1)
PUNJAB_ONSET = date(2025, 9, 1)

# (district, state, affected_population, event onset date)
DISTRICTS = [
    ("Karimganj", "Assam", ASSAM_PER_DISTRICT, ASSAM_ONSET),
    ("Darrang", "Assam", ASSAM_PER_DISTRICT, ASSAM_ONSET),
    ("Tamulpur", "Assam", ASSAM_PER_DISTRICT, ASSAM_ONSET),
    ("Tarn Taran", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Hoshiarpur", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Kapurthala", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Rupnagar", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Moga", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Sangrur", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Barnala", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Patiala", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Gurdaspur", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Amritsar", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Ferozepur", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
    ("Fazilka", "Punjab", PUNJAB_PER_DISTRICT, PUNJAB_ONSET),
]

# Sphere-derived need per affected person, and the unit it's measured in.
RESOURCES = {
    "Water": ("litres", lambda p: p * 15 * DAYS_OF_NEED),
    "Food": ("kg", lambda p: round(p * 2.1 * DAYS_OF_NEED)),
    "Medical": ("kits", lambda p: math.ceil(p / 500)),
    "Shelter": ("tents", lambda p: math.ceil(p / 5)),
    "Clothing": ("sets", lambda p: p),
}

# Illustrative early-response reach - NOT from a source. Water/food tend to
# arrive first; medical/shelter lag. Multiplied by a per-district capacity
# factor so some districts show partial coverage and others near none. Tuned
# so the resulting unmet-% spread exercises all three urgency bands rather
# than showing a wall of "critical".
FULFILL_CEILING = {
    "Water": 0.85,
    "Food": 0.70,
    "Clothing": 0.55,
    "Shelter": 0.40,
    "Medical": 0.45,
}


def urgency_from_unmet_pct(pct: float) -> str:
    if pct >= 66:
        return "critical"
    if pct >= 33:
        return "medium"
    return "low"


def main() -> None:
    # per-district early-response capacity (0.4 = cut off, 1.35 = well reached)
    capacity = {name: random.uniform(0.35, 1.5) for name, *_ in DISTRICTS}

    rows = []
    for name, state, population, onset in DISTRICTS:
        zone = f"{name}, {state}"
        for resource, (unit, need_fn) in RESOURCES.items():
            needed = int(need_fn(population))
            frac = min(0.95, random.uniform(0.0, FULFILL_CEILING[resource]) * capacity[name])
            fulfilled = round(needed * frac)
            unmet_pct = 100 * (needed - fulfilled) / needed if needed else 0
            request_date = onset + timedelta(days=random.randint(0, 9))

            rows.append(
                {
                    "REQUEST_ID": str(uuid.uuid5(uuid.NAMESPACE_URL, f"relieftrace/{zone}/{resource}")),
                    "ZONE_NAME": zone,
                    "RESOURCE_TYPE": resource,
                    "QUANTITY_NEEDED": needed,
                    "QUANTITY_FULFILLED": fulfilled,
                    "URGENCY_LEVEL": urgency_from_unmet_pct(unmet_pct),
                    "REQUEST_DATE": request_date.strftime("%Y-%m-%d"),
                    "UNIT": unit,
                    "AFFECTED_POPULATION": population,
                }
            )

    df = pd.DataFrame(rows).sort_values(["ZONE_NAME", "RESOURCE_TYPE"]).reset_index(drop=True)

    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "relief_requests.csv")
    df.to_csv(path, index=False)

    total_pop = sum(p for _, _, p, _ in DISTRICTS)
    print(f"Wrote {len(df)} request rows ({len(DISTRICTS)} districts x {len(RESOURCES)} resources) to {path}")
    print(f"Total affected population represented: {total_pop:,}")
    print("Delivery side is NOT generated - it comes from live submissions only.")


if __name__ == "__main__":
    main()
