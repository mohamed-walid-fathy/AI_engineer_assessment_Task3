"""
data_layer.py
Loads the raw operations spreadsheet, applies a small set of documented
cleaning rules, and derives the timing fields the rest of the app needs.

Nothing in this file invents numbers. Every rule here is a business
assumption made explicit — see ASSUMPTIONS below. If the COO's real
definition of "late" or "outlier" differs, change it HERE, once, and
every tool picks up the new definition automatically.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# ASSUMPTIONS — read this before trusting any number the app produces.
# ---------------------------------------------------------------------------
ASSUMPTIONS = {
    "late_definition": (
        "An order is 'late' if its delivery duration (DeliveryTime - CreatedDate) "
        "exceeds the 90th percentile duration for its OWN branch, computed over "
        "the branch's own history in the dataset. This is a relative, "
        "self-referential threshold, not a fixed SLA in minutes, because no SLA "
        "was provided in the data. If the business has a real SLA (e.g. '45 "
        "minutes'), replace LATE_THRESHOLD_FN with that constant."
    ),
    "outlier_cap": (
        "Delivery/dispatch/pickup durations longer than 24 hours (1440 min) are "
        "treated as data/timestamp errors, not real operational events, and are "
        "excluded from duration statistics (but the order itself is kept for "
        "counts/ratings)."
    ),
    "negative_durations": (
        "~21% of PickingUpTime values fall before AddedToTripTime, and ~5% of "
        "AddedToTripTime values fall before CreatedDate. These are almost "
        "certainly clock-sync or system-logging artifacts. Rows with a negative "
        "dispatch or pickup lag are excluded from lag statistics only "
        "(not from order counts or ratings)."
    ),
    "min_volume_gate": (
        "Any branch/rider/zone comparison suppresses entities with fewer than "
        "MIN_VOLUME orders in the relevant window. Branch order counts in this "
        "dataset range from 1 to 1,924 — small-sample entities are hidden from "
        "rankings rather than shown with misleadingly precise stats."
    ),
    "reference_date": (
        "'Last month' / 'this month' are resolved against the MAX date actually "
        "present in the data (2026-07-12), not against today's real-world date, "
        "and the most recent calendar month is partial. This is stated in every "
        "answer that uses a time window."
    ),
    "sampling_caveat": (
        "Monthly order volumes in this dataset are highly uneven (843 orders in "
        "Jul 2025 vs 9,953 in Apr 2026) and April 2025 has zero rows. This looks "
        "like a sample extract, not a complete transaction log. Month-over-month "
        "comparisons may reflect sampling differences, not real operational "
        "change. This app flags month-over-month comparisons with this caveat "
        "every time it makes one — it cannot rule the possibility out from the "
        "data alone."
    ),
    "zero_rating": (
        "0.0 is treated as a real (very negative) rating, not a null/'not rated' "
        "code, because the dictionary does not say otherwise. This should be "
        "confirmed with whoever owns the rating system before this goes to "
        "production."
    ),
}

MIN_VOLUME = 20            # minimum orders to appear in a ranking
OUTLIER_CAP_MINUTES = 24 * 60


def _minutes(delta: pd.Series) -> pd.Series:
    return delta.dt.total_seconds() / 60.0


def load_raw(xlsx_path: str) -> pd.DataFrame:
    df = pd.read_excel(xlsx_path, sheet_name="Data")
    return df


def clean_and_derive(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # --- derived timing fields --------------------------------------------
    df["delivery_min"] = _minutes(df["DeliveryTime"] - df["CreatedDate"])
    df["dispatch_min"] = _minutes(df["AddedToTripTime"] - df["CreatedDate"])
    df["pickup_min"] = _minutes(df["PickingUpTime"] - df["AddedToTripTime"])

    # --- quality flags (kept as columns, not silently dropped) -------------
    df["flag_negative_dispatch"] = df["dispatch_min"] < 0
    df["flag_negative_pickup"] = df["pickup_min"] < 0
    df["flag_delivery_outlier"] = df["delivery_min"] > OUTLIER_CAP_MINUTES
    df["flag_dispatch_outlier"] = df["dispatch_min"].abs() > OUTLIER_CAP_MINUTES
    df["flag_pickup_outlier"] = df["pickup_min"].abs() > OUTLIER_CAP_MINUTES

    # usable-for-stats versions: NaN out the values we don't trust,
    # but never drop the row (counts/ratings/comments stay valid)
    df["delivery_min_clean"] = df["delivery_min"].where(~df["flag_delivery_outlier"])
    df["dispatch_min_clean"] = df["dispatch_min"].where(
        (~df["flag_negative_dispatch"]) & (~df["flag_dispatch_outlier"])
    )
    df["pickup_min_clean"] = df["pickup_min"].where(
        (~df["flag_negative_pickup"]) & (~df["flag_pickup_outlier"])
    )

    df["order_month"] = df["CreatedDate"].dt.to_period("M")
    df["order_hour"] = df["CreatedDate"].dt.hour
    df["order_dow"] = df["CreatedDate"].dt.day_name()
    df["has_comment"] = df["CustomerComment"].notna()

    # crude language tag for comments — good enough to bucket EN vs AR,
    # not a real language-ID model
    def _lang(s):
        if not isinstance(s, str) or not s.strip():
            return None
        arabic_chars = sum("\u0600" <= ch <= "\u06FF" for ch in s)
        return "ar" if arabic_chars > len(s) * 0.2 else "en"

    df["comment_lang"] = df["CustomerComment"].map(_lang)

    return df


def branch_late_thresholds(df: pd.DataFrame) -> pd.Series:
    """
    Per-branch 90th-percentile delivery duration, computed on cleaned
    (non-outlier) durations, using each branch's full history in the data.
    Returns a Series indexed by BranchID.
    """
    return df.groupby("BranchID")["delivery_min_clean"].quantile(0.90)


def flag_late_orders(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    thresholds = branch_late_thresholds(df)
    df["branch_p90_min"] = df["BranchID"].map(thresholds)
    df["is_late"] = df["delivery_min_clean"] > df["branch_p90_min"]
    return df


def load_clean(xlsx_path: str) -> pd.DataFrame:
    raw = load_raw(xlsx_path)
    df = clean_and_derive(raw)
    df = flag_late_orders(df)
    return df


def data_reference_date(df: pd.DataFrame) -> pd.Timestamp:
    """The 'today' the app reasons from: the latest date actually in the data."""
    return df["CreatedDate"].max()


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/operations_data_anonymized.xlsx"
    df = load_clean(path)
    print(f"Loaded {len(df):,} rows, {df['BranchID'].nunique()} branches, "
          f"{df['RiderID'].nunique()} riders")
    print(f"Reference date (max CreatedDate in data): {data_reference_date(df)}")
    print(f"Late orders flagged: {df['is_late'].sum():,} "
          f"({df['is_late'].mean()*100:.1f}%)")
    out = Path(__file__).resolve().parent.parent / "data" / "clean.parquet"
    df.to_parquet(out)
    print(f"Wrote {out}")
