import pandas as pd
from app.database import SessionLocal, Employee
from app.routes.upload import detect_file_format, convert_long_to_wide, process_wide_dataframe, get_db_mapping

def test():
    db = SessionLocal()
    mapping_dict = get_db_mapping(db)
    
    # 1. Test BP Regex + Fuzzy Match in Long format
    data_long = {
        "cid": ["2222222222222", "2222222222222"],
        "visit_date": ["2026-04-07", "2026-04-07"],
        "lab_name": ["bp systolic", "w.b.c. count"], # 'bp systolic' exists exactly, 'w.b.c. count' should fuzzy match 'wbc count'
        "result": ["120/80", "5,500"]
    }
    df_long = pd.DataFrame(data_long)
    df_wide = convert_long_to_wide(df_long, mapping_dict)
    
    # Check if wide df has bp_systolic and bp_diastolic
    print("Wide Df columns:", df_wide.columns.tolist())
    print("Wide Df data:\n", df_wide.to_dict())
    
    # 2. Test saving to DB
    success, err, msgs = process_wide_dataframe(df_wide, 999, db, mapping_dict)
    print(f"DB Insert: Success={success}, Errors={err}")
    if err > 0:
        print("Error msgs:", msgs)
        
    emp = db.query(Employee).filter_by(cid="2222222222222").first()
    if emp:
        print(f"In DB -> SBP: {emp.bp_systolic}, DBP: {emp.bp_diastolic}, WBC: {emp.wbc}")
    else:
        print("Employee not found in DB")
        
    db.close()

if __name__ == "__main__":
    test()
