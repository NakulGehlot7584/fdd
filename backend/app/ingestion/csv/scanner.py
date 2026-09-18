from pathlib import Path

import polars as pl


def scan_csv(file_path: str | Path) -> dict:
    """
    Inspect a CSV file and return basic structural information.

    The scanner does not perform semantic role mapping.
    Its responsibility is to discover what is inside the CSV.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    if path.suffix.lower() != ".csv":
        raise ValueError(f"Expected a CSV file, got: {path.suffix}")

    df = pl.read_csv(path)

    columns = []

    for column_name in df.columns:
        series = df[column_name]

        columns.append(
            {
                "name": column_name,
                "dtype": str(series.dtype),
                "null_count": series.null_count(),
                "sample_values": series.head(5).to_list(),
            }
        )

    return {
        "file_name": path.name,
        "file_path": str(path),
        "row_count": df.height,
        "column_count": df.width,
        "columns": columns,
    }