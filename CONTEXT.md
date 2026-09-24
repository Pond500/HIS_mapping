# HIS Mapping

Converts any hospital's health-check file into the department's fixed template, with AI-assisted mapping and mandatory human review for anything the system is not sure of.

## Language

**ระดับความเสี่ยง (risk level)**:
A per-person score for one round: (abnormal categorical values ÷ categorical values with a result that round) × 100%, bucketed 0%=ยอมรับได้, 1–25%=ต่ำ, 25–50%=ปานกลาง, 50–75%=สูง, 75–100%=สูงมาก. Only the `kind == "categorical"` fields count (Chest X-ray, EKG, ...), which alone carry a real ปกติ/ผิดปกติ verdict. Numeric fields' `lo`/`hi` in `template.py` is a *plausible-value* range for catching a unit or mapping mistake, not a clinical normal range — a value inside it can still be medically abnormal (e.g. blood lead within the plausible adult range but above a safe level), so it must never feed this score. A company's risk level is the average of this score across everyone with a categorical result that round. Computed from real results; not from the Walkthrough Survey.
_Avoid_: risk score, ผลตรวจผิดปกติ (that means one value, not the person's overall level), "normal range" for template.py's lo/hi (it isn't one)

**ประเภทความเสี่ยง (risk category)**:
The hazard a department is exposed to (Lead, Silicosis, Pesticides, Confined space, ...). Comes from the department's Walkthrough Survey answers, which are still a mockup (see [existing note in CLAUDE.md]) — not computed from results, unlike ระดับความเสี่ยง. A person's risk category is their department's.
_Avoid_: risk level (that's the severity score, a different axis)

**งานที่ต้องตรวจ (pending review panel)**:
Opens automatically right after a results upload finishes, but is also reachable any other time from a badge/count on the round dashboard — a person must never lose access to an open review just because they closed the panel or left the page. It is a view onto the same open `pending_reviews` rows the old dedicated `/reviews` page used; there is no separate queue. The person-detail modal (รายบุคคล tab) can also answer that person's open reviews inline, through the same decisions API — not a separate answering path.

**คอลัมน์ของบริษัท (company custom column)**:
A result column a company defines for itself, for a value real in the file but with no seat among the 40 standard template columns (e.g. urinalysis pH, eye-muscle phoria tests). Scoped per **company**, not per hospital like every other learned thing in this system (LabMapping, department codes, identity columns) — a genuine, deliberate exception, because a template columns's *meaning* is universal but a *company's own extra test panel* is not. Consistent with companies already being a shared national register (D20): if company A is served by two hospitals, the second hospital sees and reuses the first's custom columns for that company, the same way both already share the one register of that company's departments and employees. Has a name and a kind (numeric or text only — no categorical in v1). A numeric one's unit is recorded from whatever the first file wrote and never auto-converted (no known conversion table exists for a column nobody defined in advance); a later file naming a *different* unit for the same column is a new question for a human, not a silent mix of two units under one name. When answering a mapping review, a reviewer sees this company's existing custom columns to reuse, or can name a new one — never forced to retype an exact match to avoid a near-duplicate.
_Avoid_: extra result (the old, nameless catch-all in `extra_results`; the "keep it, no name" review answer is retired — a reviewer choosing "this is a real result with no seat in the form" is now always naming or picking a company column, never storing an anonymous blob again). This holds for the model too: in a company's file the Mapper agent's bare `__extra__` proposal is never auto-accepted and can't be "approved" as is (it only preselects the answer), and a hospital's older nameless `__extra__` mapping for a label comes back as a question until that company names a column for it. Files with no company (the evaluation cases) keep the old behaviour.

**ไฟล์ที่ส่งกรมควบคุมโรค (department submission file)**:
Two sheets are the fixed, agreed format (`employees`, `employee_checkups`, D23-ก) and never change shape company to company. A company's own custom columns go in a **third sheet**, appended to the same workbook, present only when that company has any — the department sees them, but the two-sheet contract regulators rely on stays exactly as agreed.

**ส่งรายงานผลตรวจ (submit)**:
Marks the round handed over to the department at that point in time. It does not close the round — more result files can still be uploaded afterward, same as today. A later change to stored results still withdraws any round-level approval (existing `revoke_if_approved`); submitting again after that is allowed, same open flow, not a new state machine.

**สถานะผลตรวจร่างกาย (checkup status)**:
Per person, per round: "ตรวจแล้ว" (has at least one stored result this round) or "ไม่พบข้อมูล" (none yet). There is currently no "ไม่มาตรวจ" (confirmed absent) state — deferred; a staff member cannot yet mark someone absent. Do not build UI or copy that implies a third state exists.

**หน้าภาพรวมบริษัท (company overview page)**:
The screen shown after picking a company and before any round's dashboard: the company's general info plus its Walkthrough Survey risk table per department. Lists the company's existing rounds (a company may have several, e.g. one per month or per checkup type) and lets the user pick one to open its dashboard, or create a new one via "+ เพิ่มรอบข้อมูล" — same round list/create behavior the app already has, just reached from here instead of a separate page.
_Avoid_: dashboard (that's the round-level screen, one level deeper)
