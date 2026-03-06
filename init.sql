-- init.sql
-- สร้างตาราง employees ตรงกับ template 45 columns + metadata

CREATE TABLE IF NOT EXISTS employees (
    id              SERIAL PRIMARY KEY,

    -- ข้อมูลส่วนบุคคล
    cid             VARCHAR(13) NOT NULL,
    first_name      VARCHAR(100),
    last_name       VARCHAR(100),
    department_id   VARCHAR(50),
    visit_date      DATE,

    -- Toxicology
    venous_blood_lead   NUMERIC(10,2),

    -- CBC
    wbc             NUMERIC(10,2),
    hb              NUMERIC(10,2),
    hct             NUMERIC(10,2),
    plt             NUMERIC(12,2),
    neutrophil      NUMERIC(10,2),
    lymphocyte      NUMERIC(10,2),
    monocyte        NUMERIC(10,2),
    eosinophil      NUMERIC(10,2),
    basophil        NUMERIC(10,2),

    -- Kidney
    creatinine      NUMERIC(10,2),

    -- Liver
    sgot_ast        NUMERIC(10,2),
    sgpt_alt        NUMERIC(10,2),
    alp             NUMERIC(10,2),
    tb              NUMERIC(10,2),
    db              NUMERIC(10,2),

    -- Metabolic
    uric_acid       NUMERIC(10,2),

    -- X-ray
    chest_xray      SMALLINT,         -- 1=ปกติ, 2=ผิดปกติ
    xray_comment    TEXT,
    profusion       NUMERIC(10,2),
    primary_lesion  VARCHAR(20),
    secondary_lesion VARCHAR(20),

    -- Cholinesterase
    rbc_che         NUMERIC(12,2),
    plasma_che_bche NUMERIC(12,2),

    -- EKG
    ekg             SMALLINT,         -- 1=ปกติ, 2=ผิดปกติ
    ekg_comment     TEXT,

    -- Vital signs
    bmi             NUMERIC(10,2),
    bp_systolic     NUMERIC(10,2),
    bp_diastolic    NUMERIC(10,2),
    pulse_rate      NUMERIC(10,2),

    -- Spirometry
    spirometry_fvc_percent  NUMERIC(10,2),
    spirometry_fev1_percent NUMERIC(10,2),
    spirometry_fvc          NUMERIC(10,2),
    spirometry_fev1         NUMERIC(10,2),
    spirometry_fev1_fvc     NUMERIC(10,2),
    spirometry_height       NUMERIC(10,2),

    -- Hearing
    hearing_ability SMALLINT,         -- 1=ปกติ, 2=ผิดปกติ
    hearing_comment TEXT,

    -- Vision
    far_vision_test SMALLINT,         -- 1=เหมาะสม, 2=อาจไม่เหมาะสม
    far_vision_comment TEXT,

    -- Metadata
    upload_id       INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(cid, visit_date)
);

CREATE INDEX IF NOT EXISTS idx_employees_cid ON employees(cid);
CREATE INDEX IF NOT EXISTS idx_employees_date ON employees(visit_date);
CREATE INDEX IF NOT EXISTS idx_employees_upload ON employees(upload_id);

-- Upload history log
CREATE TABLE IF NOT EXISTS upload_logs (
    id              SERIAL PRIMARY KEY,
    filename        VARCHAR(500) NOT NULL,
    file_type       VARCHAR(10),          -- csv / xlsx
    total_rows      INTEGER DEFAULT 0,
    success_rows    INTEGER DEFAULT 0,
    error_rows      INTEGER DEFAULT 0,
    errors          TEXT,                  -- JSON array of error messages
    status          VARCHAR(20) DEFAULT 'processing',  -- processing / completed / failed
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
