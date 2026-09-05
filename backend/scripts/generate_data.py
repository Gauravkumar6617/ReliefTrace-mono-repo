"""
Synthetic disaster-relief data for ReliefTrace: relief requests from zones and
the deliveries that (partially) fulfill them, spread across a 30-day disaster
timeline. Each zone gets a random "coverage factor" so some zones end up
badly under-served - that unevenness is what the zone-gaps insight surfaces.

Run (from backend/): python -m scripts.generate_data
Output: data/relief_requests.csv, data/relief_deliveries.csv
"""

import os
import random
import uuid
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "data"))

fake = Faker()
random.seed(42)
Faker.seed(42)

NUM_ZONES = 15
NUM_REQUESTS = 200
NUM_DELIVERIES = 150
TIMELINE_DAYS = 30

RESOURCE_TYPES = ["Food", "Water", "Shelter", "Medical", "Clothing"]
URGENCY_LEVELS = ["low", "medium", "critical"]
URGENCY_WEIGHTS = [0.30, 0.45, 0.25]

DONOR_ORGS = [
    "Red Cross Lucknow",
    "Doctors Without Borders",
    "World Central Kitchen",
    "UNICEF Field Unit",
    "Direct Relief",
    "Local Rotary Chapter",
    "CARE International",
    "Save the Children",
    "Habitat for Humanity",
    "Islamic Relief",
]

# roughly proportional to how much of a resource a single request/delivery
# tends to involve
QUANTITY_RANGES = {
    "Food": (50, 2000),        # meals / kg
    "Water": (100, 5000),      # liters
    "Shelter": (5, 200),       # tents / units
    "Medical": (10, 500),      # kits
    "Clothing": (20, 1000),    # units
}

DISASTER_START = datetime.now() - timedelta(days=TIMELINE_DAYS)


def make_zones(n: int) -> list[str]:
    names = set()
    while len(names) < n:
        names.add(f"{fake.city()} Zone")
    return sorted(names)


def random_date_in_timeline(start: datetime, days_elapsed_max: int) -> datetime:
    return start + timedelta(days=random.randint(0, days_elapsed_max))


def main():
    zones = make_zones(NUM_ZONES)
    # 0.15 = badly under-served, 0.95 = well covered - drives delivery odds/size below
    coverage_factor = {zone: random.uniform(0.15, 0.95) for zone in zones}

    requests = []
    for _ in range(NUM_REQUESTS):
        zone = random.choice(zones)
        resource_type = random.choice(RESOURCE_TYPES)
        lo, hi = QUANTITY_RANGES[resource_type]
        quantity_needed = random.randint(lo, hi)
        request_date = random_date_in_timeline(DISASTER_START, TIMELINE_DAYS - 1)

        # zones with low coverage skew toward higher urgency - the need doesn't
        # go away just because no one is responding to it
        cf = coverage_factor[zone]
        if cf < 0.35:
            urgency = random.choices(URGENCY_LEVELS, weights=[0.10, 0.30, 0.60])[0]
        elif cf < 0.65:
            urgency = random.choices(URGENCY_LEVELS, weights=URGENCY_WEIGHTS)[0]
        else:
            urgency = random.choices(URGENCY_LEVELS, weights=[0.45, 0.40, 0.15])[0]

        requests.append(
            {
                "REQUEST_ID": str(uuid.uuid4()),
                "ZONE_NAME": zone,
                "RESOURCE_TYPE": resource_type,
                "QUANTITY_NEEDED": quantity_needed,
                "QUANTITY_FULFILLED": 0,  # filled in after deliveries are generated
                "URGENCY_LEVEL": urgency,
                "REQUEST_DATE": request_date.strftime("%Y-%m-%d"),
                "_request_date_obj": request_date,
                "_coverage_factor": cf,
            }
        )

    # deliveries are drawn against requests weighted by each zone's coverage
    # factor, so well-covered zones get picked (and fulfilled generously)
    # far more often than under-served ones
    weights = [r["_coverage_factor"] for r in requests]
    deliveries = []
    fulfilled_totals: dict[str, float] = {r["REQUEST_ID"]: 0 for r in requests}

    for _ in range(NUM_DELIVERIES):
        req = random.choices(requests, weights=weights, k=1)[0]
        cf = req["_coverage_factor"]
        # a single delivery covers somewhere between 10% and 70% of the need,
        # scaled by the zone's coverage factor
        fraction = random.uniform(0.10, 0.70) * cf
        quantity_sent = max(1, round(req["QUANTITY_NEEDED"] * fraction))

        delivery_date = req["_request_date_obj"] + timedelta(days=random.randint(0, 5))
        delivery_date = min(delivery_date, DISASTER_START + timedelta(days=TIMELINE_DAYS - 1))

        deliveries.append(
            {
                "DELIVERY_ID": str(uuid.uuid4()),
                "REQUEST_ID": req["REQUEST_ID"],
                "ZONE_NAME": req["ZONE_NAME"],
                "DONOR_ORG": random.choice(DONOR_ORGS),
                "RESOURCE_TYPE": req["RESOURCE_TYPE"],
                "QUANTITY_SENT": quantity_sent,
                "DELIVERY_DATE": delivery_date.strftime("%Y-%m-%d"),
                "SOLANA_TX_SIG": "",  # populated later by solana_deliveries.py
                "SOURCE": "seed",
            }
        )
        fulfilled_totals[req["REQUEST_ID"]] += quantity_sent

    for req in requests:
        req["QUANTITY_FULFILLED"] = round(fulfilled_totals[req["REQUEST_ID"]])
        del req["_request_date_obj"]
        del req["_coverage_factor"]

    requests_df = pd.DataFrame(requests).sort_values("REQUEST_DATE").reset_index(drop=True)
    deliveries_df = pd.DataFrame(deliveries).sort_values("DELIVERY_DATE").reset_index(drop=True)

    os.makedirs(DATA_DIR, exist_ok=True)
    requests_path = os.path.join(DATA_DIR, "relief_requests.csv")
    deliveries_path = os.path.join(DATA_DIR, "relief_deliveries.csv")
    requests_df.to_csv(requests_path, index=False)
    deliveries_df.to_csv(deliveries_path, index=False)
    print(f"Wrote {len(requests_df)} rows to {requests_path}")
    print(f"Wrote {len(deliveries_df)} rows to {deliveries_path}")


if __name__ == "__main__":
    main()
