"""
Upload Routes
=============
File upload endpoint: receives CSV/XLSX files, runs mapping pipeline,
and saves results to PostgreSQL.
"""

import io
import json
import os
import sys
import traceback
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

# Add parent dir to path for mapping imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from mapping_config import LAB_NAME_TO_TEMPLATE, NORMAL_ABNORMAL_MAP, CLINICAL_CATEGORICAL_IN_LONG

from app.database import Employee, UploadLog, get_db

router = APIRouter(prefix="/api", tags=["upload"])


# ---------------------------------------------------------------------------
# Column mapping: template column → DB column
# ---------------------------------------------------------------------------
TEMPLATE_TO_DB = {
    "เลขบัตรประชาชน": "cid",
    "ชื่อ": "first_name",
    "นามสกุล": "last_name",
    "ID แผนก": "department_id",
    "วันที่ตรวจ (ปปปป-ดด-วว)": "visit_date",
    "venous_blood_lead": "venous_blood_lead",
    "wbc": "wbc",
    "hb": "hb",
    "hct": "hct",
    "plt": "plt",
    "neutrophil": "neutrophil",
    "lymphocyte": "lymphocyte",
    "monocyte": "monocyte",
    "eosinophil": "eosinophil",
    "basophil": "basophil",
    "creatinine": "creatinine",
    "sgot_ast": "sgot_ast",
    "sgpt_alt": "sgpt_alt",
    "alp": "alp",
    "tb": "tb",
    "db": "db",
    "uric_acid": "uric_acid",
    "chest_xray": "chest_xray",
    "xray_comment": "xray_comment",
    "profusion": "profusion",
    "primary_lesion": "primary_lesion",
    "secondary_lesion": "secondary_lesion",
    "rbc_che": "rbc_che",
    "plasma_che_bche": "plasma_che_bche",
    "ekg": "ekg",
    "ekg_comment": "ekg_comment",
    "bmi": "bmi",
    "bp_systolic": "bp_systolic",
    "bp_diastolic": "bp_diastolic",
    "pulse_rate": "pulse_rate",
    "spirometry_fvc_percent": "spirometry_fvc_percent",
    "spirometry_fev1_percent": "spirometry_fev1_percent",
    "spirometry_fvc": "spirometry_fvc",
    "spirometry_fev1": "spirometry_fev1",
    "spirometry_fev1_fvc": "spirometry_fev1_fvc",
    "spirometry_height": "spirometry_height",
    "hearing_ability": "hearing_ability",
    "hearing_comment": "hearing_comment",
    "far_vision_test": "far_vision_test",
    "far_vision_comment": "far_vision_comment",
}

# Fields that are numeric
NUMERIC_FIELDS = {
    "venous_blood_lead", "wbc", "hb", "hct", "plt",
    "neutrophil", "lymphocyte", "monocyte", "eosinophil", "basophil",
    "creatinine", "sgot_ast", "sgpt_alt", "alp", "tb", "db",
    "uric_acid", "profusion", "rbc_che", "plasma_che_bche",
    "bmi", "bp_systolic", "bp_diastolic", "pulse_rate",
    "spirometry_fvc_percent", "spirometry_fev1_percent",
    "spirometry_fvc", "spirometry_fev1", "spirometry_fev1_fvc",
    "spirometry_height",
}

# Fields that are categorical (1=normal, 2=abnormal)
CATEGORICAL_FIELDS = {"chest_xray", "ekg", "hearing_ability", "far_vision_test"}


def detect_file_format(df):
    """
    Detect if file is already in template (Wide) format
    or HIS (Long) format based on column names.
    """
    cols_lower = set(c.lower().strip() for c in df.columns)

    # Check for Long format markers
    long_markers = {"lab_name", "result", "labtest", "labresult"}
    if long_markers & cols_lower:
        return "long"

    # Check for Wide format (template columns)
    template_markers = {"wbc", "hb", "hct", "creatinine", "sgot_ast"}
    if len(template_markers & cols_lower) >= 3:
        return "wide"

    # Check Thai column names
    if "เลขบัตรประชาชน" in set(df.columns):
        return "wide"

    return "wide"  # Default to wide


def convert_long_to_wide(df):
    """
    Convert HIS Long/EAV format → Wide format.
    Expects columns: cid (or เลขบัตรประชาชน), lab_name, result, visit_date
    Now also handles categorical fields (X-ray/EKG/hearing/vision).
    """
    # Normalize column names
    col_map = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl in ("cid", "เลขบัตรประชาชน", "pid", "patient_id"):
            col_map[c] = "cid"
        elif cl in ("lab_name", "labtest", "test_name", "item_name"):
            col_map[c] = "lab_name"
        elif cl in ("result", "labresult", "lab_result", "value"):
            col_map[c] = "result"
        elif cl in ("visit_date", "date_serv", "vstdate", "วันที่ตรวจ"):
            col_map[c] = "visit_date"
        elif cl in ("fname", "first_name", "ชื่อ"):
            col_map[c] = "first_name"
        elif cl in ("lname", "last_name", "นามสกุล"):
            col_map[c] = "last_name"
        elif cl in ("department_id", "dept", "id แผนก"):
            col_map[c] = "department_id"

    df = df.rename(columns=col_map)

    if "lab_name" not in df.columns or "result" not in df.columns:
        raise ValueError("ไม่พบคอลัมน์ 'lab_name' และ 'result' ในไฟล์ Long format")

    if "cid" not in df.columns:
        raise ValueError("ไม่พบคอลัมน์ CID/เลขบัตรประชาชน ในไฟล์")

    # Map lab names → template columns
    df["template_col"] = df["lab_name"].apply(
        lambda x: LAB_NAME_TO_TEMPLATE.get(str(x).strip().lower())
    )

    # Keep only mapped rows
    mapped = df[df["template_col"].notna()].copy()
    unmapped = df[df["template_col"].isna()]
    if len(unmapped) > 0:
        unmapped_names = unmapped["lab_name"].unique().tolist()[:10]
        print(f"  ⚠️ Lab names ที่ map ไม่ได้: {unmapped_names}")

    # Convert categorical results (Normal/Abnormal → 1/2) for clinical fields
    for idx, row in mapped.iterrows():
        tcol = row["template_col"]
        if tcol in CLINICAL_CATEGORICAL_IN_LONG:
            result_val = row["result"]
            converted = _convert_categorical(result_val)
            if converted is not None:
                mapped.at[idx, "result"] = converted

    # Clean comma-separated numbers (e.g. "7,500" → "7500")
    mapped["result"] = mapped["result"].apply(_clean_numeric_string)

    # Pivot: group by cid+visit_date, spread template_col as columns
    group_cols = ["cid"]
    if "visit_date" in mapped.columns:
        group_cols.append("visit_date")

    # Keep demographic info
    demo_cols = {}
    for col in ["first_name", "last_name", "department_id"]:
        if col in mapped.columns:
            demo_cols[col] = mapped.groupby("cid")[col].first()

    pivoted = mapped.pivot_table(
        index=group_cols,
        columns="template_col",
        values="result",
        aggfunc="first"
    ).reset_index()

    # Flatten column names
    pivoted.columns = [c if isinstance(c, str) else c[0] for c in pivoted.columns]

    # Add demographics back
    for col, series in demo_cols.items():
        if col not in pivoted.columns:
            pivoted = pivoted.merge(series.reset_index(), on="cid", how="left")

    return pivoted


def _clean_numeric_string(val):
    """Clean numeric strings: remove commas, handle N/A."""
    if pd.isna(val):
        return val
    s = str(val).strip()
    if s.lower() in ("n/a", "na", "", "-", "--"):
        return None
    # Remove commas from numbers like "7,500"
    cleaned = s.replace(",", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return val  # Keep original if can't convert


def process_wide_dataframe(df, upload_id, db):
    """
    Process a Wide format DataFrame → save to database.
    Supports UPSERT: if CID+visit_date already exists, update the record.
    Returns (success_count, error_count, error_messages)
    """
    success = 0
    updated = 0
    errors_list = []

    # Normalize column names for matching
    col_mapping = {}
    for orig_col in df.columns:
        for tpl_col, db_col in TEMPLATE_TO_DB.items():
            if orig_col.strip().lower() == tpl_col.lower() or orig_col.strip() == tpl_col:
                col_mapping[orig_col] = db_col
                break
        # Also try direct DB column match
        if orig_col not in col_mapping:
            if orig_col.strip().lower() in TEMPLATE_TO_DB.values():
                col_mapping[orig_col] = orig_col.strip().lower()

    for idx, row in df.iterrows():
        try:
            emp_data = {"upload_id": upload_id}

            for orig_col, db_col in col_mapping.items():
                val = row.get(orig_col)

                # Handle NaN / None
                if pd.isna(val):
                    continue

                # Handle date
                if db_col == "visit_date":
                    val = _parse_date(val)
                # Handle numeric
                elif db_col in NUMERIC_FIELDS:
                    try:
                        # Clean commas and N/A
                        s = str(val).strip().replace(",", "")
                        if s.lower() in ("n/a", "na", "", "-", "--"):
                            val = None
                        else:
                            val = float(s)
                    except (ValueError, TypeError):
                        val = None
                # Handle categorical
                elif db_col in CATEGORICAL_FIELDS:
                    val = _convert_categorical(val)

                if val is not None:
                    emp_data[db_col] = val

            # Skip rows without CID
            cid = emp_data.get("cid")
            if not cid:
                continue

            # Ensure CID is string
            emp_data["cid"] = str(int(float(cid))) if isinstance(cid, float) else str(cid)

            # UPSERT: check if record already exists
            visit_date = emp_data.get("visit_date")
            existing = db.query(Employee).filter(
                Employee.cid == emp_data["cid"],
                Employee.visit_date == visit_date
            ).first()

            if existing:
                # Update existing record
                for key, val in emp_data.items():
                    if key != "cid" and key != "visit_date" and val is not None:
                        setattr(existing, key, val)
                updated += 1
            else:
                # Insert new record
                emp = Employee(**emp_data)
                db.add(emp)
                success += 1

        except Exception as e:
            db.rollback()
            errors_list.append(f"Row {idx + 1}: {str(e)}")

    db.commit()
    return success + updated, len(errors_list), errors_list


def _parse_date(val):
    """Parse date from various formats (supports both BE and CE years)."""
    if isinstance(val, datetime):
        return val.date()

    s = str(val).strip()
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"]:
        try:
            dt = datetime.strptime(s, fmt)
            # If year > 2500, assume Buddhist Era
            if dt.year > 2500:
                dt = dt.replace(year=dt.year - 543)
            return dt.date()
        except ValueError:
            continue
    return None


def _convert_categorical(val):
    """Convert normal/abnormal values to 1/2."""
    if isinstance(val, (int, float)):
        return int(val) if val in (1, 2) else None

    normalized = str(val).strip().lower()
    return NORMAL_ABNORMAL_MAP.get(normalized)


# ---------------------------------------------------------------------------
# API Endpoint
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload HIS file (CSV or XLSX) → map → save to database.
    Supports both Wide (template) and Long (HIS/EAV) formats.
    For XLSX: processes ALL sheets automatically and merges results.
    """
    # Validate file type
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ("csv", "xlsx", "xls"):
        return {"success": False, "error": "รองรับเฉพาะไฟล์ .csv และ .xlsx เท่านั้น"}

    # Create upload log
    log = UploadLog(filename=filename, file_type=ext, status="processing")
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        # Read file content
        content = await file.read()
        bytes_io = io.BytesIO(content)

        total_rows = 0
        total_success = 0
        total_errors = 0
        all_error_msgs = []
        formats_detected = []
        sheets_processed = []

        if ext == "csv":
            # CSV: single sheet
            df = pd.read_csv(bytes_io)
            if not df.empty:
                total_rows = len(df)
                fmt = detect_file_format(df)
                formats_detected.append(fmt)
                if fmt == "long":
                    df = convert_long_to_wide(df)
                s, e, msgs = process_wide_dataframe(df, log.id, db)
                total_success += s
                total_errors += e
                all_error_msgs.extend(msgs)
                sheets_processed.append("CSV")
        else:
            # XLSX: process ALL sheets
            xlsx = pd.ExcelFile(bytes_io)
            print(f"  📄 XLSX has {len(xlsx.sheet_names)} sheets: {xlsx.sheet_names}")

            for sheet_name in xlsx.sheet_names:
                df = xlsx.parse(sheet_name)
                if df.empty:
                    print(f"  ⏭️ Sheet '{sheet_name}' is empty, skipping")
                    continue

                total_rows += len(df)
                fmt = detect_file_format(df)
                formats_detected.append(f"{sheet_name}({fmt})")
                print(f"  📋 Sheet '{sheet_name}': {len(df)} rows, format={fmt}")

                if fmt == "long":
                    df = convert_long_to_wide(df)

                s, e, msgs = process_wide_dataframe(df, log.id, db)
                total_success += s
                total_errors += e
                all_error_msgs.extend([f"[{sheet_name}] {m}" for m in msgs])
                sheets_processed.append(sheet_name)

        if total_rows == 0:
            log.status = "failed"
            log.errors = json.dumps(["ไฟล์ไม่มีข้อมูล"], ensure_ascii=False)
            db.commit()
            return {"success": False, "error": "ไฟล์ไม่มีข้อมูล"}

        # Update log
        log.total_rows = total_rows
        log.success_rows = total_success
        log.error_rows = total_errors
        log.errors = json.dumps(all_error_msgs[:50], ensure_ascii=False) if all_error_msgs else None
        log.status = "completed"
        db.commit()

        return {
            "success": True,
            "upload_id": log.id,
            "format_detected": ", ".join(formats_detected),
            "total_rows": total_rows,
            "success_rows": total_success,
            "error_rows": total_errors,
            "sheets_processed": sheets_processed,
            "errors": all_error_msgs[:10],
        }

    except Exception as e:
        log.status = "failed"
        log.errors = json.dumps([str(e)], ensure_ascii=False)
        db.commit()
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
