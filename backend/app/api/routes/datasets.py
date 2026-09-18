"""
Dataset management routes: upload, list, detail, columns, delete.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import UPLOAD_DIR, get_dataset_manager
from app.api.schemas import (
    CanonicalFieldSchema,
    CanonicalTelemetryResponse,
    ColumnInspectionSchema,
    ConversionRecordSchema,
    DatasetColumnsResponse,
    DatasetDeleteResponse,
    DatasetDetailResponse,
    DatasetListResponse,
    DatasetSummary,
    MappingConflictSchema,
    PreflightDetailsSchema,
    UnmappedChannelSchema,
)
from app.datasets.manager import DatasetManager

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post(
    "/upload",
    response_model=DatasetListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_datasets(
    files: list[UploadFile] = File(...),
    manager: DatasetManager = Depends(get_dataset_manager),
) -> DatasetListResponse:
    """
    Upload and register one or more CSV files.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided for upload.",
        )

    summaries: list[DatasetSummary] = []
    errors: list[str] = []

    for upload_file in files:
        filename = upload_file.filename or "unknown.csv"
        clean_name = Path(filename).name

        if not clean_name.lower().endswith(".csv"):
            errors.append(f"File '{clean_name}' is not a CSV.")
            continue

        # Save to an isolated upload subdirectory to preserve the exact original filename
        upload_subfolder = UPLOAD_DIR / uuid.uuid4().hex
        upload_subfolder.mkdir(parents=True, exist_ok=True)
        destination = upload_subfolder / clean_name

        try:
            with destination.open("wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
        except Exception as e:
            errors.append(f"Failed to save '{clean_name}': {e}")
            shutil.rmtree(upload_subfolder, ignore_errors=True)
            continue
        finally:
            upload_file.file.close()

        # Register through DatasetManager
        try:
            info = manager.add_csv(destination)
            # Ingest to partitioned Parquet historian so telemetry, graphs, and FDD are immediately ready
            try:
                manager.ingest_to_historian(
                    dataset_id=info.dataset_id,
                    default_equipment_id=info.equipment_id or info.dataset_id,
                )
            except Exception:
                pass

            summaries.append(
                DatasetSummary(
                    dataset_id=info.dataset_id,
                    file_name=info.file_name,
                    row_count=info.row_count,
                    column_count=info.column_count,
                    mapped_column_count=info.mapped_column_count,
                    unmapped_column_count=info.unmapped_column_count,
                    mapping_coverage=info.mapping_coverage,
                    conflict_count=info.conflict_count,
                    preflight_valid=info.preflight_valid,
                    equipment_id=info.equipment_id,
                    equipment_ids=list(info.equipment_ids),
                )
            )
        except Exception as e:
            errors.append(f"Failed to process '{clean_name}': {e}")
            shutil.rmtree(upload_subfolder, ignore_errors=True)

    if not summaries and errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload failed: {'; '.join(errors)}",
        )

    return DatasetListResponse(datasets=summaries)


@router.get("", response_model=DatasetListResponse)
def list_datasets(
    manager: DatasetManager = Depends(get_dataset_manager),
) -> DatasetListResponse:
    """
    List all registered datasets with summary metrics.
    """
    datasets = manager.list_datasets()
    summaries = [
        DatasetSummary(
            dataset_id=d.dataset_id,
            file_name=d.file_name,
            row_count=d.row_count,
            column_count=d.column_count,
            mapped_column_count=d.mapped_column_count,
            unmapped_column_count=d.unmapped_column_count,
            mapping_coverage=d.mapping_coverage,
            conflict_count=d.conflict_count,
            preflight_valid=d.preflight_valid,
            equipment_id=d.equipment_id,
            equipment_ids=list(d.equipment_ids),
        )
        for d in datasets
    ]
    return DatasetListResponse(datasets=summaries)


@router.get("/{dataset_id}", response_model=DatasetDetailResponse)
def get_dataset_details(
    dataset_id: str,
    manager: DatasetManager = Depends(get_dataset_manager),
) -> DatasetDetailResponse:
    """
    Retrieve complete inspection and mapping details for a specific dataset.
    """
    info = manager.get_dataset(dataset_id)
    result = manager.get_dataset_result(dataset_id)

    if info is None or result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset with ID '{dataset_id}' not found.",
        )

    pf = result.preflight_report
    preflight_schema = PreflightDetailsSchema(
        valid=pf.get("valid", False),
        timestamp_column=pf.get("timestamp_column"),
        timestamp_valid=pf.get("timestamp_valid", False),
        missing_timestamps=pf.get("missing_timestamps", 0),
        duplicate_timestamps=pf.get("duplicate_timestamps", 0),
        non_monotonic_timestamps=pf.get("non_monotonic_timestamps", 0),
        median_sampling_seconds=pf.get("median_sampling_seconds"),
        warnings=pf.get("warnings", []),
        errors=pf.get("errors", []),
    )

    column_schemas = [
        ColumnInspectionSchema(
            source_column=c.source_column,
            canonical_role=c.canonical_role,
            source_dtype=c.source_dtype,
            unit=c.unit,
            canonical_unit=c.canonical_unit,
            conversion_required=c.conversion_required,
            mapping_score=c.mapping_score,
            matched_pattern=c.matched_pattern,
            mapping_reason=c.mapping_reason,
            mapped=c.mapped,
            column_category=c.column_category,
        )
        for c in result.columns
    ]

    conflict_schemas = [
        MappingConflictSchema(
            role=conf.role,
            winner_column=conf.winner_column,
            winner_score=conf.winner_score,
            loser_column=conf.loser_column,
            loser_score=conf.loser_score,
            reason=conf.reason,
        )
        for conf in result.mapping_result.conflicts
    ]

    return DatasetDetailResponse(
        dataset_id=info.dataset_id,
        file_name=info.file_name,
        row_count=info.row_count,
        column_count=info.column_count,
        preflight=preflight_schema,
        mapped_column_count=info.mapped_column_count,
        unmapped_column_count=info.unmapped_column_count,
        mapping_coverage=info.mapping_coverage,
        conflict_count=info.conflict_count,
        columns=column_schemas,
        conflicts=conflict_schemas,
        unmapped_columns=result.mapping_result.unmapped_columns,
        equipment_id=info.equipment_id,
        equipment_ids=list(info.equipment_ids),
    )


@router.get("/{dataset_id}/columns", response_model=DatasetColumnsResponse)
def get_dataset_columns(
    dataset_id: str,
    manager: DatasetManager = Depends(get_dataset_manager),
) -> DatasetColumnsResponse:
    """
    Retrieve column inspection details for a dataset.
    """
    result = manager.get_dataset_result(dataset_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset with ID '{dataset_id}' not found.",
        )

    column_schemas = [
        ColumnInspectionSchema(
            source_column=c.source_column,
            canonical_role=c.canonical_role,
            source_dtype=c.source_dtype,
            unit=c.unit,
            canonical_unit=c.canonical_unit,
            conversion_required=c.conversion_required,
            mapping_score=c.mapping_score,
            matched_pattern=c.matched_pattern,
            mapping_reason=c.mapping_reason,
            mapped=c.mapped,
            column_category=c.column_category,
        )
        for c in result.columns
    ]

    return DatasetColumnsResponse(
        dataset_id=dataset_id,
        columns=column_schemas,
    )


@router.get("/{dataset_id}/canonical", response_model=CanonicalTelemetryResponse)
def get_dataset_canonical_telemetry(
    dataset_id: str,
    preview_limit: int = 20,
    manager: DatasetManager = Depends(get_dataset_manager),
) -> CanonicalTelemetryResponse:
    """
    Retrieve canonical telemetry transformation result, schema, and data preview for a dataset.
    """
    canonical_result = manager.get_canonical_telemetry(dataset_id)

    if canonical_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset with ID '{dataset_id}' not found.",
        )

    # Convert preview rows safely to python dicts (handling timestamps and floats)
    preview_df = canonical_result.canonical_df.head(preview_limit)
    preview_rows = preview_df.to_dicts()

    fields_schemas = [
        CanonicalFieldSchema(
            name=f.name,
            role=f.role,
            dtype=f.dtype,
            unit=f.unit,
            source_column=f.source_column,
            source_dtype=f.source_dtype,
            source_unit=f.source_unit,
            conversion_applied=f.conversion_applied,
            is_metadata=f.is_metadata,
        )
        for f in canonical_result.schema.fields
    ]

    unmapped_schemas = [
        UnmappedChannelSchema(
            source_column=u.source_column,
            source_dtype=u.source_dtype,
            unit=u.unit,
            column_category=u.column_category,
            reason=u.reason,
        )
        for u in canonical_result.schema.unmapped_channels
    ]

    conversion_schemas = [
        ConversionRecordSchema(
            source_column=c.source_column,
            canonical_role=c.canonical_role,
            source_unit=c.source_unit,
            canonical_unit=c.canonical_unit,
            formula=c.formula,
        )
        for c in canonical_result.conversions_applied
    ]

    return CanonicalTelemetryResponse(
        dataset_id=dataset_id,
        file_name=canonical_result.file_name or "unknown.csv",
        row_count=canonical_result.row_count,
        column_count=canonical_result.column_count,
        timestamp_column=canonical_result.timestamp_column,
        equipment_id_column=canonical_result.equipment_id_column,
        telemetry_roles=canonical_result.telemetry_roles,
        fields=fields_schemas,
        unmapped_channels=unmapped_schemas,
        conversions=conversion_schemas,
        preview_rows=preview_rows,
    )


@router.delete("/{dataset_id}", response_model=DatasetDeleteResponse)
def delete_dataset(
    dataset_id: str,
    manager: DatasetManager = Depends(get_dataset_manager),
) -> DatasetDeleteResponse:
    """
    Remove a dataset from the manager and clean up its historian partition.
    """
    # Clean up historian partition if present
    for b_dir in manager.historian.storage.root_dir.glob("building=*"):
        b_name = b_dir.name.split("=")[1]
        try:
            manager.historian.delete_equipment(b_name, dataset_id)
        except Exception:
            pass

    removed = manager.remove_dataset(dataset_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset with ID '{dataset_id}' not found.",
        )

    return DatasetDeleteResponse(
        dataset_id=dataset_id,
        removed=True,
    )
