"""
Preflight CSV validation module for verifying structural and timestamp integrity.

Source of Truth:
- Timestamp candidates: `TIMESTAMP_CANDIDATES`
- Candidate datetime formats: `CANDIDATE_DATETIME_FORMATS`

Design Principles:
1. Robust Timestamp Parsing: Generic support for ISO8601, 12-hour AM/PM, month names,
   and trailing timezone strings (e.g. IST, UTC) without filename-specific hacks.
2. Non-Destructive: Validates datasets read-only without modifying inputs on disk.
3. Preserves Output Contract: Retains valid, timestamp_column, timestamp_valid,
   missing_timestamps, duplicate_timestamps, non_monotonic_timestamps,
   median_sampling_seconds, warnings, and errors.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl


TIMESTAMP_CANDIDATES: tuple[str, ...] = (
    "timestamp",
    "timestamp_utc",
    "datetime",
    "date_time",
    "time",
)

CANDIDATE_DATETIME_FORMATS: tuple[str, ...] = (
    "%d-%b-%y %I:%M:%S %p",    # 01-Jul-26 12:00:00 AM
    "%d-%b-%Y %I:%M:%S %p",    # 01-Jul-2026 12:00:00 AM
    "%d-%b-%y %H:%M:%S",       # 01-Jul-26 14:00:00
    "%d-%b-%Y %H:%M:%S",       # 01-Jul-2026 14:00:00
    "%b-%d-%y %I:%M:%S %p",    # Jul-01-26 12:00:00 AM
    "%b-%d-%Y %I:%M:%S %p",    # Jul-01-2026 12:00:00 AM
    "%Y-%m-%d %H:%M:%S",       # 2026-07-01 14:00:00
    "%Y-%m-%d %I:%M:%S %p",    # 2026-07-01 02:00:00 PM
    "%m/%d/%Y %I:%M:%S %p",    # 07/01/2026 02:00:00 PM
    "%d/%m/%Y %I:%M:%S %p",    # 01/07/2026 02:00:00 PM
    "%m/%d/%Y %H:%M:%S",       # 07/01/2026 14:00:00
    "%d/%m/%Y %H:%M:%S",       # 01/07/2026 14:00:00
    "%m/%d/%y %I:%M:%S %p",    # 07/01/26 02:00:00 PM
    "%d/%m/%y %I:%M:%S %p",    # 01/07/26 02:00:00 PM
    "%m/%d/%y %H:%M:%S",       # 07/01/26 14:00:00
    "%d/%m/%y %H:%M:%S",       # 01/07/26 14:00:00
    "%Y/%m/%d %H:%M:%S",       # 2026/07/01 14:00:00
    "%d-%m-%Y %H:%M:%S",       # 01-07-2026 14:00:00
    "%Y-%m-%d",                # 2026-07-01
    "%d-%b-%Y",                # 01-Jul-2026
    "%d-%b-%y",                # 01-Jul-26
)


def find_timestamp_column(columns: list[str]) -> str | None:
    """
    Find a likely timestamp column using generic column-name candidates.
    """
    normalized = {column.lower().strip(): column for column in columns}

    for candidate in TIMESTAMP_CANDIDATES:
        if candidate in normalized:
            return normalized[candidate]

    return None


def parse_timestamp_series(raw_series: pl.Series) -> pl.Series:
    """
    Robustly parse timestamp values into a polars.Datetime series.

    Handles:
    - Native Datetime / Date series
    - ISO8601 formats
    - 12-hour AM/PM formats with 2-digit / 4-digit years
    - 3-letter month abbreviations (e.g. 01-Jul-26)
    - Trailing timezone abbreviations (e.g. IST, UTC, EDT) and offsets (+05:30)
    """
    if raw_series.dtype in (pl.Datetime, pl.Date):
        return raw_series.cast(pl.Datetime)

    s_str = raw_series.cast(pl.Utf8).str.strip_chars()

    # 1. Try standard ISO8601 fast parser
    try:
        res = s_str.str.strptime(pl.Datetime, format=None, strict=False)
        if res.null_count() == 0 and res.len() > 0:
            return res
    except Exception:
        pass

    # 2. Clean trailing timezone abbreviations (e.g. " IST", " UTC") and offsets
    tz_cleaned = s_str.str.replace(r"\s+[A-Za-z]{2,5}$", "")
    tz_cleaned = tz_cleaned.str.replace(r"\s*[\+\-]\d{2}:?\d{2}$", "")

    for fmt in CANDIDATE_DATETIME_FORMATS:
        try:
            res = tz_cleaned.str.strptime(pl.Datetime, format=fmt, strict=False)
            if res.null_count() == 0 and res.len() > 0:
                return res
        except Exception:
            continue

    # 3. Fallback: try candidate formats on uncleaned string
    for fmt in CANDIDATE_DATETIME_FORMATS:
        try:
            res = s_str.str.strptime(pl.Datetime, format=fmt, strict=False)
            if res.null_count() == 0 and res.len() > 0:
                return res
        except Exception:
            continue

    # Final fallback to standard polars parser
    return s_str.str.strptime(pl.Datetime, format=None, strict=False)


def preflight_csv(file_path: str | Path) -> dict:
    """
    Validate the basic structural and timestamp health of a CSV.

    This function does not modify the input CSV.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    if path.suffix.lower() != ".csv":
        raise ValueError(f"Expected a CSV file, got: {path.suffix}")

    df = pl.read_csv(path)

    timestamp_column = find_timestamp_column(df.columns)

    report = {
        "file_name": path.name,
        "valid": True,
        "timestamp_column": timestamp_column,
        "timestamp_valid": False,
        "missing_timestamps": 0,
        "duplicate_timestamps": 0,
        "non_monotonic_timestamps": 0,
        "median_sampling_seconds": None,
        "warnings": [],
        "errors": [],
    }

    if timestamp_column is None:
        report["valid"] = False
        report["errors"].append("No timestamp column found.")
        return report

    raw_timestamp = df[timestamp_column]
    timestamps = parse_timestamp_series(raw_timestamp)

    report["missing_timestamps"] = timestamps.null_count()

    if report["missing_timestamps"] > 0:
        report["valid"] = False
        report["errors"].append(
            f"{report['missing_timestamps']} timestamp values could not be parsed."
        )

    valid_timestamps = timestamps.drop_nulls()

    if valid_timestamps.is_empty():
        report["valid"] = False
        report["errors"].append("No valid timestamps available.")
        return report

    report["timestamp_valid"] = True

    report["duplicate_timestamps"] = (
        valid_timestamps.len() - valid_timestamps.n_unique()
    )

    if report["duplicate_timestamps"] > 0:
        report["valid"] = False
        report["errors"].append(
            f"{report['duplicate_timestamps']} duplicate timestamps found."
        )

    differences = valid_timestamps.diff().dt.total_seconds()

    negative_steps = differences.filter(differences < 0)

    report["non_monotonic_timestamps"] = negative_steps.len()

    if report["non_monotonic_timestamps"] > 0:
        report["valid"] = False
        report["errors"].append(
            f"{report['non_monotonic_timestamps']} non-monotonic timestamp steps found."
        )

    positive_steps = differences.filter(differences > 0)

    if not positive_steps.is_empty():
        report["median_sampling_seconds"] = positive_steps.median()

    return report
