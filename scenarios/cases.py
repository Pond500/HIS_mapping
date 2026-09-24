"""The scenario cases. Each is one situation the system can be in, and what must happen."""

from scenarios.harness import bad_cid, cid, csv_bytes, num, xlsx_bytes

CASES = []


def case(id_, title, world=True):
    def deco(fn):
        CASES.append({"id": id_, "title": title, "fn": fn, "world": world, "doc": (fn.__doc__ or "").strip()})
        return fn
    return deco


@case("R01", "ทะเบียนสะอาด เข้าครบ ไม่มีคำถาม")
def r01(s):
    """อัปทะเบียน 5 คน หัวคอลัมน์ที่ระบบรู้จัก → เพิ่ม 5 คน ไม่มีคำถาม ไฟล์เสร็จ"""
    out = s.default_people()
    assert s.h.scalar("select count(*) from employees") == 5
    assert s.file(1)["status"] == "completed", s.file(1)["status"]


HEAD = ["เลขบัตรประชาชน", "ชื่อ", "นามสกุล", "ชื่อแผนก"]
HEAD_FULL = HEAD + ["เพศ", "ปีเกิด", "ตำแหน่ง", "อายุงาน"]


def person(n, dept="ผลิต", **extra):
    return [cid(n), f"ชื่อ{n}", f"สกุล{n}", dept]


def employee(s, n):
    return s.h.sql("select * from employees where cid=:c order by id", c=cid(n))


# ═══════════════════════════════════════════════════════════════════════════
# R — นำเข้าทะเบียนพนักงาน
# ═══════════════════════════════════════════════════════════════════════════

@case("R02", "ทะเบียนไฟล์เดิมอัปซ้ำ ไม่เปลี่ยนอะไร")
def r02(s):
    """อัปไฟล์ทะเบียนเดิมสองครั้ง → ครั้งที่สอง 'มีอยู่แล้ว 5' เพิ่ม 0 ไม่มีคำถาม"""
    s.default_people()
    out = s.registry([HEAD] + [person(n) for n in range(1, 6)][:4] + [person(5, "คลัง")])
    assert (out["added"], out["unchanged"], out["reviews"]) == (0, 5, 0), out
    assert s.h.scalar("select count(*) from employees") == 5


@case("R03", "หัวคอลัมน์แปลก ตอบเป็นช่องของทะเบียน ระบบจำ")
def r03(s):
    """ไฟล์มีคอลัมน์ 'หน้าที่รับผิดชอบ' → ถาม 1 ข้อ ตอบ 'ตำแหน่งงาน' → คนเข้าครบ มีตำแหน่ง
    อัปไฟล์รูปแบบเดิมอีกครั้ง → ไม่ถามซ้ำ"""
    head = HEAD + ["หน้าที่รับผิดชอบ"]
    rows = [head] + [person(n) + ["ช่างกลึง"] for n in (1, 2)]
    out = s.registry(rows)
    assert s.kinds(1) == ["mapping"], s.kinds(1)
    assert out["added"] == 2                       # the rest of the row still lands
    q = s.reviews(1)[0]
    s.decide(1, [{"review_id": q["id"], "action": "set", "target": "position"}])
    assert s.file(1)["status"] == "completed"
    assert employee(s, 1)[0]["position"] == "ช่างกลึง"
    out2 = s.registry(rows, name="อีกครั้ง.csv")
    assert out2["reviews"] == 0, out2              # learned, not asked again
    assert s.reviews(1, "approved")[0]["decision"]["action"] == "set"


@case("R04", "คอลัมน์ที่ไม่ใช่ข้อมูลทะเบียน ตอบ 'ไม่ใช่' แล้วไม่ถามอีก")
def r04(s):
    """คอลัมน์ 'รหัสภายใน' → ตอบ ไม่ใช่ข้อมูลทะเบียน → ไฟล์เสร็จ อัปซ้ำไม่ถาม"""
    rows = [HEAD + ["รหัสภายใน"], person(1) + ["E-1"]]
    s.registry(rows)
    q = s.reviews(1)[0]
    s.decide(1, [{"review_id": q["id"], "action": "ignore"}])
    assert s.file(1)["status"] == "completed"
    assert s.registry(rows, name="ซ้ำ.csv")["reviews"] == 0


@case("R05", "หัวคอลัมน์ของแบบฟอร์มกรมฯ (ชื่อแผนก + ID แผนกที่ว่าง) อ่านได้เลย")
def r05(s):
    """หัวตามแบบฟอร์มจริงของกรมฯ ที่มีทั้ง 'ชื่อแผนก' และ 'ID แผนก' (ว่าง) → ไม่ถามอะไร"""
    rows = [["เลขบัตรประชาชน", "ชื่อ", "นามสกุล", "ID แผนก", "ชื่อแผนก"],
            [cid(1), "ก", "ข", "", "ผลิต"], [cid(2), "ค", "ง", "", "คลัง"]]
    out = s.registry(rows)
    assert (out["added"], out["reviews"]) == (2, 0), out


@case("R06", "เลขบัตรผิดในทะเบียน ข้ามแถวนั้น แถวอื่นเข้า")
def r06(s):
    """5 แถว แถวที่ 3 เลขบัตรผิด checksum → เข้า 4 คน มีรายการ 'cid' 1 รายการ (ตอบบนหน้าจอไม่ได้)"""
    rows = [HEAD] + [person(n) for n in (1, 2)] + [[bad_cid(3), "ชื่อ3", "สกุล3", "ผลิต"]] + [person(n) for n in (4, 5)]
    out = s.registry(rows)
    assert out["added"] == 4 and s.kinds(1) == ["cid"], (out, s.kinds(1))
    assert s.reviews(1)[0]["payload"]["raw_cid"] == bad_cid(3)


@case("R07", "แถวไม่มีชื่อแผนก ข้ามแถว บอกให้แก้ไฟล์")
def r07(s):
    """แถวหนึ่งไม่มีแผนก → ไม่เข้าทะเบียน มีรายการ 'row_missing_department' ที่ตอบบนหน้าจอไม่ได้"""
    out = s.registry([HEAD, person(1), [cid(2), "ชื่อ2", "สกุล2", ""]])
    assert out["added"] == 1 and s.kinds(1) == ["row_missing_department"], (out, s.kinds(1))


@case("R08", "แผนกที่ยังไม่มี 3 คน ถามครั้งเดียว ตอบแล้วเข้าครบ")
def r08(s):
    """3 คนอยู่แผนก 'ซ่อมบำรุง' ที่ยังไม่มี → ถามข้อเดียว ตอบ 'เพิ่มแผนก' → แผนกถูกสร้าง คนเข้าครบ 3"""
    out = s.registry([HEAD] + [person(n, "ซ่อมบำรุง") for n in (1, 2, 3)])
    assert out["added"] == 0 and s.kinds(1) == ["unknown_department"], (out, s.kinds(1))
    q = s.reviews(1)[0]
    s.decide(1, [{"review_id": q["id"], "action": "add_department"}])
    assert s.h.scalar("select count(*) from departments where name='ซ่อมบำรุง'") == 1
    assert s.h.scalar("select count(*) from employees") == 3
    assert s.file(1)["status"] == "completed"


@case("R09", "แผนกที่ยังไม่มี กด 'ข้ามไว้ก่อน' แล้วกลับมาตอบทีหลัง")
def r09(s):
    """ข้ามคำถามแผนก → ไม่มีคนเข้า คำถามยังค้าง → ตอบทีหลัง → คนเข้า"""
    s.registry([HEAD, person(1, "ซ่อมบำรุง")])
    q = s.reviews(1)[0]
    s.decide(1, [{"review_id": q["id"], "action": "skip"}])
    assert s.h.scalar("select count(*) from employees") == 0 and s.kinds(1) == ["unknown_department"]
    q = s.reviews(1)[0]          # the file is re-read after every save, so a waiting question gets a new id
    s.decide(1, [{"review_id": q["id"], "action": "add_department"}])
    assert s.h.scalar("select count(*) from employees") == 1


@case("R10", "ค่าเพศที่ไม่รู้จัก คนยังเข้า ช่องเพศว่าง มีรายการให้แก้ไฟล์")
def r10(s):
    """เพศเขียนว่า 'ไม่ระบุ' → คนเข้าทะเบียน เพศว่าง ไม่เดาให้ มีรายการ 'value'"""
    rows = [HEAD_FULL, person(1) + ["ไม่ระบุ", "2530", "ช่าง", "5"]]
    s.registry(rows)
    e = employee(s, 1)[0]
    assert e["gender"] is None and "value" in s.kinds(1), (e["gender"], s.kinds(1))


@case("R11", "ปีเกิดเป็น ค.ศ. แปลงเป็น พ.ศ. ให้")
def r11(s):
    """ปีเกิด 1987 → เก็บ 2530"""
    s.registry([HEAD_FULL, person(1) + ["ชาย", "1987", "ช่าง", "5"]])
    assert int(employee(s, 1)[0]["birth_year"]) == 2530


@case("R12", "คำนำหน้าติดมากับชื่อ ตัดออกให้")
def r12(s):
    """ชื่อ 'นายสมชาย' → เก็บ 'สมชาย'"""
    s.registry([HEAD, [cid(1), "นายสมชาย", "ใจดี", "ผลิต"]])
    assert employee(s, 1)[0]["first_name"] == "สมชาย"


@case("R13", "ค่าในทะเบียนไม่ตรงไฟล์ใหม่ ถามว่าจะใช้ค่าไหน")
def r13(s):
    """ตำแหน่งเปลี่ยนในไฟล์ใหม่ 2 คน → ค่าเดิมอยู่ก่อน ถาม 2 ข้อ; ตอบ 'ใช้ค่าใหม่' คนหนึ่ง 'เก็บเดิม' อีกคน"""
    s.registry([HEAD_FULL, person(1) + ["ชาย", "2530", "ช่างกลึง", "5"], person(2) + ["หญิง", "2531", "ช่างเชื่อม", "3"]])
    s.registry([HEAD_FULL, person(1) + ["ชาย", "2530", "หัวหน้ากะ", "5"], person(2) + ["หญิง", "2531", "หัวหน้าแผนก", "3"]],
               name="ใหม่.csv")
    qs = s.reviews(2)
    assert sorted(q["kind"] for q in qs) == ["registry_value", "registry_value"]
    assert employee(s, 1)[0]["position"] == "ช่างกลึง"            # untouched until answered
    by = {q["payload"]["cid"]: q for q in qs}
    s.decide(2, [{"review_id": by[cid(1)]["id"], "action": "replace"},
                 {"review_id": by[cid(2)]["id"], "action": "keep"}])
    assert employee(s, 1)[0]["position"] == "หัวหน้ากะ"
    assert employee(s, 2)[0]["position"] == "ช่างเชื่อม"
    assert s.file(2)["status"] == "completed"


@case("R14", "คนเดียวกันอยู่สองแผนก เป็นสองแถว")
def r14(s):
    """เลขบัตรเดียวกัน 2 แผนก → 2 แถวในทะเบียน (กรมฯ ใช้ (เลขบัตร, แผนก) เป็นคีย์)"""
    s.registry([HEAD, person(1, "ผลิต"), person(1, "คลัง")])
    assert len(employee(s, 1)) == 2


@case("R15", "ไฟล์ที่ไม่มีหัวตารางที่รู้จักเลย")
def r15(s):
    """ไฟล์ที่หัวคอลัมน์ไม่รู้จักสักอัน → ไม่นำเข้า มีรายการ 'profile' บอกให้แก้ไฟล์ ไม่พัง"""
    out = s.registry([["ก", "ข"], ["1", "2"]])
    assert out["success"] and s.h.scalar("select count(*) from employees") == 0
    assert s.kinds(1) == ["profile"], s.kinds(1)


@case("R16", "ไม่มีคอลัมน์เลขบัตรที่รู้จัก ถามให้เลือกคอลัมน์")
def r16(s):
    """หัวเลขบัตรเขียนว่า 'บัตร13หลัก' → ถามให้เลือกคอลัมน์เลขบัตร ตอบแล้วนำเข้าครบ"""
    head = ["บัตร13หลัก", "ชื่อ", "นามสกุล", "ชื่อแผนก"]
    s.registry([head, person(1), person(2)])
    ident = [q for q in s.reviews(1) if q["kind"] == "identity"]
    assert ident, s.kinds(1)
    s.decide(1, [{"review_id": ident[0]["id"], "action": "identity", "role": "cid", "header": "บัตร13หลัก"}])
    assert s.h.scalar("select count(*) from employees") == 2, s.kinds(1)


@case("R17", "ไฟล์มีบรรทัดหัวเรื่องก่อนหัวตาราง")
def r17(s):
    """สองบรรทัดแรกเป็นชื่อรายงาน หัวตารางอยู่บรรทัดที่ 3 → อ่านได้ ไม่ถาม"""
    rows = [["รายชื่อพนักงาน บริษัททดสอบ"], ["ปี 2569"], [], HEAD, person(1), person(2)]
    out = s.registry(rows)
    assert (out["added"], out["reviews"]) == (2, 0), out


@case("R18", "ไฟล์ทะเบียนเป็น .xlsx")
def r18(s):
    """อัป .xlsx (เลขบัตรเป็นตัวเลข ไม่ใช่ข้อความ) → อ่านได้ครบ"""
    rows = [HEAD] + [[int(cid(n)), f"ชื่อ{n}", f"สกุล{n}", "ผลิต"] for n in (1, 2, 3)]
    out = s.registry(None, name="ทะเบียน.xlsx", raw=xlsx_bytes({"Sheet1": rows}))
    assert out["added"] == 3, out


@case("R19", "ไฟล์มีแต่หัวตาราง ไม่มีคน")
def r19(s):
    """มีแต่บรรทัดหัวตาราง → ไม่พัง เสร็จ ไม่มีใครเข้า"""
    out = s.registry([HEAD])
    assert out["success"] and out["rows"] == 0 and s.file(1)["status"] == "completed", out


@case("R20", "คนเดียวกันซ้ำสองแถวในไฟล์เดียว")
def r20(s):
    """แถวซ้ำ (เลขบัตร+แผนกเดียวกัน) ในไฟล์เดียวกัน → ไฟล์ต้องไม่พัง เหลือ 1 คน"""
    out = s.registry([HEAD, person(1), person(1), person(2)])
    assert out["success"], out
    assert s.h.scalar("select count(*) from employees where cid=:c", c=cid(1)) == 1
    assert s.file(1)["status"] != "failed", s.file(1)["errors"]


@case("R21", "เลขบัตรเขียนมีขีดคั่น")
def r21(s):
    """1-1017-00207-36-4 แบบมีขีด → อ่านเป็นเลข 13 หลักได้"""
    c = cid(1)
    dashed = f"{c[0]}-{c[1:5]}-{c[5:10]}-{c[10:12]}-{c[12]}"
    s.registry([HEAD, [dashed, "ก", "ข", "ผลิต"]])
    assert employee(s, 1), "person with a dashed id was not registered"


@case("R22", "ชื่อว่างในทะเบียน")
def r22(s):
    """แถวที่ไม่มีชื่อเลย → ไฟล์ต้องไม่พัง (จะเข้าโดยไม่มีชื่อ หรือถาม ก็ได้ ห้ามล้ม)"""
    out = s.registry([HEAD, [cid(1), "", "", "ผลิต"]])
    assert out["success"] and s.file(1)["status"] != "failed", (out, s.file(1)["errors"])


@case("R23", "ทะเบียนไฟล์ CSV ภาษาไทยเข้ารหัส cp874 (Windows เก่า)")
def r23(s):
    """CSV เข้ารหัส cp874 → อ่านภาษาไทยถูก ไม่กลายเป็นตัวประหลาด"""
    raw = csv_bytes([HEAD, person(1)], encoding="cp874")
    s.registry(None, raw=raw, name="เก่า.csv")
    assert employee(s, 1)[0]["first_name"] == "ชื่อ1", employee(s, 1)


# ═══════════════════════════════════════════════════════════════════════════
# L — นำเข้าผลตรวจ
# ═══════════════════════════════════════════════════════════════════════════

ID2 = ["เลขบัตรประชาชน", "ชื่อ-สกุล"]


def lab(cols, *people, extra_head=()):
    """A wide results file. people = (n, [values...]); the name is filled in, the register wins."""
    rows = [ID2 + list(cols)]
    for n, vals in people:
        rows.append([cid(n), f"ชื่อ{n} สกุล{n}"] + list(vals))
    return rows


def with_people(s):
    s.default_people()


@case("L01", "ไฟล์ผลตรวจสะอาด แปลงหน่วยและรหัสถูก")
def l01(s):
    """ผลตรวจ 2 คน (hb, wbc เป็นเซลล์/µL, plt, เอกซเรย์ 1/2) → เก็บครบ wbc/plt เป็น 10^3/µL
    เอกซเรย์ 1→0 2→1 เก็บค่าดิบไว้ ไม่มีคำถาม ไฟล์เสร็จ"""
    with_people(s)
    out = s.results(lab(["hb", "wbc", "plt", "chest_xray", "ekg"],
                        (1, [14.2, 8383, 210186, 1, 2]), (2, [12.6, 4700, 300000, 2, 1])))
    assert out["status"] == "completed" and not s.reviews(), (out["status"], s.kinds())
    c1 = s.checkup(1)
    assert (num(c1["hb"]), num(c1["wbc"]), num(c1["plt"])) == (14.2, 8.38, 210.19), c1
    assert (c1["chest_xray"], c1["ekg"]) == (0, 1), c1
    assert s.checkup(2)["chest_xray"] == 1
    raw = s.h.scalar("select raw_value from value_provenance where \"column\"='wbc' order by id limit 1")
    assert raw == "8383", raw


@case("L02", "คนที่ไม่อยู่ในทะเบียน ผลถูกพัก ตอบแล้วเข้า")
def l02(s):
    """ไฟล์มีคนที่ไม่อยู่ในทะเบียน → คนอื่นเข้า คนนั้นถูกพักพร้อมบอกจำนวนค่าที่รอ
    ตอบ 'เพิ่มเข้าทะเบียน' → เข้าทะเบียนและมีผลตรวจ ไฟล์เสร็จ"""
    with_people(s)
    s.results(lab(["hb", "wbc"], (1, [14.0, 7000]), (99, [13.0, 6500])))
    assert s.checkup(1) and not s.checkup(99), "the stranger's results must be held back"
    q = s.reviews(s.fid)
    assert [x["kind"] for x in q] == ["unregistered_person"], s.kinds(s.fid)
    assert q[0]["payload"]["values_waiting"] == 2 and "ผลิต" in q[0]["payload"]["known_departments"]
    s.decide(s.fid, [{"review_id": q[0]["id"], "action": "register", "header": "ผลิต",
                  "first_name": "คนใหม่", "last_name": "มาก่อน"}])
    assert num(s.checkup(99)["hb"]) == 13.0
    assert s.file(s.fid)["status"] == "completed"


@case("L03", "คนแปลกหน้ากด 'ข้ามไว้ก่อน' ผลยังพักอยู่")
def l03(s):
    """ข้ามคำถาม → คนนั้นไม่เข้า คำถามยังค้าง ผลคนอื่นไม่ได้รับผลกระทบ"""
    with_people(s)
    s.results(lab(["hb"], (1, [14.0]), (99, [13.0])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "skip"}])
    assert not s.checkup(99) and s.kinds(s.fid) == ["unregistered_person"]
    assert num(s.checkup(1)["hb"]) == 14.0


@case("L04", "เลขบัตรผิดในไฟล์ผลตรวจ ข้ามแถวนั้น")
def l04(s):
    """แถวที่ 2 เลขบัตรผิด → คนอื่นเข้า มีรายการ 'cid' ที่ตอบบนหน้าจอไม่ได้"""
    with_people(s)
    rows = lab(["hb"], (1, [14.0]), (3, [13.0]))
    rows[2][0] = bad_cid(3)
    s.results(rows)
    assert s.checkup(1) and not s.checkup(3) and s.kinds(s.fid) == ["cid"], s.kinds(s.fid)


@case("L05", "ค่านอกช่วงค่าเดียว ไม่เก็บค่านั้น แจ้งให้แก้ไฟล์")
def l05(s):
    """hb = 99 ของคนหนึ่งในไฟล์เล็ก (2 คน) → ค่านั้นไม่ถูกเก็บ มีรายการ 'value' คนอื่นปกติ"""
    with_people(s)
    s.results(lab(["hb"], (1, [14.0]), (2, [99])))
    assert num(s.checkup(1)["hb"]) == 14.0
    c2 = s.checkup(2)
    assert c2 is None or c2["hb"] is None, "an implausible value must not be stored"
    assert "value" in s.kinds(s.fid), s.kinds(s.fid)


@case("L06", "ค่านอกช่วงหนึ่งใน 10 (น้อยกว่า 20%) ยังเป็นรายการค่า ไม่ถามทั้งคอลัมน์")
def l06(s):
    """10 คน hb 1 คนผิดปกติ (10%) → เก็บ 9 ค่า มีรายการ 'value' 1 รายการ ไม่มีคำถามระดับคอลัมน์"""
    s.registry([HEAD] + [person(n) for n in range(1, 11)])
    vals = [(n, [14.0]) for n in range(1, 10)] + [(10, [99])]
    s.results(lab(["hb"], *vals))
    assert s.n_checkups() == 9 or s.n_checkups() == 10
    assert "mapping" not in s.kinds(s.fid) and "value" in s.kinds(s.fid), s.kinds(s.fid)


@case("L07", "ค่าผิดสเกลหน่วย (wbc 4.7) ถามซ้ำพร้อมเหตุผล ตอบหน่วยแล้วเก็บถูก")
def l07(s):
    """wbc = 4.7, 4.91, 6.46, 5.51 (หน่วยพัน/µL) → ถามคอลัมน์ พร้อมธง range_suspect ตอบ set wbc หน่วย 10^3/µl
    → เก็บ 4.70 ... ; ไฟล์รูปแบบเดียวกันครั้งต่อไปไม่ถาม"""
    with_people(s)
    rows = lab(["wbc"], *[(n, [v]) for n, v in ((1, 4.7), (2, 4.91), (3, 6.46), (4, 5.51))])
    s.results(rows)
    q = s.reviews(s.fid)
    assert [x["kind"] for x in q] == ["mapping"] and q[0]["payload"].get("range_suspect") is True, q
    s.decide(s.fid, [{"review_id": q[0]["id"], "action": "set", "target": "wbc", "unit": "10^3/µl"}])
    assert num(s.checkup(1)["wbc"]) == 4.7 and num(s.checkup(3)["wbc"]) == 6.46, s.checkup(1)
    assert s.file(s.fid)["status"] == "completed"
    s.results(rows, name="อีกไฟล์.csv", round_id=s.r2)
    assert not s.reviews(), "the learned unit must apply to the next file"


@case("L08", "ตอบคอลัมน์ไม่ระบุหน่วย ระบบยังถามซ้ำอย่างมีเหตุผล (ไม่เก็บค่าผิด)")
def l08(s):
    """ตอบ 'เป็น wbc' โดยไม่ใส่หน่วย → ค่าอยู่นอกช่วง ต้องถูกถามอีก ห้ามเก็บ 0.0047"""
    with_people(s)
    s.results(lab(["wbc"], *[(n, [v]) for n, v in ((1, 4.7), (2, 4.91), (3, 6.46), (4, 5.51))]))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "set", "target": "wbc"}])
    assert s.n_checkups() == 0 or all(s.checkup(n)["wbc"] is None for n in (1, 2, 3, 4)), "wrong-scale value stored"
    again = s.reviews(s.fid)
    assert again and again[0]["payload"].get("range_suspect") is True, again


@case("L09", "คอลัมน์ไม่รู้จัก: ตอบเก็บเป็นข้อมูลเพิ่มเติม (คอลัมน์ของบริษัท)")
def l09(s):
    """คอลัมน์ 'ค่าเหล็กในเลือด' (AI ใช้ไม่ได้) → ถามคน ตอบ extra ตั้งชื่อคอลัมน์ใหม่ของบริษัท →
    ค่าอยู่ใน extra_results ผูกกับ company_extra_columns ไม่ทิ้ง ไม่ถามอีก แม้ต่างรอบ (รอบเดียวกันบริษัทเดียวกัน)"""
    with_people(s)
    rows = lab(["ค่าเหล็กในเลือด"], (1, [120]), (2, [98]))
    s.results(rows)
    q = s.reviews(s.fid)
    assert [x["kind"] for x in q] == ["mapping"], s.kinds(s.fid)
    assert q[0]["payload"].get("company_id") == s.co, q[0]["payload"]
    s.decide(s.fid, [{"review_id": q[0]["id"], "action": "extra",
                      "column_name": "ค่าเหล็กในเลือด", "column_kind": "numeric"}])
    assert s.h.scalar("select count(*) from extra_results where column_id is not null") == 2
    assert s.h.scalar("select count(*) from company_extra_columns where company_id=:c", c=s.co) == 1
    s.results(rows, name="ซ้ำ.csv", round_id=s.r2)
    assert not s.reviews(), "a company column must be remembered, not asked again"


@case("L09b", "คอลัมน์ของบริษัท: อีกคอลัมน์หนึ่งเลือกใช้คอลัมน์เดิมที่เคยตั้งไว้ ไม่สร้างซ้ำ")
def l09b(s):
    """ตั้งคอลัมน์ของบริษัทจากคอลัมน์แรก แล้วอีกไฟล์หนึ่งมีชื่อคอลัมน์คนละชื่อ (แต่ความหมายเดียวกัน)
    เลือกคอลัมน์เดิมด้วย column_id → ไม่มีคอลัมน์ใหม่ถูกสร้าง ค่าทั้งสองผูกกับคอลัมน์เดียวกัน"""
    with_people(s)
    s.results(lab(["ค่าเหล็กในเลือด"], (1, [120])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "extra",
                      "column_name": "ค่าเหล็กในเลือด", "column_kind": "numeric"}])
    col_id = s.h.scalar("select id from company_extra_columns where company_id=:c", c=s.co)

    s.results(lab(["Fe serum"], (2, [98])), name="อีกไฟล์.csv")
    q2 = s.reviews(s.fid)[0]
    assert q2["kind"] == "mapping"
    s.decide(s.fid, [{"review_id": q2["id"], "action": "extra", "column_id": col_id}])
    assert s.h.scalar("select count(*) from company_extra_columns where company_id=:c", c=s.co) == 1
    assert s.h.scalar("select count(*) from extra_results where column_id=:i", i=col_id) == 2


@case("L09c", "คอลัมน์ของบริษัท: ไฟล์ถัดไปเขียนหน่วยไม่ตรงกับที่เคยตั้งไว้ → ถามคนใหม่")
def l09c(s):
    """ตั้งคอลัมน์ตัวเลขพร้อมหน่วย mg/L แล้วไฟล์ถัดไปเขียนหน่วยอื่น (µg/L) สำหรับชื่อเดียวกัน →
    ต้องไม่เงียบๆ ผสมหน่วยกัน ถามคนก่อนเสมอ ตอบเลือกคอลัมน์เดิมได้ (รับทราบว่าหน่วยไม่ตรง)"""
    with_people(s)
    s.results(lab(["ค่าตะกั่วพิเศษ (mg/L)"], (1, [5])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "extra",
                      "column_name": "ค่าตะกั่วพิเศษ", "column_kind": "numeric", "column_unit": "mg/L"}])
    col_id = s.h.scalar("select id from company_extra_columns where company_id=:c", c=s.co)

    s.results(lab(["ค่าตะกั่วพิเศษ (µg/L)"], (2, [12])), name="หน่วยอื่น.csv")
    q2 = s.reviews(s.fid)[0]
    assert q2["kind"] == "mapping" and q2["payload"].get("company_column_conflict", {}).get("id") == col_id, q2
    s.decide(s.fid, [{"review_id": q2["id"], "action": "extra", "column_id": col_id}])
    assert s.h.scalar("select count(*) from extra_results where column_id=:i", i=col_id) == 2
    assert s.h.scalar("select count(*) from company_extra_columns where company_id=:c", c=s.co) == 1


@case("L09d", "คอลัมน์ของบริษัท: mapping 'extra ไม่มีชื่อ' เก่าของโรงพยาบาล → ถามคนให้ตั้งชื่อ")
def l09d(s):
    """โรงพยาบาลเคยจำ 'far_lateral_phoria' เป็น __extra__ (แบบเก่า ไม่มีชื่อ AI รับเองได้) →
    ไฟล์ของบริษัทต้องไม่เก็บเป็นแถวไม่มีชื่ออีก: ถามคน ตอบ 'อนุมัติตาม AI' ที่เสนอ __extra__ ถูกปฏิเสธ
    ตั้งชื่อคอลัมน์แล้วค่าผูกกับคอลัมน์ ไม่มีแถว extra ไม่มีชื่อเลย"""
    from app.database import SessionLocal
    from app.graph.flow import save_mapping
    with SessionLocal() as db:
        hosp = s.h.scalar("select id from hospitals where code='H01'")
        save_mapping(db, hosp, "far_lateral_phoria", None, "__extra__", 1.0, "agent_auto", "old auto")
        db.commit()
    with_people(s)
    s.results(lab(["far_lateral_phoria"], (1, [1]), (2, [2])))
    q = s.reviews(s.fid)
    assert [x["kind"] for x in q] == ["mapping"], s.kinds(s.fid)
    assert s.h.scalar("select count(*) from extra_results") == 0, "stored as a nameless extra"
    # the review carries the model's bare __extra__, as the live graph's would
    from sqlalchemy import text
    with s.h.engine.begin() as c:
        c.execute(text("update pending_reviews set payload = (payload::jsonb || "
                       "'{\"proposal\": {\"target\": \"__extra__\", \"factor\": 1.0}}')::json where id=:i"),
                  {"i": q[0]["id"]})
    s.decide(s.fid, [{"review_id": q[0]["id"], "action": "approve"}], expect=400)
    s.decide(s.fid, [{"review_id": q[0]["id"], "action": "extra",
                      "column_name": "ตาเหล่แนวนอน", "column_kind": "numeric"}])
    assert s.h.scalar("select count(*) from extra_results where column_id is null") == 0
    assert s.h.scalar("select count(*) from extra_results where column_id is not null") == 2


@case("L10", "คอลัมน์ไม่รู้จัก: ตอบ 'ไม่ใช่ผลตรวจ' ค่าไม่ถูกเก็บ และไม่ถามอีก")
def l10(s):
    """ตอบ ignore → ไม่มีอะไรถูกเก็บจากคอลัมน์นั้น ไฟล์ถัดไปไม่ถามอีก"""
    with_people(s)
    rows = lab(["รหัสภายใน"], (1, ["A1"]), (2, ["A2"]))
    s.results(rows)
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "ignore"}])
    assert s.h.scalar("select count(*) from extra_results") == 0
    s.results(rows, name="ซ้ำ.csv", round_id=s.r2)
    assert not s.reviews()


@case("L11", "คอลัมน์ไม่รู้จัก: ตอบเป็นช่องของแบบฟอร์ม พร้อมหน่วย")
def l11(s):
    """คอลัมน์ 'Serum Cr' หน่วย µmol/L (88.4 → 1.0 mg/dL) → ตอบ creatinine หน่วย µmol/L → เก็บ 1.00"""
    with_people(s)
    s.results(lab(["Serum Cr"], (1, [88.4]), (2, [70.7])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "set", "target": "creatinine", "unit": "µmol/L"}])
    assert num(s.checkup(1)["creatinine"]) == 1.0, s.checkup(1)


@case("L12", "ตอบ 'ตั้งเป็นช่อง' ด้วยหน่วยที่ระบบไม่รู้จัก ถูกปฏิเสธ")
def l12(s):
    """หน่วยที่ไม่มีในตารางแปลง → 400 ไม่ปล่อยให้เก็บโดยเดา"""
    with_people(s)
    s.results(lab(["Serum Cr"], (1, [1.0]), (2, [0.9])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "set", "target": "creatinine", "unit": "furlongs"}], expect=400)


@case("L13", "ค่าซ้ำในไฟล์เดียว: ค่าเท่ากันเก็บครั้งเดียว ค่าต่างกันไม่เลือกให้")
def l13(s):
    """คนเดียวกัน 2 แถวในไฟล์เดียว: hb เท่ากัน → เก็บ 1 ค่าเงียบๆ; wbc ต่างกัน → ไม่เก็บ มีรายการ"""
    with_people(s)
    rows = lab(["hb", "wbc"], (1, [14.0, 7000]), (1, [14.0, 9000]))
    s.results(rows)
    c = s.checkup(1)
    assert num(c["hb"]) == 14.0
    assert c["wbc"] is None and "value" in s.kinds(s.fid), (c["wbc"], s.kinds(s.fid))


@case("L14", "อัปไฟล์เดิมซ้ำ ข้ามทุกค่า ไม่มีขัดแย้ง")
def l14(s):
    """ไฟล์เดิมอัปครั้งที่สอง → ทุกค่า 'ข้าม (เท่าเดิม)' ไม่มีขัดแย้ง ไม่มีคำถามใหม่ จำนวนแถวเท่าเดิม"""
    with_people(s)
    rows = lab(["hb", "wbc"], (1, [14.2, 8383]), (2, [12.6, 4700]))
    s.results(rows)
    out = s.results(rows, name="ซ้ำ.csv")
    assert out["stats"]["stored"] == 0 and out["stats"]["skipped_same"] == 4, out["stats"]
    assert s.h.scalar("select count(*) from conflicts") == 0 and s.n_checkups() == 2


@case("L15", "รอบใหม่ของคนเดิม เป็นแถวใหม่ ไม่ขัดแย้ง")
def l15(s):
    """คนเดียวกัน hb ต่างกันในรอบที่ 2 → แถวใหม่ ไม่มีขัดแย้ง"""
    with_people(s)
    s.results(lab(["hb"], (1, [14.0])))
    s.results(lab(["hb"], (1, [15.5])), name="รอบ2.csv", round_id=s.r2)
    assert num(s.checkup(1, s.r1)["hb"]) == 14.0 and num(s.checkup(1, s.r2)["hb"]) == 15.5
    assert s.h.scalar("select count(*) from conflicts") == 0


@case("L16", "ผลเขียนเป็นข้อความ (Fibrosis RUL) ถามปกติหรือผิดปกติ")
def l16(s):
    """chest_xray = 'Fibrosis RUL' 2 คน → ถามครั้งเดียวต่อข้อความ (ส่งคำตอบให้ทั้ง 2 รายการ)
    ตอบ ผิดปกติ → chest_xray = 1 และเก็บข้อความเป็นคอมเมนต์ ไฟล์ถัดไปที่มีข้อความเดียวกันไม่ถาม"""
    with_people(s)
    rows = lab(["chest_xray"], (1, ["Fibrosis RUL"]), (2, ["Fibrosis RUL"]), (3, ["ปกติ"]))
    s.results(rows)
    qs = [x for x in s.reviews(s.fid) if x["kind"] == "comment"]
    assert len(qs) >= 2, s.kinds(s.fid)
    s.decide(s.fid, [{"review_id": q["id"], "action": "comment", "value": 2} for q in qs
                 if q["payload"]["text"] == "Fibrosis RUL"])
    c = s.checkup(1)
    assert c["chest_xray"] == 1 and c["xray_comment"] == "Fibrosis RUL", c
    s.results(lab(["chest_xray"], (4, ["Fibrosis RUL"])), name="อีกไฟล์.csv", round_id=s.r2)
    assert not [x for x in s.reviews() if x["payload"].get("text") == "Fibrosis RUL"], "meaning must be remembered"


@case("L17", "ความดัน 120/80 แยกเป็นตัวบนตัวล่าง")
def l17(s):
    """คอลัมน์ bp = '120/80' → bp_systolic 120, bp_diastolic 80"""
    with_people(s)
    s.results(lab(["bp"], (1, ["120/80"]), (2, ["135/85"])))
    c = s.checkup(1)
    assert c and (num(c["bp_systolic"]), num(c["bp_diastolic"])) == (120, 80), (c, s.kinds(s.fid))


@case("L18", "ช่องว่างในไฟล์ ไม่ถูกเก็บ ไม่มีคำถาม")
def l18(s):
    """เซลล์ว่างและ N/A → ไม่เก็บอะไร ไม่มีรายการค่าผิด"""
    with_people(s)
    s.results(lab(["hb", "wbc"], (1, ["", 7000]), (2, ["N/A", 6000])))
    assert s.checkup(1)["hb"] is None and num(s.checkup(1)["wbc"]) == 7.0
    assert not s.reviews(), s.kinds(s.fid)


@case("L19", "ไฟล์แบบ long (หนึ่งแถวต่อหนึ่งผลตรวจ)")
def l19(s):
    """คอลัมน์ เลขบัตร/ชื่อ/รายการตรวจ/ผล/หน่วย → เก็บถูก แปลงหน่วย"""
    with_people(s)
    rows = [["เลขบัตรประชาชน", "ชื่อ-สกุล", "รายการตรวจ", "ผลตรวจ", "หน่วย"],
            [cid(1), "ชื่อ1 สกุล1", "hb", 142, "g/L"], [cid(1), "ชื่อ1 สกุล1", "wbc", 8383, "cells/µL"],
            [cid(2), "ชื่อ2 สกุล2", "hb", 126, "g/L"], [cid(2), "ชื่อ2 สกุล2", "wbc", 4700, "cells/µL"]]
    s.results(rows)
    c = s.checkup(1)
    assert c and (num(c["hb"]), num(c["wbc"])) == (14.2, 8.38), (c, s.kinds(s.fid))


@case("L20", "หน่วยอยู่ในวงเล็บหัวคอลัมน์ (Hb (g/L))")
def l20(s):
    """หัว 'hb (g/L)' ค่า 142 → 14.2 g/dL"""
    with_people(s)
    s.results(lab(["hb (g/L)"], (1, [142]), (2, [126])))
    c = s.checkup(1)
    assert c and num(c["hb"]) == 14.2, (c, s.kinds(s.fid))


@case("L21", "หน่วยแปลกในวงเล็บ ไม่แปลงเอง")
def l21(s):
    """หัว 'hb (furlongs)' → ไม่เดาแปลง ถามคน ไม่เก็บค่า"""
    with_people(s)
    s.results(lab(["hb (furlongs)"], (1, [14.2]), (2, [12.6])))
    assert "mapping" in s.kinds(s.fid) and (s.checkup(1) is None or s.checkup(1)["hb"] is None), s.kinds(s.fid)


@case("L22", "ไฟล์ไม่มีคอลัมน์ชื่อเลย (เลขบัตรกับผลตรวจล้วน)")
def l22(s):
    """ไฟล์มีแต่เลขบัตรกับผล ไม่มีชื่อ → ต้องเก็บได้ ไม่ถามหาคอลัมน์ชื่อ (ชื่ออยู่ในทะเบียนแล้ว)"""
    with_people(s)
    rows = [["เลขบัตรประชาชน", "hb"], [cid(1), 14.0], [cid(2), 13.0]]
    s.results(rows)
    assert s.n_checkups() == 2 and not [k for k in s.kinds(s.fid) if k == "identity"], s.kinds(s.fid)


@case("L23", "ชื่อในไฟล์ต่างจากทะเบียน ทะเบียนเป็นหลัก ไม่ถาม")
def l23(s):
    """ชื่อในไฟล์เขียนคนละชื่อกับทะเบียน แต่เลขบัตรตรง → เก็บผลให้คนในทะเบียน ไม่ถาม ไม่แก้ชื่อทะเบียน"""
    with_people(s)
    rows = [ID2 + ["hb"], [cid(1), "ชื่อผิดในไฟล์ ไม่ตรง", 14.0]]
    s.results(rows)
    assert s.checkup(1) and not s.reviews()
    assert s.h.scalar("select first_name from employees where cid=:c", c=cid(1)) == "ชื่อ1"


@case("L24", "วันที่ตรวจในไฟล์ต่างจากวันนัดของรอบ")
def l24(s):
    """ไฟล์มีคอลัมน์วันที่ตรวจ (พ.ศ.) ต่างจากวันนัด → เก็บวันที่ของแต่ละคนไว้ที่ checkup_date;
    ตรงกับวันนัด → ไม่เก็บซ้ำ (ว่าง)"""
    with_people(s)
    rows = [ID2 + ["วันที่ตรวจ", "hb"], [cid(1), "ก", "5/3/2569", 14.0], [cid(2), "ข", "1/3/2569", 13.0]]
    s.results(rows)
    assert str(s.checkup(1)["checkup_date"]) == "2026-03-05", s.checkup(1)
    assert s.checkup(2)["checkup_date"] is None, s.checkup(2)


@case("L25", "วันที่ในไฟล์อ่านไม่ออก (คอลัมน์ไม่ถูกมองเป็นวันที่)")
def l25(s):
    """คอลัมน์ 'วันที่ตรวจ' ที่ค่าเป็นขยะ → ระบบไม่มองเป็นคอลัมน์วันที่ ถามว่าคอลัมน์นี้คืออะไร (ไม่ทิ้งเงียบ)
    ผลตรวจอื่นเก็บที่วันนัดของรอบ ไม่พังทั้งไฟล์"""
    with_people(s)
    rows = [ID2 + ["วันที่ตรวจ", "hb"], [cid(1), "สมชาย ก", "99/99/9999", 14.0], [cid(2), "สมหญิง ข", "1/3/2569", 13.0]]
    out = s.results(rows)
    assert out["success"] and s.checkup(1) and s.checkup(2), (s.kinds(s.fid))
    assert [r["payload"]["label"] for r in s.reviews(s.fid) if r["kind"] == "mapping"] == ["วันที่ตรวจ"]


@case("L26", "เลขบัตรเป็นเลขวิทยาศาสตร์ (Excel ทำเลขบัตรพัง)")
def l26(s):
    """เซลล์ '1.10046E+12' → ไม่เชื่อ ไม่เดาเลขที่เหลือ ข้ามแถว มีรายการ 'cid'"""
    with_people(s)
    rows = lab(["hb"], (1, [14.0]))
    rows.append(["1.10046E+12", "ก ข", 13.0])
    s.results(rows)
    assert s.kinds(s.fid) == ["cid"], s.kinds(s.fid)


@case("L27", "ไฟล์ .xlsx หลายชีต (ชีตแรกว่าง)")
def l27(s):
    """ไฟล์ xlsx สองชีต ชีตหนึ่งว่าง อีกชีตมีผล → เก็บผลจากชีตที่มี ไม่พัง"""
    with_people(s)
    raw = xlsx_bytes({"ว่าง": [], "ผล": lab(["hb", "wbc"], (1, [14.0, 7000]), (2, [13.0, 6000]))})
    out = s.results(None, name="หลายชีต.xlsx", raw=raw)
    assert out["success"] and s.n_checkups() == 2, (out, s.kinds(s.fid))


@case("L28", "ผลเอกซเรย์/หู/ตา เป็น 1/2 แปลงเป็น 0/1 ครบทุกช่อง")
def l28(s):
    """chest_xray, ekg, hearing_ability, far_vision_test ค่า 1 และ 2 → 0 และ 1"""
    with_people(s)
    s.results(lab(["chest_xray", "ekg", "hearing_ability", "far_vision_test"], (1, [1, 1, 1, 1]), (2, [2, 2, 2, 2])))
    c1, c2 = s.checkup(1), s.checkup(2)
    assert [c1[k] for k in ("chest_xray", "ekg", "hearing_ability", "far_vision_test")] == [0, 0, 0, 0], c1
    assert [c2[k] for k in ("chest_xray", "ekg", "hearing_ability", "far_vision_test")] == [1, 1, 1, 1], c2


@case("L29", "ไฟล์ผลตรวจมีแต่หัวตาราง")
def l29(s):
    """ไม่มีคน → ไม่พัง"""
    with_people(s)
    out = s.results(lab(["hb"]))
    assert out["success"] and s.n_checkups() == 0, out


@case("L30", "ไฟล์ CSV ภาษาไทยเข้ารหัส cp874")
def l30(s):
    """ผลตรวจใน CSV cp874 → อ่านคอลัมน์ไทยถูก"""
    with_people(s)
    raw = csv_bytes(lab(["hb", "ค่าเหล็กในเลือด"], (1, [14.0, 100])), encoding="cp874")
    s.results(None, raw=raw, name="เก่า.csv")
    q = s.reviews(s.fid)
    assert q and q[0]["payload"]["label"] == "ค่าเหล็กในเลือด", q


@case("L31", "ผลตรวจ 100 คนใน 1 ไฟล์")
def l31(s):
    """ทะเบียน 100 คน ผลตรวจ 100 คน → เก็บครบ ไม่มีคำถาม"""
    s.registry([HEAD] + [person(n) for n in range(1, 101)])
    s.results(lab(["hb", "wbc"], *[(n, [13.0 + (n % 5) * 0.1, 6000 + n]) for n in range(1, 101)]))
    assert s.n_checkups() == 100 and not s.reviews()


# ═══════════════════════════════════════════════════════════════════════════
# P — คน แผนก และทะเบียนที่ไม่ตรงกับไฟล์ผลตรวจ
# ═══════════════════════════════════════════════════════════════════════════

def with_dept(cols, *people):
    rows = [ID2 + ["แผนก"] + list(cols)]
    for n, dept, vals in people:
        rows.append([cid(n), f"ชื่อ{n} สกุล{n}", dept] + list(vals))
    return rows


@case("P01", "ไฟล์เขียนแผนกตรงกับทะเบียน ผ่านเลย")
def p01(s):
    """คอลัมน์แผนกตรงกับทะเบียน → เก็บ ไม่ถาม"""
    with_people(s)
    s.results(with_dept(["hb"], (1, "ผลิต", [14.0]), (5, "คลัง", [13.0])))
    assert s.n_checkups() == 2 and not s.reviews()


@case("P02", "แผนกในไฟล์ไม่ตรงทะเบียน → ถาม ตอบ 'ไฟล์เขียนผิด ใช้ทะเบียน'")
def p02(s):
    """คนอยู่ 'ผลิต' ในทะเบียน แต่ไฟล์เขียน 'คลัง' → พักผล ถาม; ตอบ use_register → ผลเข้าแผนกเดิม (ผลิต)
    และต้องไม่ถามซ้ำหลังตอบ"""
    with_people(s)
    s.results(with_dept(["hb"], (1, "คลัง", [14.0])))
    q = s.reviews(s.fid)
    assert [x["kind"] for x in q] == ["department_change"] and not s.checkup(1)
    s.decide(s.fid, [{"review_id": q[0]["id"], "action": "use_register"}])
    c = s.checkup(1)
    assert c and c["dept"] == "ผลิต", c
    assert not s.reviews(), f"the same question came back: {s.kinds()}"
    assert s.file(s.fid)["status"] == "completed"


@case("P03", "แผนกในไฟล์ไม่ตรงทะเบียน → ตอบ 'ย้ายแผนกจริง'")
def p03(s):
    """ตอบ move_department → เปิดแถวคนในแผนกใหม่ ผลเข้าแผนกใหม่ แถวแผนกเดิมยังอยู่ ไม่ถามซ้ำ"""
    with_people(s)
    s.results(with_dept(["hb"], (1, "คลัง", [14.0])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "move_department"}])
    assert len(employee(s, 1)) == 2, "old department row must stay"
    c = s.checkup(1)
    assert c and c["dept"] == "คลัง", c
    assert not s.reviews() and s.file(s.fid)["status"] == "completed"


@case("P04", "แผนกในไฟล์ไม่มีอยู่จริงในสถานประกอบการ")
def p04(s):
    """ไฟล์เขียนแผนก 'แผนกลอย' ที่ไม่มี → ต้องไม่สร้างแผนกเอง; ถามคน (ไม่พัง)"""
    with_people(s)
    out = s.results(with_dept(["hb"], (1, "แผนกลอย", [14.0])))
    assert out["success"] and not s.checkup(1)
    assert s.h.scalar("select count(*) from departments where name='แผนกลอย'") == 0
    assert s.reviews(s.fid), "a person held back must have a question"


@case("P05", "คนที่อยู่สองแผนก ไฟล์ไม่บอกแผนก → ต้องไม่เดา")
def p05(s):
    """เลขบัตรเดียวกันอยู่ผลิตและคลัง ไฟล์ผลตรวจไม่มีคอลัมน์แผนก → ห้ามเลือกแถวแรกเอง
    ต้องมีคำถาม (หรืออย่างน้อยห้ามเก็บเข้าแผนกใดแผนกหนึ่งเงียบๆ)"""
    s.registry([HEAD, person(1, "ผลิต"), person(1, "คลัง")])
    s.results(lab(["hb"], (1, [14.0])))
    rows = s.h.sql("select d.name from employee_checkups c join employees e on e.id=c.employee_id "
                   "join departments d on d.id=e.department_pk")
    assert not rows or s.reviews(s.fid), f"stored silently under {rows} with no question"


@case("P06", "คนที่อยู่สองแผนก ไฟล์บอกแผนก → เข้าแถวที่ถูกต้อง")
def p06(s):
    """ไฟล์ระบุ 'คลัง' → ผลเข้าแถวคนในคลัง ไม่ใช่ผลิต"""
    s.registry([HEAD, person(1, "ผลิต"), person(1, "คลัง")])
    s.results(with_dept(["hb"], (1, "คลัง", [14.0])))
    rows = s.h.sql("select d.name from employee_checkups c join employees e on e.id=c.employee_id "
                   "join departments d on d.id=e.department_pk")
    assert [r["name"] for r in rows] == ["คลัง"], rows


@case("P07", "ทะเบียนของอีกบริษัท ไม่ถูกใช้กับรอบของบริษัทนี้")
def p07(s):
    """คนอยู่ในทะเบียนบริษัท B เท่านั้น แต่ไฟล์ถูกอัปเข้ารอบของบริษัท A → ถือว่าไม่อยู่ในทะเบียนของ A (ถาม)"""
    with_people(s)
    co_b = s.company("บริษัท B", "0105500000002", ("ผลิต",))
    s.registry([HEAD, person(50)], company=co_b, name="ทะเบียนB.csv")
    s.results(lab(["hb"], (50, [14.0])))
    assert s.kinds(s.fid) == ["unregistered_person"], s.kinds(s.fid)


@case("P08", "คนเดียวกันอยู่ทะเบียนสองบริษัท ผลไม่ปนกัน")
def p08(s):
    """เลขบัตรเดียวกันในสองบริษัท ผลตรวจของรอบบริษัท A เข้าแถวของ A เท่านั้น"""
    with_people(s)
    co_b = s.company("บริษัท B", "0105500000002", ("ผลิต",))
    s.registry([HEAD, person(1)], company=co_b, name="ทะเบียนB.csv")
    s.results(lab(["hb"], (1, [14.0])))
    rows = s.h.sql("select d.company_id from employee_checkups c join employees e on e.id=c.employee_id "
                   "join departments d on d.id=e.department_pk")
    assert [r["company_id"] for r in rows] == [s.co], rows


@case("P09", "คนแปลกหน้าคนเดียวกันในสองไฟล์ ตอบครั้งเดียวได้ (ตอบสองรายการ)")
def p09(s):
    """สองไฟล์มีคนแปลกหน้าเลขบัตรเดียวกัน ตอบทั้งสองรายการ → เข้าทะเบียนคนเดียว (ไม่ 500) ผลสองไฟล์รวมกัน"""
    with_people(s)
    s.results(lab(["hb"], (99, [13.0])), name="ก.csv")
    f1 = s.fid
    s.results(lab(["wbc"], (99, [7000])), name="ข.csv")
    f2 = s.fid
    for f in (f1, f2):
        q = s.reviews(f)[0]
        s.decide(f, [{"review_id": q["id"], "action": "register", "header": "ผลิต",
                      "first_name": "คนใหม่", "last_name": "ทดสอบ"}])
    assert s.h.scalar("select count(*) from employees where cid=:c", c=cid(99)) == 1
    c = s.checkup(99)
    assert num(c["hb"]) == 13.0 and num(c["wbc"]) == 7.0, c


@case("P10", "เพิ่มคนแปลกหน้าโดยไม่ระบุชื่อ ถูกปฏิเสธ")
def p10(s):
    """ตอบ register แต่ไม่มีชื่อ และไฟล์ก็ไม่มีชื่อ → 400 ไม่เพิ่มคนไม่มีชื่อ"""
    with_people(s)
    s.results([["เลขบัตรประชาชน", "hb"], [cid(99), 13.0]])
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "register", "header": "ผลิต"}], expect=400)


@case("P11", "เพิ่มคนแปลกหน้าเข้าแผนกที่ไม่มีอยู่ ถูกปฏิเสธ")
def p11(s):
    """เลือกแผนกที่ไม่มีในสถานประกอบการ → 400 ไม่สร้างแผนก"""
    with_people(s)
    s.results(lab(["hb"], (99, [13.0])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "register", "header": "แผนกลอย",
                      "first_name": "ก", "last_name": "ข"}], expect=400)
    assert s.h.scalar("select count(*) from departments where name='แผนกลอย'") == 0


@case("P12", "คนอยู่สองแผนก ตอบว่าเป็นแผนกไหน ผลเข้าแผนกนั้น และไม่ถามซ้ำ")
def p12(s):
    """ไฟล์ไม่บอกแผนก ถาม 'which_department' ตอบ 'คลัง' → ผลเข้าแถวคนในคลัง แถวผลิตไม่มีผล ไม่ถามซ้ำ ไฟล์เสร็จ"""
    s.registry([HEAD, person(1, "ผลิต"), person(1, "คลัง")])
    s.results(lab(["hb"], (1, [14.0])))
    q = s.reviews(s.fid)
    assert [x["kind"] for x in q] == ["which_department"] and sorted(q[0]["payload"]["candidates"]) == ["คลัง", "ผลิต"]
    s.decide(s.fid, [{"review_id": q[0]["id"], "action": "choose_department", "header": "คลัง"}])
    rows = s.h.sql("select d.name from employee_checkups c join employees e on e.id=c.employee_id "
                   "join departments d on d.id=e.department_pk")
    assert [r["name"] for r in rows] == ["คลัง"], rows
    assert not s.reviews() and s.file(s.fid)["status"] == "completed"


@case("P13", "เลือกแผนกที่คนนี้ไม่ได้อยู่ ถูกปฏิเสธ")
def p13(s):
    """ตอบ choose_department ด้วยแผนกที่ไม่ได้อยู่ในตัวเลือก → 400"""
    s.registry([HEAD, person(1, "ผลิต"), person(1, "คลัง")])
    s.results(lab(["hb"], (1, [14.0])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "choose_department", "header": "แผนกลอย"}], expect=400)


@case("P14", "แผนกในไฟล์ไม่มีจริง ตอบ 'ไฟล์เขียนผิด' ผลเข้าแผนกตามทะเบียน")
def p14(s):
    """ไฟล์เขียน 'แผนกลอย' → ถาม; ตอบ use_register → เก็บที่แผนกทะเบียน ไม่ถามซ้ำ ไม่สร้างแผนกใหม่"""
    with_people(s)
    s.results(with_dept(["hb"], (1, "แผนกลอย", [14.0])))
    q = s.reviews(s.fid)[0]
    assert q["kind"] == "department_change"
    s.decide(s.fid, [{"review_id": q["id"], "action": "use_register"}])
    assert s.checkup(1)["dept"] == "ผลิต" and not s.reviews()
    assert s.h.scalar("select count(*) from departments where name='แผนกลอย'") == 0


@case("P15", "แผนกในไฟล์ไม่มีจริง แต่ตอบ 'ย้ายแผนกจริง' ถูกปฏิเสธ (ไม่สร้างแผนกเอง)")
def p15(s):
    """move_department ไปแผนกที่ไม่มี → 400 บอกให้เพิ่มแผนกที่หน้าทะเบียนสถานประกอบการก่อน"""
    with_people(s)
    s.results(with_dept(["hb"], (1, "แผนกลอย", [14.0])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "move_department"}], expect=400)


# ═══════════════════════════════════════════════════════════════════════════
# C — ข้อมูลขัดแย้ง
# ═══════════════════════════════════════════════════════════════════════════

def conflict_setup(s):
    with_people(s)
    s.results(lab(["hb", "wbc"], (1, [14.0, 7000]), (2, [13.0, 6000])), name="แรก.csv")
    s.results(lab(["hb", "wbc"], (1, [15.5, 7000]), (2, [13.0, 6500])), name="ที่สอง.csv")
    return s.fid


@case("C01", "ค่าใหม่ต่างจากค่าเดิม เกิดข้อขัดแย้ง ค่าเดิมยังอยู่")
def c01(s):
    """ไฟล์ที่สองให้ hb ต่างและ wbc ของอีกคนต่าง → 2 ข้อขัดแย้ง ค่าเดิมยังอยู่ ไฟล์ 'รอตรวจ'"""
    f = conflict_setup(s)
    cs = s.sa.get("/api/conflicts?status=open").json()
    assert len(cs) == 2, cs
    assert num(s.checkup(1)["hb"]) == 14.0 and num(s.checkup(2)["wbc"]) == 6.0
    assert s.file(f)["status"] == "awaiting_review"


@case("C02", "ข้อขัดแย้ง: เก็บค่าเดิม / ใช้ค่าใหม่ พร้อมประวัติ")
def c02(s):
    """keep → ค่าเดิม ไม่มีประวัติ; replace → ค่าใหม่ มีประวัติ (ค่าเก่า ค่าใหม่ ผู้ตัดสินจากบัญชี) และแหล่งที่มา;
    ตัดสินครบ → ไฟล์ 'เสร็จ'"""
    f = conflict_setup(s)
    cs = {c["column"]: c for c in s.sa.get("/api/conflicts?status=open").json()}
    r1 = s.sa.post(f"/api/conflicts/{cs['hb']['id']}/resolve", json={"action": "replace", "by": "browser-says-this"})
    r2 = s.sa.post(f"/api/conflicts/{cs['wbc']['id']}/resolve", json={"action": "keep", "by": "x"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert num(s.checkup(1)["hb"]) == 15.5 and num(s.checkup(2)["wbc"]) == 6.0
    h = s.h.sql("select * from value_history")
    assert len(h) == 1 and h[0]["reason"] == "conflict_resolved" and h[0]["old_value"] == "14.00", h
    assert h[0]["changed_by"] == "sa", f"who decided must come from the session, got {h[0]['changed_by']!r}"
    assert s.file(f)["status"] == "completed"


@case("C03", "ตัดสินข้อขัดแย้งเดิมซ้ำ ถูกปฏิเสธ")
def c03(s):
    """ตัดสินข้อเดียวกันสองครั้ง → ครั้งที่สอง 409"""
    conflict_setup(s)
    c = s.sa.get("/api/conflicts?status=open").json()[0]
    assert s.sa.post(f"/api/conflicts/{c['id']}/resolve", json={"action": "keep"}).status_code == 200
    assert s.sa.post(f"/api/conflicts/{c['id']}/resolve", json={"action": "keep"}).status_code == 409


@case("C04", "ใช้ค่าใหม่ทั้งไฟล์")
def c04(s):
    """accept-all → ทุกข้อขัดแย้งของไฟล์ถูกแทนที่ ค่าใหม่ทั้งหมด ประวัติครบ ไฟล์เสร็จ"""
    f = conflict_setup(s)
    r = s.sa.post(f"/api/files/{f}/conflicts/accept-all", json={})
    assert r.status_code == 200 and r.json()["replaced"] == 2, r.text
    assert num(s.checkup(1)["hb"]) == 15.5 and num(s.checkup(2)["wbc"]) == 6.5
    assert s.h.scalar("select count(*) from value_history") == 2 and s.file(f)["status"] == "completed"


@case("C05", "ตอบคำถามอื่นของไฟล์เดียวกัน ต้องไม่ทำข้อขัดแย้งซ้ำ")
def c05(s):
    """ไฟล์มีทั้งข้อขัดแย้งและคำถามคอลัมน์ ตอบคำถามแล้วระบบประมวลผลไฟล์ใหม่ → ข้อขัดแย้งยังเท่าเดิม ไม่ซ้ำ
    และไฟล์ยัง 'รอตรวจ' (ไม่ขึ้นเสร็จทั้งที่ยังมีข้อขัดแย้ง)"""
    with_people(s)
    s.results(lab(["hb"], (1, [14.0])), name="แรก.csv")
    s.results(lab(["hb", "รหัสภายใน"], (1, [15.5, "A1"])), name="สอง.csv")
    f = s.fid
    q = [x for x in s.reviews(f) if x["kind"] == "mapping"][0]
    s.decide(f, [{"review_id": q["id"], "action": "ignore"}])
    assert s.h.scalar("select count(*) from conflicts where status='open'") == 1
    assert s.file(f)["status"] == "awaiting_review"


@case("C06", "ค่าจากการกรองมือขัดกับไฟล์ที่นำเข้าทีหลัง")
def c06(s):
    """กรอกมือ hb=14.0 แล้วนำเข้าไฟล์ที่ให้ 15.0 → เกิดข้อขัดแย้ง (แม้ค่าเดิมไม่มีไฟล์ต้นทาง) ค่ามือยังอยู่ ไม่พัง"""
    with_people(s)
    emp = s.h.one("select id from employees where cid=:c", c=cid(1))["id"]
    r = s.sa.put("/api/checkups", json={"round_id": s.r1, "employee_id": emp, "values": {"hb": "14.0"}})
    assert r.status_code == 200, r.text
    s.results(lab(["hb"], (1, [15.0])))
    cs = s.sa.get("/api/conflicts?status=open")
    assert cs.status_code == 200 and len(cs.json()) == 1, cs.text
    assert num(s.checkup(1)["hb"]) == 14.0


# ═══════════════════════════════════════════════════════════════════════════
# D — API การตัดสินใจ: ต้องไม่ยอมรับคำตอบที่ผิดที่ผิดทาง
# ═══════════════════════════════════════════════════════════════════════════

@case("D01", "คำตอบของรายการที่เป็นของอีกไฟล์ ถูกปฏิเสธ")
def d01(s):
    """ส่งคำตอบของ review ไฟล์ A ไปที่ URL ของไฟล์ B → 400"""
    with_people(s)
    s.results(lab(["รหัสภายใน"], (1, ["A"])), name="ก.csv")
    a = s.fid
    s.results(lab(["รหัสอื่น"], (1, ["B"])), name="ข.csv")
    b = s.fid
    qa = s.reviews(a)[0]
    s.decide(b, [{"review_id": qa["id"], "action": "ignore"}], expect=400)


@case("D02", "ตอบผิดประเภท (เพิ่มคนเข้าทะเบียนให้คอลัมน์ผลตรวจ) ถูกปฏิเสธ")
def d02(s):
    """action 'register' กับคำถามคอลัมน์ → 400 ไม่มีผลข้างเคียง"""
    with_people(s)
    s.results(lab(["รหัสภายใน"], (1, ["A"])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "register", "header": "ผลิต", "first_name": "ก"}], expect=400)
    assert s.h.scalar("select count(*) from employees") == 5


@case("D03", "ตั้งเป็นช่องที่ไม่มีในแบบฟอร์ม ถูกปฏิเสธ")
def d03(s):
    """target 'ไม่มีช่องนี้' → 400"""
    with_people(s)
    s.results(lab(["รหัสภายใน"], (1, ["A"])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "set", "target": "no_such_column"}], expect=400)


@case("D04", "action ที่ไม่มีในระบบ ถูกปฏิเสธก่อนถึงตรรกะ")
def d04(s):
    """action แปลก → 422"""
    with_people(s)
    s.results(lab(["รหัสภายใน"], (1, ["A"])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "delete_everything"}], expect=422)


@case("D05", "ตอบรายการที่ตัดสินไปแล้ว ไม่ทำซ้ำ")
def d05(s):
    """เพิ่มคนแปลกหน้า แล้วส่งคำตอบเดิมซ้ำ → ไม่ error ไม่เกิดคนซ้ำ"""
    with_people(s)
    s.results(lab(["hb"], (99, [13.0])))
    q = s.reviews(s.fid)[0]
    body = [{"review_id": q["id"], "action": "register", "header": "ผลิต", "first_name": "ก", "last_name": "ข"}]
    s.decide(s.fid, body)
    s.decide(s.fid, body)
    assert s.h.scalar("select count(*) from employees where cid=:c", c=cid(99)) == 1


@case("D06", "ผู้ตัดสินมาจากบัญชีที่ล็อกอิน ไม่ใช่สิ่งที่เบราว์เซอร์บอก")
def d06(s):
    """decided_by ต้องเป็น 'sa' แม้ body จะส่ง by อื่น"""
    with_people(s)
    s.results(lab(["hb"], (99, [13.0])))
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "register", "header": "ผลิต", "first_name": "ก"}])
    who = s.h.scalar("select decided_by from pending_reviews where id=:i", i=q["id"])
    assert who == "sa", who


@case("D07", "ไฟล์ที่ไม่มีอยู่จริง")
def d07(s):
    """ตัดสิน/ดูสถานะไฟล์ id ที่ไม่มี → 404 ไม่ 500"""
    assert s.sa.post("/api/files/9999/decisions", json={"decisions": [], "by": "x"}).status_code == 404
    assert s.sa.get("/api/files/9999").status_code == 404


@case("D08", "กดข้ามทุกข้อ ไม่เกิดอะไร")
def d08(s):
    """ส่ง action skip ทุกข้อ → ไม่เปลี่ยนสถานะ คำถามยังอยู่ครบ"""
    with_people(s)
    s.results(lab(["รหัสภายใน", "hb"], (1, ["A", 14.0]), (99, ["B", 13.0])))
    qs = s.reviews(s.fid)
    before = len(qs)
    s.decide(s.fid, [{"review_id": q["id"], "action": "skip"} for q in qs])
    assert len(s.reviews(s.fid)) == before


# ═══════════════════════════════════════════════════════════════════════════
# U — ประตูการอัปโหลดและสิทธิ์
# ═══════════════════════════════════════════════════════════════════════════

def raw_upload(client, path, data, name="x.csv", content=None):
    content = content if content is not None else csv_bytes([["a"], ["1"]])
    r = client.post(path, files={"file": (name, content)}, data=data)
    return r


@case("U01", "นามสกุลไฟล์ที่ไม่รองรับ")
def u01(s):
    """.pdf → ปฏิเสธ ไม่สร้างไฟล์ในระบบ"""
    r = raw_upload(s.sa, "/api/upload", {"round_id": s.r1, "hospital": "H01"}, name="x.pdf").json()
    assert r["success"] is False and s.h.scalar("select count(*) from source_files") == 0


@case("U02", "ผลตรวจต้องเลือกรอบ / รอบที่ไม่มีอยู่")
def u02(s):
    """ไม่ส่ง round_id → ปฏิเสธ; round_id ที่ไม่มี → ปฏิเสธ"""
    assert raw_upload(s.sa, "/api/upload", {"hospital": "H01"}).json()["success"] is False
    assert raw_upload(s.sa, "/api/upload", {"round_id": 9999, "hospital": "H01"}).json()["success"] is False
    assert s.h.scalar("select count(*) from source_files") == 0


@case("U03", "ผู้ดูแลส่วนกลางต้องเลือกหน่วยบริการ และเลือกได้เฉพาะที่มีจริง")
def u03(s):
    """ไม่ส่ง hospital → ปฏิเสธ; รหัสหน่วยที่ไม่มี → ปฏิเสธ (ไม่สร้างหน่วยใหม่เอง)"""
    r = raw_upload(s.sa, "/api/upload", {"round_id": s.r1, "hospital": ""}).json()
    assert r["success"] is False and "หน่วยบริการ" in r["error"], r
    r = raw_upload(s.sa, "/api/upload", {"round_id": s.r1, "hospital": "TYPO99"}).json()
    assert r["success"] is False
    assert s.h.scalar("select count(*) from hospitals where code='TYPO99'") == 0


@case("U04", "เจ้าหน้าที่ทั่วไป: หน่วยมาจากบัญชี ไม่ใช่จากที่ส่งมา")
def u04(s):
    """staff1 (H01) ส่ง hospital=H02 → ไฟล์ถูกบันทึกเป็นของ H01"""
    with_people(s)
    r = s.results(lab(["hb"], (1, [14.0])), client=s.staff, hospital="H02")
    code = s.h.scalar("select h.code from source_files f join hospitals h on h.id=f.hospital_id where f.id=:i", i=r["upload_id"])
    assert code == "H01", code


@case("U05", "ไม่ได้ล็อกอิน")
def u05(s):
    """อัป/ดูคำถาม/ตัดสินโดยไม่ล็อกอิน → 401 ทุกเส้นทาง"""
    for method, path in (("post", "/api/upload"), ("post", "/api/upload/registry"), ("get", "/api/reviews"),
                         ("get", "/api/conflicts"), ("post", "/api/files/1/decisions"), ("get", "/api/summary?round_id=1"),
                         ("put", "/api/checkups")):
        r = getattr(s.anon, method)(path)
        assert r.status_code == 401, (path, r.status_code)


@case("U06", "ทะเบียนต้องเลือกสถานประกอบการที่มีอยู่จริง")
def u06(s):
    """ไม่ส่ง company_id / company ที่ไม่มี → ปฏิเสธ"""
    assert raw_upload(s.sa, "/api/upload/registry", {"hospital": "H01"}).json()["success"] is False
    assert raw_upload(s.sa, "/api/upload/registry", {"hospital": "H01", "company_id": 9999}).json()["success"] is False
    assert raw_upload(s.sa, "/api/upload/registry", {"hospital": "", "company_id": s.co}).json()["success"] is False


@case("U07", "ไฟล์ที่เสียหาย (ไบต์ขยะที่ตั้งนามสกุลเป็น .xlsx)")
def u07(s):
    """ไฟล์ xlsx ที่เปิดไม่ได้ → ล้มอย่างสุภาพ ไฟล์ขึ้นสถานะ failed ไม่ทำให้ระบบล่ม และไม่เขียนข้อมูล"""
    with_people(s)
    out = s.results(None, name="เสีย.xlsx", raw=b"this is not a spreadsheet at all")
    assert out["success"] is False or s.file(s.fid)["status"] == "failed", out
    assert s.n_checkups() == 0


@case("U08", "ไฟล์ทะเบียนเสียหาย")
def u08(s):
    """ทะเบียน xlsx ที่เปิดไม่ได้ → success:false ไม่ 500"""
    out = s.registry(None, name="เสีย.xlsx", raw=b"garbage")
    assert out["success"] is False, out


def _poll(s, fid, seconds=60):
    import time
    end = time.time() + seconds
    while time.time() < end:
        j = s.sa.get(f"/api/upload/{fid}/progress").json()
        if j["status"] != "processing":
            return j
        time.sleep(0.2)
    raise AssertionError(f"file {fid} still processing after {seconds}s")


@case("U09", "อัปโหลดแบบเบื้องหลัง (หน้ารายงาน): ตอบทันที บอกความคืบหน้าทุกขั้น ผลเหมือนแบบรอ")
def u09(s):
    """background=true → ได้เลขไฟล์ทันทีสถานะ processing → ถาม /progress จนจบ →
    ขั้นอ่านไฟล์/จับคู่บอกตัวเลขจริง (รู้จัก 1 จาก 2), ขั้น AI ถูกนับ, จบแล้วคำตอบเหมือนอัปแบบรอ:
    hb เก็บ, ชื่อที่ไม่รู้จักเป็นคำถาม · เลขไฟล์ที่ไม่มีอยู่ → 404"""
    with_people(s)
    content = csv_bytes(lab(["hb", "ค่าแปลกๆ"], (1, [13.1, 5]), (2, [12.4, 6])))
    r = s.sa.post("/api/upload", files={"file": ("เบื้องหลัง.csv", content)},
                  data={"round_id": s.r1, "hospital": "H01", "background": "true"})
    j = r.json()
    assert r.status_code == 200 and j["success"] and j["status"] == "processing", j
    done = _poll(s, j["upload_id"])
    assert done["success"] and done["status"] == "awaiting_review", done
    steps = {x["key"]: x for x in done["progress"]["steps"]}
    assert all(x["state"] in ("done", "skipped") for x in steps.values()), steps
    assert steps["read"]["state"] == steps["match"]["state"] == steps["store"]["state"] == "done", steps
    assert "รู้จักแล้ว 1 จาก 2" in steps["match"]["detail"], steps["match"]
    assert steps["ai_propose"]["state"] == "done", steps["ai_propose"]
    assert done["error_rows"] == 1 and s.checkup(1)["hb"] is not None, done
    assert s.sa.get("/api/upload/999999/progress").status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# M — กรอกผลตรวจทีละคน
# ═══════════════════════════════════════════════════════════════════════════

def emp_id(s, n):
    return s.h.one("select id from employees where cid=:c", c=cid(n))["id"]


@case("M01", "กรอกผลตรวจครั้งแรก สร้างแถว มีประวัติทุกช่องพร้อมชื่อผู้กรอก")
def m01(s):
    """กรอก hb, wbc, chest_xray → สร้างแถวผลตรวจ; ประวัติ 3 แถว reason manual_entry ผู้กรอก = 'sa'
    ค่าที่พิมพ์เก็บตามที่พิมพ์ (ไม่แปลงหน่วย)"""
    with_people(s)
    r = s.sa.put("/api/checkups", json={"round_id": s.r1, "employee_id": emp_id(s, 1),
                                        "values": {"hb": "14.5", "wbc": "8.4", "chest_xray": 1}})
    assert r.status_code == 200 and r.json()["created"] and r.json()["changed"] == 3, r.text
    c = s.checkup(1)
    assert (num(c["hb"]), num(c["wbc"]), c["chest_xray"]) == (14.5, 8.4, 1), c
    h = s.h.sql("select * from value_history where reason='manual_entry'")
    assert len(h) == 3 and {x["changed_by"] for x in h} == {"sa"}, h


@case("M02", "กรอกค่าเดิมซ้ำ ไม่มีประวัติปลอม")
def m02(s):
    """กรอกค่าเท่าเดิม (แม้เขียนต่างรูปแบบ 14.5 กับ 14.50) → changed 0 ไม่มีประวัติเพิ่ม"""
    with_people(s)
    body = {"round_id": s.r1, "employee_id": emp_id(s, 1), "values": {"hb": "14.5"}}
    s.sa.put("/api/checkups", json=body)
    body["values"] = {"hb": "14.50"}
    r = s.sa.put("/api/checkups", json=body)
    assert r.json()["changed"] == 0, r.text
    assert s.h.scalar("select count(*) from value_history") == 1


@case("M03", "แก้ค่า ประวัติ 1 แถว ค่าเก่าค่าใหม่ถูกต้อง")
def m03(s):
    """แก้ hb 14.5 → 15.0 → ประวัติเพิ่ม 1 แถว old=14.50 new=15.0"""
    with_people(s)
    body = {"round_id": s.r1, "employee_id": emp_id(s, 1), "values": {"hb": "14.5"}}
    s.sa.put("/api/checkups", json=body)
    body["values"] = {"hb": "15.0"}
    r = s.sa.put("/api/checkups", json=body)
    assert r.json()["changed"] == 1
    h = s.h.sql("select * from value_history order by id desc limit 1")[0]
    assert (h["old_value"], h["new_value"]) == ("14.50", "15.0"), h


@case("M04", "กรอกไม่ใช่ตัวเลข / รหัสผิด ถูกปฏิเสธ")
def m04(s):
    """hb='abc' → 400; chest_xray=5 → 400; ช่องที่ไม่มีอยู่ → 400 ไม่เขียนอะไรเลย"""
    with_people(s)
    base = {"round_id": s.r1, "employee_id": emp_id(s, 1)}
    for values in ({"hb": "abc"}, {"chest_xray": 5}, {"no_such": 1}):
        r = s.sa.put("/api/checkups", json={**base, "values": values})
        assert r.status_code == 400, (values, r.status_code, r.text)
    assert s.n_checkups() == 0 and s.h.scalar("select count(*) from value_history") == 0


@case("M05", "กรอกให้คนของอีกบริษัท ถูกปฏิเสธ")
def m05(s):
    """คนอยู่ทะเบียนบริษัท B แต่กรอกเข้ารอบของบริษัท A → 400"""
    with_people(s)
    co_b = s.company("บริษัท B", "0105500000002", ("ผลิต",))
    s.registry([HEAD, person(50)], company=co_b, name="B.csv")
    r = s.sa.put("/api/checkups", json={"round_id": s.r1, "employee_id": emp_id(s, 50), "values": {"hb": "14"}})
    assert r.status_code == 400, r.text


@case("M06", "ค่าว่างที่พิมพ์ = ล้างค่า มีประวัติ")
def m06(s):
    """ส่ง hb='' หลังเคยมีค่า → ค่าถูกล้าง ประวัติบันทึก new_value ว่าง"""
    with_people(s)
    body = {"round_id": s.r1, "employee_id": emp_id(s, 1), "values": {"hb": "14.5"}}
    s.sa.put("/api/checkups", json=body)
    body["values"] = {"hb": ""}
    r = s.sa.put("/api/checkups", json=body)
    assert r.json()["changed"] == 1 and s.checkup(1)["hb"] is None, (r.text, s.checkup(1))


@case("M07", "รายชื่อคนที่ยังกรอกได้ของรอบ")
def m07(s):
    """/api/rounds/{id}/people แสดงทุกคนในทะเบียนของบริษัทนั้น พร้อมบอกว่าใครมีแถวผลตรวจแล้ว"""
    with_people(s)
    s.sa.put("/api/checkups", json={"round_id": s.r1, "employee_id": emp_id(s, 1), "values": {"hb": "14"}})
    ppl = s.sa.get(f"/api/rounds/{s.r1}/people").json()
    assert len(ppl) == 5 and sum(1 for p in ppl if p["checkup_id"]) == 1, ppl


# ═══════════════════════════════════════════════════════════════════════════
# S — ภาพรวม ส่งรายงาน รับรองรอบ
# ═══════════════════════════════════════════════════════════════════════════

def loaded(s):
    with_people(s)
    s.results(lab(["hb", "wbc", "plt", "chest_xray", "ekg"],
                  (1, [14.2, 8383, 210186, 1, 2]), (2, [12.6, 4700, 300000, 2, 1]), (3, [13.0, 6000, 250000, 1, 1])))


@case("S01", "ภาพรวมของรอบ นับถูก")
def s01(s):
    """3 คนมีผล 2 คนไม่มี (5 ในทะเบียน) → people=3 (นับเฉพาะคนที่มีแถวผลตรวจ) เอกซเรย์ปกติ 2 ผิดปกติ 1 ไม่มีคำถามค้าง"""
    loaded(s)
    d = s.sa.get(f"/api/summary?round_id={s.r1}").json()
    assert d["people"] == 3, d["people"]
    f = {x["column"]: x for x in d["findings"]}["chest_xray"]
    assert (f["normal"], f["abnormal"]) == (2, 1), f
    assert d["open_work"]["reviews_total"] == 0 and d["open_work"]["conflicts"] == 0, d["open_work"]


@case("S02", "ภาพรวมเตือนงานค้าง")
def s02(s):
    """มีคำถามค้าง 1 และข้อขัดแย้ง 1 → ภาพรวมของรอบรายงานจำนวนตรงกัน"""
    with_people(s)
    s.results(lab(["hb", "รหัสภายใน"], (1, [14.0, "A"])), name="ก.csv")
    s.results(lab(["hb"], (1, [15.0])), name="ข.csv")
    d = s.sa.get(f"/api/summary?round_id={s.r1}").json()["open_work"]
    assert d["reviews_total"] == 1 and d["conflicts"] == 1, d


@case("S03", "ไฟล์ส่งออก: สองชีต หน่วยและรหัสถูกตามกรมฯ")
def s03(s):
    """ส่งรายงาน → ไฟล์ Excel 2 ชีต employees / employee_checkups; wbc/plt เป็น 10^3/µL;
    เอกซเรย์ 0/1; วันที่เป็นวันนัดของรอบ; ทุกคอลัมน์ผลตรวจอยู่ครบ"""
    import io
    import openpyxl
    from app.template import TEMPLATE_FIELDS
    loaded(s)
    r = s.sa.post("/api/summary/submit", json={"round_id": s.r1})
    assert r.status_code == 200, r.text
    dl = s.sa.get(f"/api/summary/download/{r.json()['id']}")
    wb = openpyxl.load_workbook(io.BytesIO(dl.content))
    assert wb.sheetnames == ["employees", "employee_checkups"], wb.sheetnames
    rows = list(wb["employee_checkups"].iter_rows(values_only=True))
    head = list(rows[0])
    result_cols = [f.column for f in TEMPLATE_FIELDS if f.group != "person"]
    assert head[:2] == ["citizen_id", "checkup_date"] and head[2:] == result_cols, head[:5]
    by = {r_[0]: dict(zip(head, r_)) for r_ in rows[1:]}
    p1 = by[cid(1)]
    assert p1["wbc"] == 8.38 and p1["plt"] == 210.19 and p1["chest_xray"] == 0 and p1["ekg"] == 1, p1
    assert p1["checkup_date"] == "2026-03-01"
    assert len(by) == 3, "only people with a results row are exported"


@case("S04", "รอบที่ไม่มีผลตรวจ ส่งไม่ได้")
def s04(s):
    """ส่งรายงานรอบว่าง → 400"""
    with_people(s)
    assert s.sa.post("/api/summary/submit", json={"round_id": s.r1}).status_code == 400


@case("S05", "ส่งรายงานตอนยังมีงานค้าง ถูกบล็อก ต้องยืนยันชัดเจน")
def s05(s):
    """มีคำถามค้าง 1 ข้อ → ส่งรายงานถูกปฏิเสธ (409 รหัส open_work พร้อมจำนวน) ไม่มีการบันทึกการส่ง
    ยืนยัน confirm_open_work → ส่งได้ และบันทึกไว้ว่าส่งทั้งที่ยังค้าง พร้อมชื่อผู้ยืนยันจากบัญชี"""
    with_people(s)
    s.results(lab(["hb", "รหัสภายใน"], (1, [14.0, "A"])))
    r = s.sa.post("/api/summary/submit", json={"round_id": s.r1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "open_work", r.text
    assert r.json()["detail"]["open_work"]["reviews_total"] == 1
    assert s.h.scalar("select count(*) from report_submissions") == 0
    r = s.sa.post("/api/summary/submit", json={"round_id": s.r1, "confirm_open_work": True})
    assert r.status_code == 200, r.text
    sm = s.h.one("select summary from report_submissions")["summary"]
    assert sm["sent_with_open_work"] is True and sm["confirmed_by"] == "sa", sm


@case("S08", "ส่งรายงานตอนไม่มีงานค้าง ส่งได้เลย และบันทึกว่าไม่ได้ส่งทั้งที่ค้าง")
def s08(s):
    """ไม่มีคำถาม/ข้อขัดแย้ง → ส่งได้โดยไม่ต้องยืนยัน sent_with_open_work เป็นเท็จ"""
    loaded(s)
    r = s.sa.post("/api/summary/submit", json={"round_id": s.r1})
    assert r.status_code == 200, r.text
    sm = s.h.one("select summary from report_submissions")["summary"]
    assert sm["sent_with_open_work"] is False and sm["confirmed_by"] is None, sm


@case("S09", "ข้อขัดแย้งที่ค้างก็บล็อกการส่งเหมือนคำถาม")
def s09(s):
    """ไม่มีคำถาม แต่มีข้อขัดแย้งค้าง → ส่งไม่ได้จนกว่าจะตัดสิน; ตัดสินแล้วส่งได้"""
    conflict_setup(s)
    assert s.sa.post("/api/summary/submit", json={"round_id": s.r1}).status_code == 409
    s.sa.post(f"/api/files/{s.fid}/conflicts/accept-all", json={})
    assert s.sa.post("/api/summary/submit", json={"round_id": s.r1}).status_code == 200


@case("S06", "รับรองรอบ และยกเลิกการรับรอง")
def s06(s):
    """approve → บันทึกผู้รับรองจากบัญชี; ยกเลิก → ล้างผู้รับรอง"""
    r = s.sa.post(f"/api/rounds/{s.r1}/approve", json={"approved": True}).json()
    assert r["is_approved"] and r["approved_by"] == "sa", r
    r = s.sa.post(f"/api/rounds/{s.r1}/approve", json={"approved": False}).json()
    assert not r["is_approved"] and r["approved_by"] is None, r


# ═══════════════════════════════════════════════════════════════════════════
# G — ตั้งค่าเริ่มต้น: สถานประกอบการ การสำรวจ รอบ
# ═══════════════════════════════════════════════════════════════════════════

@case("G01", "รอบตรวจซ้ำ (การสำรวจ+ประเภท+วันนัดเดียวกัน) ถูกปฏิเสธ")
def g01(s):
    """สร้างรอบเดิมซ้ำ → 409"""
    sv = s.h.scalar("select survey_id from employee_checkup_batches where id=:i", i=s.r1)
    r = s.staff.post("/api/rounds", json={"survey_id": sv, "checkup_type": 2, "appoint_date": "2026-03-01"})
    assert r.status_code == 409, r.text


@case("G02", "ผู้ดูแลส่วนกลางสร้างรอบตรวจได้")
def g02(s):
    """ผู้ดูแลส่วนกลาง (ไม่สังกัดหน่วยบริการ) สร้างรอบ → ต้องสำเร็จ ไม่ 500"""
    r = s.sa.post("/api/surveys", json={"company_id": s.co, "survey_date": "2026-02-01"})
    r = s.sa.post("/api/rounds", json={"survey_id": r.json()["id"], "checkup_type": 2, "appoint_date": "2026-05-01"})
    assert r.status_code == 201, f"{r.status_code}: {r.text[:200]}"


@case("G03", "เลขนิติบุคคลต้อง 13 หลัก")
def g03(s):
    """เลขนิติบุคคลสั้นเกิน → 422 ไม่สร้างสถานประกอบการ"""
    r = s.sa.post("/api/companies", json={"juristic_id": "123", "name": "X"})
    assert r.status_code == 422, r.status_code


@case("G04", "แผนกชื่อซ้ำในบริษัทเดียวกัน")
def g04(s):
    """เพิ่มแผนก 'ผลิต' ซ้ำ → ปฏิเสธอย่างสุภาพ (ไม่ 500)"""
    r = s.sa.post(f"/api/companies/{s.co}/departments", json={"name": "ผลิต"})
    assert r.status_code in (400, 409, 422), r.status_code


@case("G05", "ประเภทการตรวจที่ไม่มีอยู่")
def g05(s):
    """สร้างรอบด้วยประเภท 999 → 404"""
    sv = s.h.scalar("select survey_id from employee_checkup_batches where id=:i", i=s.r1)
    assert s.staff.post("/api/rounds", json={"survey_id": sv, "checkup_type": 999, "appoint_date": "2026-06-01"}).status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# X — ข้ามส่วน: ความจำต่อหน่วยบริการ และหน้าดูข้อมูล
# ═══════════════════════════════════════════════════════════════════════════

@case("X01", "สิ่งที่ระบบเรียนรู้จำแยกตามหน่วยบริการ")
def x01(s):
    """สอนที่ H01 ว่า 'รหัสภายใน' ไม่ใช่ผลตรวจ → H01 ไม่ถามอีก แต่ H02 ยังถาม"""
    with_people(s)
    rows = lab(["รหัสภายใน"], (1, ["A"]), (2, ["B"]))
    s.results(rows, hospital="H01")
    q = s.reviews(s.fid)[0]
    s.decide(s.fid, [{"review_id": q["id"], "action": "ignore"}])
    s.results(rows, name="h01ซ้ำ.csv", hospital="H01", round_id=s.r2)
    assert not s.reviews(), "H01 must not be asked again"
    s.results(rows, name="h02.csv", hospital="H02", round_id=s.r2)
    assert [x["kind"] for x in s.reviews(s.fid)] == ["mapping"], "H02 has learned nothing and must ask"


@case("X02", "หน้าข้อมูลพนักงานเห็นผลตรวจที่นำเข้า")
def x02(s):
    """/api/employees แสดงคนพร้อมผลตรวจ; /api/stats นับถูก"""
    loaded(s)
    r = s.sa.get("/api/employees")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["employees"] if isinstance(body, dict) and "employees" in body else body
    assert len(rows) >= 3, body if len(str(body)) < 400 else str(body)[:400]


@case("X03", "ส่งออกจากหน้าข้อมูลพนักงานเปิดได้")
def x03(s):
    """/api/export ให้ไฟล์ Excel ที่เปิดได้"""
    import io
    import openpyxl
    loaded(s)
    r = s.sa.get(f"/api/export?round_id={s.r1}")
    assert r.status_code == 200, r.status_code
    openpyxl.load_workbook(io.BytesIO(r.content))


@case("X04", "แก้ไฟล์แล้วอัปใหม่ ปิดรายการผิดของไฟล์เก่าได้ และปิดแล้วไม่กลับมา")
def x04(s):
    """อัปไฟล์ที่มีเลขบัตรผิด 1 แถว (ค้าง 'cid') แล้วอัปไฟล์ที่แก้แล้ว → ระบบบอกไม่ได้ว่ารายการเก่า 'ถูกแก้แล้ว'
    (เลขผิดไม่โยงกับใคร) จึงยังเห็นอยู่ แต่คนกด 'ปิดรายการ' ได้ → รายการหาย ไฟล์เก่า 'เสร็จ' ผู้ปิดจากบัญชี
    และปิดแล้วไม่ถูกเปิดกลับมาเมื่อไฟล์นั้นถูกประมวลผลซ้ำ"""
    with_people(s)
    bad = lab(["hb", "รหัสภายใน"], (1, [14.0, "A"]), (2, [13.0, "B"]))
    bad[2][0] = bad_cid(2)
    s.results(bad, name="ผิด.csv")
    old = s.fid
    kinds = s.kinds(old)
    assert "cid" in kinds, kinds
    s.results(lab(["hb"], (1, [14.0]), (2, [13.0])), name="แก้แล้ว.csv")
    assert s.checkup(2), "the corrected file must store the person"

    cid_item = [r for r in s.reviews(old) if r["kind"] == "cid"][0]
    # it cannot be answered, only closed
    s.decide(old, [{"review_id": cid_item["id"], "action": "ignore"}], expect=400)
    s.decide(old, [{"review_id": cid_item["id"], "action": "dismiss"}])
    assert not [r for r in s.reviews(old) if r["kind"] == "cid"]
    who = s.h.scalar("select decided_by from pending_reviews where id=:i", i=cid_item["id"])
    assert who == "sa", who

    # answering the file's other question re-reads the file; the closed item must stay closed
    q = [r for r in s.reviews(old) if r["kind"] == "mapping"][0]
    s.decide(old, [{"review_id": q["id"], "action": "ignore"}])
    assert not [r for r in s.reviews(old) if r["kind"] == "cid"], "a closed item came back"
    assert s.file(old)["status"] == "completed", s.file(old)["status"]


@case("X05", "ทะเบียน: ปิดรายการเลขบัตรผิดหลังแก้ไฟล์ ปิดแล้วไม่กลับมา")
def x05(s):
    """ทะเบียนมีเลขบัตรผิด 1 แถว → ปิดรายการ → ไฟล์เสร็จ และอัปไฟล์เดิมซ้ำแล้วตอบอย่างอื่น รายการที่ปิดไม่กลับมา"""
    rows = [HEAD + ["รหัสภายใน"], person(1) + ["E1"], [bad_cid(2), "ชื่อ2", "สกุล2", "ผลิต", "E2"]]
    s.registry(rows)
    it = [r for r in s.reviews(1) if r["kind"] == "cid"][0]
    s.decide(1, [{"review_id": it["id"], "action": "dismiss"}])
    q = [r for r in s.reviews(1) if r["kind"] == "mapping"][0]
    s.decide(1, [{"review_id": q["id"], "action": "ignore"}])
    assert not [r for r in s.reviews(1) if r["kind"] == "cid"], "a closed item came back"
    assert s.file(1)["status"] == "completed"


@case("X06", "ปิดรายการที่ตอบได้ ถูกปฏิเสธ")
def x06(s):
    """dismiss ใช้ได้เฉพาะรายการที่ไม่มีคำตอบให้ (เลขบัตรผิด ฯลฯ) ห้ามใช้ปิดคำถามที่ต้องตัดสินใจ"""
    with_people(s)
    s.results(lab(["รหัสภายใน"], (1, ["A"])))
    q = s.reviews(s.fid)[0]
    assert q["kind"] == "mapping"
    s.decide(s.fid, [{"review_id": q["id"], "action": "dismiss"}], expect=400)


@case("S07", "รอบที่รับรองแล้ว ผลเปลี่ยน → ปลดการรับรองอัตโนมัติ")
def s07(s):
    """รับรองรอบแล้ว: อัปผลใหม่ที่เพิ่มค่า → ปลดการรับรอง (ข้อมูลอยู่ครบ) และบอกในผลการอัป;
    อัปไฟล์เดิมซ้ำที่ไม่เปลี่ยนอะไร → ยังรับรองอยู่"""
    with_people(s)
    s.results(lab(["hb"], (1, [14.0])), name="แรก.csv")
    s.sa.post(f"/api/rounds/{s.r1}/approve", json={"approved": True})

    def approved():
        return s.h.one("select is_approved, approved_by, approved_at from employee_checkup_batches where id=:i", i=s.r1)

    out = s.results(lab(["hb"], (1, [14.0])), name="ซ้ำ.csv")          # nothing new
    assert approved()["is_approved"] and not out["stats"].get("approval_revoked"), out["stats"]
    out = s.results(lab(["hb"], (2, [13.0])), name="เพิ่ม.csv")          # a new value
    a = approved()
    assert not a["is_approved"] and a["approved_by"] is None and a["approved_at"] is None, a
    assert out["stats"].get("approval_revoked") is True
    assert s.n_checkups() == 2, "withdrawing an approval must not lose data"


@case("S10", "ข้อขัดแย้งเปลี่ยนค่า → ปลดการรับรอง; เก็บค่าเดิม → ไม่ปลด")
def s10(s):
    """ตัดสิน keep ไม่กระทบการรับรอง; replace เปลี่ยนค่า จึงปลดการรับรอง"""
    conflict_setup(s)
    cs = {c["column"]: c for c in s.sa.get("/api/conflicts?status=open").json()}
    s.sa.post(f"/api/rounds/{s.r1}/approve", json={"approved": True})
    s.sa.post(f"/api/conflicts/{cs['wbc']['id']}/resolve", json={"action": "keep"})
    assert s.h.scalar("select is_approved from employee_checkup_batches where id=:i", i=s.r1) is True
    s.sa.post(f"/api/conflicts/{cs['hb']['id']}/resolve", json={"action": "replace"})
    assert s.h.scalar("select is_approved from employee_checkup_batches where id=:i", i=s.r1) is False


@case("S11", "กรอกมือแก้ค่า → ปลดการรับรอง; กรอกค่าเดิม → ไม่ปลด")
def s11(s):
    """แก้ hb ในรอบที่รับรองแล้ว → ปลดการรับรองและบอกในคำตอบ; ส่งค่าเท่าเดิมอีกครั้งไม่ปลด"""
    with_people(s)
    body = {"round_id": s.r1, "employee_id": emp_id(s, 1), "values": {"hb": "14.5"}}
    s.sa.put("/api/checkups", json=body)
    s.sa.post(f"/api/rounds/{s.r1}/approve", json={"approved": True})
    r = s.sa.put("/api/checkups", json=body)                           # same value
    assert r.json()["changed"] == 0 and not r.json()["approval_revoked"]
    assert s.h.scalar("select is_approved from employee_checkup_batches where id=:i", i=s.r1) is True
    body["values"] = {"hb": "15.0"}
    r = s.sa.put("/api/checkups", json=body)
    assert r.json()["approval_revoked"] is True
    assert s.h.scalar("select is_approved from employee_checkup_batches where id=:i", i=s.r1) is False
