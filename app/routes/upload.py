"""
Upload Routes
=============
File upload endpoint: receives CSV/XLSX files, runs mapping pipeline,
and saves results to PostgreSQL.
"""

import hashlib
import io
import os
import sys
import traceback
import re
from datetime import datetime

import pandas as pd
from rapidfuzz import process, fuzz
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

# Add parent dir to path for mapping imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from mapping_config import NORMAL_ABNORMAL_MAP, CLINICAL_CATEGORICAL_IN_LONG

from app.database import get_db
from app.models import Employee, Hospital, LabMapping, SourceFile
from app.template import TEMPLATE_FIELDS

# Original uploaded files are kept here (D12: keep the source of every value)
STORAGE_DIR = os.environ.get("STORAGE_DIR", os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage", "uploads"))

router = APIRouter(prefix="/api", tags=["upload"])


# ---------------------------------------------------------------------------
# Column sets — derived from app/template.py (single source of truth)
# ---------------------------------------------------------------------------
TEMPLATE_TO_DB = {f.header: f.column for f in TEMPLATE_FIELDS}
NUMERIC_FIELDS = {f.column for f in TEMPLATE_FIELDS if f.kind == "numeric"}
CATEGORICAL_FIELDS = {f.column for f in TEMPLATE_FIELDS if f.kind == "categorical"}

def get_db_mapping(db: Session):
    """Fetch mapping config from database"""
    # Central dictionary only for now; hospital overrides come with the new pipeline
    records = db.query(LabMapping).filter(LabMapping.hospital_id.is_(None)).all()
    mapping_dict = {}
    for m in records:
        mapping_dict[m.source_name.lower().strip()] = {
            "col": m.target_column,
            "factor": float(m.unit_factor) if m.unit_factor else 1.0
        }
    return mapping_dict

def get_mapped_col(lab_name, mapping_dict):
    """Get template column and unit factor, using RapidFuzz if exact match fails"""
    if pd.isna(lab_name):
        return None, 1.0
        
    lname = str(lab_name).strip().lower()
    if lname in mapping_dict:
        return mapping_dict[lname]["col"], mapping_dict[lname]["factor"]
    
    # Fuzzy match fallback
    choices = list(mapping_dict.keys())
    if not choices:
        return None, 1.0
        
    best_match = process.extractOne(lname, choices, scorer=fuzz.token_sort_ratio)
    if best_match and best_match[1] >= 85:
        # print(f"  🧠 Fuzzy Matched: '{lname}' -> '{best_match[0]}' ({str(best_match[1])}%)")
        return mapping_dict[best_match[0]]["col"], mapping_dict[best_match[0]]["factor"]
    
    return None, 1.0


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


def convert_long_to_wide(df, mapping_dict):
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

    # Map lab names → template columns and unit factors
    mapped_cols = []
    unit_factors = []
    for x in df["lab_name"]:
        c, f = get_mapped_col(x, mapping_dict)
        mapped_cols.append(c)
        unit_factors.append(f)
        
    df["template_col"] = mapped_cols
    df["unit_factor"] = unit_factors

    # Keep only mapped rows
    mapped = df[df["template_col"].notna()].copy()
    unmapped = df[df["template_col"].isna()]
    if len(unmapped) > 0:
        unmapped_names = unmapped["lab_name"].unique().tolist()[:10]
        print(f"  ⚠️ Lab names ที่ map ไม่ได้: {unmapped_names}")

    extra_rows = []
    # Convert categorical and handle BP regex
    for idx, row in mapped.iterrows():
        tcol = row["template_col"]
        fac = row["unit_factor"]
        result_val = str(row["result"]).strip()
        
        # Regex check for BP e.g., "120/80"
        bp_match = re.match(r'^(\d+)\s*/\s*(\d+)$', result_val)
        if bp_match:
            mapped.at[idx, "template_col"] = "bp_systolic"
            mapped.at[idx, "result"] = bp_match.group(1)
            
            new_row = row.copy()
            new_row["template_col"] = "bp_diastolic"
            new_row["result"] = bp_match.group(2)
            extra_rows.append(new_row)
            continue
            
        if tcol in CLINICAL_CATEGORICAL_IN_LONG:
            converted = _convert_categorical(row["result"])
            if converted is not None:
                mapped.at[idx, "result"] = converted

    if extra_rows:
        mapped = pd.concat([mapped, pd.DataFrame(extra_rows)], ignore_index=True)

    # Clean numeric format (remove commas etc) and apply unit_factor
    def apply_clean_and_factor(row):
        val = _clean_numeric_string(row["result"])
        if isinstance(val, (int, float)) and row["template_col"] in NUMERIC_FIELDS:
            return float(val) * row["unit_factor"]
        return val

    mapped["result"] = mapped.apply(apply_clean_and_factor, axis=1)

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


def process_wide_dataframe(df, upload_id, db, mapping_dict=None, hospital_id=None):
    """
    Process a Wide format DataFrame → save to database.
    Supports UPSERT and dynamic DB mappings & fuzzy matching.
    """
    if mapping_dict is None:
        mapping_dict = {}
        
    success = 0
    updated = 0
    errors_list = []

    # Normalize column names for matching
    col_mapping = {}
    for orig_col in df.columns:
        orig = orig_col.strip().lower()
        found = False
        
        # 1. TEMPLATE_TO_DB Exact match
        for tpl_col, db_col in TEMPLATE_TO_DB.items():
            if orig == tpl_col.lower() or orig_col.strip() == tpl_col:
                col_mapping[orig_col] = {"db_col": db_col, "factor": 1.0}
                found = True
                break
                
        # 2. Match DB names directly
        if not found and orig in TEMPLATE_TO_DB.values():
             col_mapping[orig_col] = {"db_col": orig, "factor": 1.0}
             found = True

        # 3. Fuzzy map / DB Custom mapping map
        if not found and mapping_dict:
            col, fac = get_mapped_col(orig_col, mapping_dict)
            if col:
                # col might be template name (Thai) or db_col (English)
                db_col = TEMPLATE_TO_DB.get(col, col)
                if db_col in TEMPLATE_TO_DB.values():
                    col_mapping[orig_col] = {"db_col": db_col, "factor": fac}

    for idx, row in df.iterrows():
        try:
            emp_data = {"source_file_id": upload_id, "hospital_id": hospital_id}
            current_row_errors = []

            for orig_col, mapping_info in col_mapping.items():
                db_col = mapping_info["db_col"]
                factor = mapping_info["factor"]
                val = row.get(orig_col)

                # Handle NaN / None
                if pd.isna(val) or val == "":
                    continue

                # Regex catch for BP "120/80" in wide dataset (if under bp_systolic, bp_diastolic or generic numeric)
                s_val = str(val).strip()
                bp_match = re.match(r'^(\d+)\s*/\s*(\d+)$', s_val)
                if bp_match and db_col in ("bp_systolic", "bp_diastolic", "pulse_rate"):
                    # Apply to both if we detect BP syntax
                    emp_data["bp_systolic"] = float(bp_match.group(1))
                    emp_data["bp_diastolic"] = float(bp_match.group(2))
                    continue

                try:
                    # Handle date
                    if db_col == "visit_date":
                        val = _parse_date(val)
                    # Handle numeric
                    elif db_col in NUMERIC_FIELDS:
                        # Clean commas and N/A
                        s = s_val.replace(",", "")
                        if s.lower() in ("n/a", "na", "-", "--"):
                            val = None
                        else:
                            try:
                                val = float(s) * factor
                            except ValueError:
                                raise ValueError(f"ค่า '{val}' ไม่ใช่ตัวเลขที่ถูกต้อง")
                    # Handle categorical
                    elif db_col in CATEGORICAL_FIELDS:
                        val = _convert_categorical(val)
                        
                except ValueError as e:
                    current_row_errors.append(f"คอลัมน์ {orig_col} ({str(e)})")
                    continue

                if val is not None:
                    emp_data[db_col] = val

            # Skip rows without CID or Date, but track the error
            cid = emp_data.get("cid")
            if not cid:
                current_row_errors.append("ไม่พบข้อมูลเลขบัตรประชาชน (CID)")
            if not emp_data.get("visit_date"):
                current_row_errors.append("ไม่พบข้อมูลวันที่ตรวจ (Visit Date)")

            if len(current_row_errors) > 0:
                errors_list.append(f"Row {idx + 1}: " + " | ".join(current_row_errors))
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
                for key, v in emp_data.items():
                    if key != "cid" and key != "visit_date" and v is not None:
                        setattr(existing, key, v)
                updated += 1
            else:
                # Insert new record
                emp = Employee(**emp_data)
                db.add(emp)
                success += 1

        except Exception as e:
            db.rollback()
            errors_list.append(f"Row {idx + 1} (System Error): {str(e)}")

    db.commit()
    return success + updated, len(errors_list), errors_list


def _parse_date(val):
    """Parse date from various formats (supports both BE and CE years)."""
    if pd.isna(val) or str(val).strip() == "":
        return None
        
    if isinstance(val, datetime):
        return val.date()

    s = str(val).strip()
    if s.lower() in ("n/a", "na", "-", "--"):
        return None
        
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%y"]:
        try:
            dt = datetime.strptime(s, fmt)
            # If year > 2500, assume Buddhist Era
            if dt.year > 2500:
                dt = dt.replace(year=dt.year - 543)
            return dt.date()
        except ValueError:
            continue
    raise ValueError(f"รูปแบบวันที่ไม่ถูกต้อง ควรเป็น ปปปป-ดด-วว")


def _convert_categorical(val):
    """Convert normal/abnormal values to 1/2. Throws ValueError if unknown."""
    if pd.isna(val) or str(val).strip() == "":
        return None
        
    if isinstance(val, (int, float)):
        if val in (1, 2):
            return int(val)
        raise ValueError("ค่าตัวเลขต้องเป็น 1 (ปกติ) หรือ 2 (ผิดปกติ) เท่านั้น")

    normalized = str(val).strip().lower()
    if normalized in ("n/a", "na", "-", "--"):
        return None
        
    mapped = NORMAL_ABNORMAL_MAP.get(normalized)
    if mapped is None:
        raise ValueError(f"คำว่า ไม่รองรับ โปรดใช้คำว่า 'ปกติ/ผิดปกติ', 'normal/abnormal', '1/2' หรือปล่อยว่าง")
    return mapped


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

    # Keep the original file, then register it
    content = await file.read()
    sha = hashlib.sha256(content).hexdigest()
    os.makedirs(STORAGE_DIR, exist_ok=True)
    stored_path = os.path.join(STORAGE_DIR, f"{sha}.{ext}")
    with open(stored_path, "wb") as fh:
        fh.write(content)

    hospital = db.query(Hospital).filter(Hospital.code == "UNSPECIFIED").one()
    log = SourceFile(hospital_id=hospital.id, filename=filename, file_type=ext,
                     sha256=sha, stored_path=stored_path, status="processing",
                     stats={}, errors=[])
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        bytes_io = io.BytesIO(content)

        total_rows = 0
        total_success = 0
        total_errors = 0
        all_error_msgs = []
        formats_detected = []
        sheets_processed = []

        # Fetch DB mapping
        mapping_dict = get_db_mapping(db)

        if ext == "csv":
            # CSV: single sheet
            df = pd.read_csv(bytes_io)
            if not df.empty:
                total_rows = len(df)
                fmt = detect_file_format(df)
                formats_detected.append(fmt)
                if fmt == "long":
                    df = convert_long_to_wide(df, mapping_dict)
                s, e, msgs = process_wide_dataframe(df, log.id, db, mapping_dict, log.hospital_id)
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
                    df = convert_long_to_wide(df, mapping_dict)

                s, e, msgs = process_wide_dataframe(df, log.id, db, mapping_dict, log.hospital_id)
                total_success += s
                total_errors += e
                all_error_msgs.extend([f"[{sheet_name}] {m}" for m in msgs])
                sheets_processed.append(sheet_name)

        if total_rows == 0:
            log.status = "failed"
            log.errors = ["ไฟล์ไม่มีข้อมูล"]
            db.commit()
            return {"success": False, "error": "ไฟล์ไม่มีข้อมูล"}

        # Update log
        log.stats = {"total_rows": total_rows, "success_rows": total_success,
                     "error_rows": total_errors}
        log.errors = all_error_msgs[:50]
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
        db.rollback()
        log.status = "failed"
        log.errors = [str(e)]
        db.commit()
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
