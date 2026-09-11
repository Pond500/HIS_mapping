import pandas as pd
from app.database import SessionLocal
from app.routes.upload import process_wide_dataframe, get_db_mapping

def test():
    db = SessionLocal()
    mapping_dict = get_db_mapping(db)
    
    # Create a Wide DataFrame with intentional errors
    data_wide = {
        "เลขบัตรประชาชน": ["111", "222", "333"],
        "วันที่ตรวจ (ปปปป-ดด-วว)": ["2026-04-07", "invalid_date", "2026-04-07"],
        "wbc": ["5000", "5,000", "I_am_a_string"],
        "chest_xray": [1, "ผิดปกติ", "รอผล"]
    }
    df = pd.DataFrame(data_wide)
    
    success, err, msgs = process_wide_dataframe(df, 888, db, mapping_dict)
    print(f"Success={success}, Errors={err}")
    for m in msgs:
        print(" ->", m)
        
    db.close()

if __name__ == "__main__":
    test()
