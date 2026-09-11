import pandas as pd
from app.database import SessionLocal
from app.routes.upload import detect_file_format, convert_long_to_wide, process_wide_dataframe, get_db_mapping

def test():
    db = SessionLocal()
    mapping_dict = get_db_mapping(db)
    
    # 1. Test BP Regex + Fuzzy Match in Long format
    data_long = {
        "cid": ["1111111111111"],
        "visit_date": ["2026-04-07"],
        "lab_name": ["Vitals: BP"], # Unregistered lab name, "bp_systolic" is "bp_systolic" in map, will fuzzy match? 
        # Actually in config we have "systolic bp", "bp systolic", "bp" is not there, maybe? "bp systolic" will just go to bp_systolic.
        # Let's say we pass "blood presure", maybe rapidfuzz hits nothing. Let's use "bp systolic" which maps exactly, 
        # but with a combined value "120/80"
        "result": ["120/80"]
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
        
    db.close()

if __name__ == "__main__":
    test()
