/*
 * review-wizard.js
 * ================
 * The "งานที่ต้องตรวจ" one-question-at-a-time wizard, factored out of
 * import_reviews.html so it can be mounted twice: on the standalone /reviews
 * page, and inside the round dashboard's review panel (CONTEXT.md: the panel
 * opens automatically after an upload, but must also be reachable any other
 * time from the dashboard — a person must never lose access to an open review
 * just because they closed the panel).
 *
 * Every decision rule below is unchanged from the page this replaces. See
 * import_reviews.html's own history for why each one is the way it is.
 *
 * Usage: mountReviewWizard(containerEl, { extraQuery: 'round_id=5', onChange() {} })
 * `extraQuery` scopes which reviews this instance sees (round dashboard) or is
 * empty (the standalone page sees everything). `onChange` fires after anything
 * is saved, so the host page can refresh its own badge/count.
 */
function mountReviewWizard(root, opts) {
    opts = opts || {};
    const extraQuery = opts.extraQuery ? '&' + opts.extraQuery : '';
    const onChange = opts.onChange || function () {};

    root.innerHTML = `
        <div class="tabs" id="rwTabs">
            <button class="tab on" data-pane="reviews">คำถามรอตอบ <span class="pill" id="rwReviewCount" hidden></span></button>
            <button class="tab" data-pane="conflicts">ข้อมูลขัดแย้ง <span class="pill" id="rwConflictCount" hidden></span></button>
        </div>

        <section id="rwPaneReviews">
            <div id="rwWizard" hidden>
                <div class="wiz-bar">
                    <div class="wiz-progress"><div class="wiz-progress-fill" id="rwWizFill"></div></div>
                    <div class="wiz-count muted" id="rwWizCount"></div>
                </div>
                <div class="card wiz-card">
                    <div class="wiz-source muted" id="rwWizSource"></div>
                    <h2 class="wiz-q" id="rwWizTitle"></h2>
                    <div class="wiz-why" id="rwWizWhy"></div>
                    <div class="wiz-body" id="rwWizBody"></div>
                    <div class="wiz-answer" id="rwWizAnswer"></div>
                    <div class="wiz-foot">
                        <button class="btn" id="rwWizBack">← ย้อนกลับ</button>
                        <span class="grow"></span>
                        <button class="btn" id="rwWizSkip">ข้ามไว้ก่อน</button>
                        <button class="btn btn-primary" id="rwWizNext">ตอบข้อนี้ →</button>
                    </div>
                </div>
                <details class="card wiz-detail" id="rwWizEvidence" hidden>
                    <summary>ดูหลักฐานทั้งหมดของข้อนี้</summary>
                    <div id="rwWizEvidenceBody"></div>
                </details>
            </div>

            <div id="rwWizDone" class="card center" hidden>
                <div class="empty-mark">✓</div>
                <div id="rwWizDoneTitle" style="font-size:17px;font-weight:600;"></div>
                <div class="muted" id="rwWizDoneNote" style="margin:6px 0 16px;"></div>
                <div id="rwWizDoneList" class="wiz-summary"></div>
                <div style="margin-top:18px;">
                    <button class="btn" id="rwWizRestart">ดูคำถามอีกครั้ง</button>
                    <button class="btn btn-primary" id="rwWizSave">บันทึกคำตอบทั้งหมด</button>
                </div>
            </div>

            <div id="rwSkippedBox" class="card" hidden>
                <h2 style="margin-top:0;font-size:16px;">สิ่งที่ตอบจากหน้านี้ไม่ได้</h2>
                <p class="muted" style="margin-bottom:10px;">รายการเหล่านี้ไม่มีคำถามให้ตอบ เพราะต้องแก้ที่ต้นทาง แล้วนำเข้าไฟล์ใหม่</p>
                <div id="rwSkippedList"></div>
            </div>

            <div id="rwReviewEmpty" class="card center" hidden>
                <div class="empty-mark">✓</div>
                <div>ไม่มีคำถามรอตอบ</div>
                <div class="muted">ทุกค่าที่นำเข้ามาแล้วถูกบันทึกหรือถูกตัดสินไปหมดแล้ว</div>
            </div>
        </section>

        <section id="rwPaneConflicts" hidden>
            <div id="rwConflictList"></div>
            <div id="rwConflictEmpty" class="card center" hidden>
                <div class="empty-mark">✓</div>
                <div>ไม่มีข้อมูลขัดแย้ง</div>
                <div class="muted">ค่าที่ส่งมาซ้ำตรงกับค่าที่เก็บไว้ทั้งหมด</div>
            </div>
        </section>`;

    const ANSWERABLE = ['mapping', 'identity', 'comment', 'department',
                        'unregistered_person', 'department_change', 'which_department',
                        'unknown_department', 'registry_value'];
    const KIND_LABEL = {cid: 'เลขบัตรประชาชนไม่ถูกต้อง', profile: 'อ่านโครงไฟล์ไม่ออก',
                        value: 'ค่าที่อ่านไม่ได้',
                        row_missing_department: 'แถวในไฟล์ทะเบียนไม่ได้เขียนแผนกไว้'};
    const SKIP_FIX = {cid: 'แก้เลขบัตรในไฟล์ต้นฉบับให้ถูกต้อง แล้วนำเข้าไฟล์ใหม่',
                      row_missing_department: 'เติมชื่อแผนกให้แถวเหล่านี้ในไฟล์ทะเบียน แล้วนำเข้าใหม่'};
    const ROLE_TH = {first_name: 'ชื่อ', last_name: 'นามสกุล', full_name: 'ชื่อ-สกุล',
                     department_id: 'แผนก', visit_date: 'วันที่ตรวจ', cid: 'เลขบัตรประชาชน'};
    const TITLE_DATE = '__report_title_date__';

    let QUESTIONS = [], SKIPPED = [], FILES = {}, templateColumns = [], registryColumns = [];
    const companyColumnsCache = {};   // company_id -> [{id, name, kind, unit}]
    async function companyColumns(companyId) {
        if (!companyId) return [];
        if (!companyColumnsCache[companyId]) companyColumnsCache[companyId] = await api(`/api/companies/${companyId}/extra-columns`);
        return companyColumnsCache[companyId];
    }
    let idx = 0;
    const answers = {};
    const $ = id => root.querySelector('#' + id);
    const key = q => q.kind === 'identity' ? `${q.id}:${q.role}` : String(q.id);

    async function load() {
        const [reviews, columns, regColumns, files] = await Promise.all([
            api('/api/reviews?status=open&limit=5000' + extraQuery),
            templateColumns.length ? templateColumns : api('/api/template/columns'),
            registryColumns.length ? registryColumns : api('/api/registry/columns'),
            api('/api/upload-logs'),
        ]);
        templateColumns = columns;
        registryColumns = regColumns;
        FILES = Object.fromEntries(files.map(f => [String(f.id), f]));

        const groups = {};
        QUESTIONS = []; SKIPPED = [];
        for (const r of reviews) {
            if (!ANSWERABLE.includes(r.kind)) { SKIPPED.push(r); continue; }
            if (r.kind === 'comment' || r.kind === 'unregistered_person') {
                const k = r.kind === 'comment'
                    ? r.payload.column + '|' + String(r.payload.text || '').trim().toLowerCase()
                    : 'person|' + r.payload.cid + '|' + (r.payload.known_departments || []).join(',');
                if (groups[k]) { groups[k].group.push(r); continue; }
                groups[k] = Object.assign({}, r, {group: [r]});
                QUESTIONS.push(groups[k]);
            } else if (r.kind === 'identity') {
                for (const role of (r.payload.missing || [])) QUESTIONS.push(Object.assign({}, r, {role}));
            } else {
                QUESTIONS.push(r);
            }
        }
        const order = {unknown_department: 0, unregistered_person: 1, department_change: 2, which_department: 2,
                       identity: 3, department: 4, mapping: 5, registry_value: 6, comment: 7};
        QUESTIONS.sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9));

        const pill = $('rwReviewCount');
        pill.textContent = QUESTIONS.length; pill.hidden = !QUESTIONS.length;
        $('rwReviewEmpty').hidden = QUESTIONS.length > 0 || SKIPPED.length > 0;
        renderSkipped();
        idx = 0;
        if (QUESTIONS.length) { $('rwWizDone').hidden = true; show(); } else finish();
        onChange();
    }

    function renderSkipped() {
        $('rwSkippedBox').hidden = !SKIPPED.length;
        if (!SKIPPED.length) return;
        const byKind = {};
        SKIPPED.forEach(r => (byKind[r.kind] = byKind[r.kind] || []).push(r));
        $('rwSkippedList').innerHTML = Object.entries(byKind).map(([kind, rows]) => {
            const where = SKIP_FIX[kind] || 'แก้ที่ไฟล์ต้นฉบับ แล้วนำเข้าใหม่';
            const ex = rows.slice(0, 6).map(r =>
                `<code>${esc(r.payload.raw_cid || r.payload.raw || r.payload.problem
                             || (r.payload.row ? 'แถว ' + r.payload.row : ''))}</code>`).join(' ');
            return `<div class="skip-row">
                <div><b>${esc(KIND_LABEL[kind] || kind)}</b> · ${rows.length} รายการ
                     <div class="muted">${ex}${rows.length > 6 ? ' …' : ''}</div></div>
                <div class="skip-side"><div class="muted">${esc(where)}</div>
                    <button class="btn btn-sm" data-dismiss-kind="${esc(kind)}">แก้แล้ว — ปิดรายการเหล่านี้</button></div></div>`;
        }).join('');
        root.querySelectorAll('[data-dismiss-kind]').forEach(b =>
            b.addEventListener('click', () => dismissKind(b.dataset.dismissKind)));
    }

    const samples = (list, max) =>
        (list || []).slice(0, max).map(x => `<code>${esc(x)}</code>`).join(' ') || '<span class="muted">—</span>';

    let currentCompanyCols = [];

    async function show() {
        const q = QUESTIONS[idx];
        $('rwWizard').hidden = false;
        $('rwWizDone').hidden = true;

        $('rwWizCount').textContent =
            `ข้อ ${idx + 1} จาก ${QUESTIONS.length} · ตอบแล้ว ${Object.keys(answers).length}`;
        $('rwWizFill').style.width = `${(idx / QUESTIONS.length) * 100}%`;

        const f = FILES[String(q.source_file_id)];
        $('rwWizSource').textContent = f
            ? `จากไฟล์ ${f.filename}${f.created_at ? ' · นำเข้า ' + new Date(f.created_at).toLocaleString('th-TH') : ''}`
            : `จากไฟล์ #${q.source_file_id}`;

        currentCompanyCols = q.kind === 'mapping' ? await companyColumns(q.payload.company_id) : [];
        if (QUESTIONS[idx] !== q) return;   // moved on while this was loading
        const view = RENDER[q.kind](q);
        $('rwWizTitle').innerHTML = view.title;
        $('rwWizWhy').innerHTML = view.why || '';
        $('rwWizBody').innerHTML = view.body || '';
        $('rwWizAnswer').innerHTML = view.answer;
        $('rwWizEvidence').hidden = !view.evidence;
        if (view.evidence) $('rwWizEvidenceBody').innerHTML = view.evidence;

        if (view.onShow) view.onShow();
        restore(q);
        $('rwWizBack').disabled = idx === 0;
        $('rwWizNext').textContent = idx === QUESTIONS.length - 1 ? 'ตอบข้อนี้ แล้วดูสรุป →' : 'ตอบข้อนี้ →';
    }

    const RENDER = {
        unregistered_person(q) {
            const p = q.payload, parts = String(p.name_in_file || '').split(' ');
            const known = p.known_departments || [];
            const deptOptions = (known.length
                ? known.map(d => `<option value="${esc(d)}" ${d === p.department_in_file ? 'selected' : ''}>${esc(d)}</option>`).join('')
                : '') || '<option value="">— ไม่มีแผนกในสถานประกอบการนี้ —</option>';
            return {
                title: 'ไฟล์มีผลตรวจของคนที่ยังไม่อยู่ในทะเบียนพนักงาน',
                why: `<span class="review-warn">ผลตรวจของคนนี้ยังไม่ถูกบันทึก จนกว่าจะรู้ว่าเป็นใคร</span>`
                     + (q.group && q.group.length > 1
                        ? `<div class="muted" style="margin-top:6px;">พบคนนี้ใน ${q.group.length} ไฟล์ · ตอบครั้งเดียว ใช้กับทุกไฟล์</div>` : ''),
                body: `<div class="kv">
                    <div class="k">เลขบัตรประชาชน</div><div class="v mono">${esc(p.cid)}</div>
                    <div class="k">ชื่อที่เขียนในไฟล์</div><div class="v">${esc(p.name_in_file) || '<span class="muted">ไม่มี</span>'}</div>
                    <div class="k">แผนกที่เขียนในไฟล์</div><div class="v">${esc(p.department_in_file) || '<span class="muted">ไฟล์นี้ไม่มีคอลัมน์แผนก</span>'}</div></div>`,
                answer: `<div class="wiz-choices">
                    <div class="ask-form">
                        <div class="ask-lead"><b>เพิ่มคนนี้เข้าทะเบียนพนักงาน แล้วบันทึกผลตรวจ</b>
                            <span class="muted">ตรวจชื่อให้ถูก แล้วเลือกแผนก ถ้ายังไม่แน่ใจว่าเป็นใคร กด “ข้ามไว้ก่อน”</span></div>
                        <div class="extra-row">
                            <label class="choice-field"><span>ชื่อ</span>
                                <input id="rwSnFirst" placeholder="ชื่อ" value="${esc(parts[0] || '')}"></label>
                            <label class="choice-field"><span>นามสกุล</span>
                                <input id="rwSnLast" placeholder="นามสกุล" value="${esc(parts.slice(1).join(' '))}"></label>
                        </div>
                        <label class="choice-field">
                            <span>แผนกที่จะเพิ่มคนนี้เข้าไป</span>
                            <select id="rwSnDept">${deptOptions}</select>
                        </label>
                    </div></div>`,
            };
        },

        which_department(q) {
            const p = q.payload;
            return {
                title: 'คนนี้อยู่ในทะเบียนหลายแผนก ผลตรวจในไฟล์เป็นของแผนกไหน',
                why: `<span class="review-warn">ผลตรวจ ${Number(p.values_waiting || 0)} ค่าของคนนี้รออยู่ ไฟล์ไม่ได้บอกแผนก ระบบจึงไม่เลือกให้</span>`,
                body: `<div class="kv"><div class="k">เลขบัตรประชาชน</div><div class="v mono">${esc(p.cid)}</div>
                       <div class="k">อยู่ในแผนก</div><div class="v">${(p.candidates || []).map(esc).join(' · ')}</div></div>`,
                answer: `<div class="wiz-choices"><div class="ask-form">
                    <label class="choice-field"><span>ผลตรวจในไฟล์นี้เป็นของแผนกไหน <b class="req">*</b></span>
                    <select id="rwPickDept"><option value="">— เลือกแผนก —</option>
                        ${(p.candidates || []).map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join('')}</select></label>
                    </div></div>`,
            };
        },

        department_change(q) {
            const p = q.payload;
            return {
                title: 'ไฟล์บอกแผนกไม่ตรงกับทะเบียน',
                why: `<span class="review-warn">ผลตรวจ ${Number(p.values_waiting || 0)} ค่าของคนนี้รออยู่ จนกว่าจะรู้ว่าอันไหนถูก</span>`,
                body: `<div class="compare">
                        <div class="compare-side"><div class="muted">ในทะเบียนพนักงาน</div><b>${esc(p.department_in_register)}</b></div>
                        <div class="compare-vs">≠</div>
                        <div class="compare-side"><div class="muted">ในไฟล์ผลตรวจ</div><b>${esc(p.department_in_file)}</b></div>
                       </div>
                       <div class="muted" style="margin-top:8px;">เลขบัตร ${esc(p.cid)}</div>`,
                answer: `<div class="wiz-choices">
                    <label class="choice"><input type="radio" name="rwAns" value="move_department">
                        <span><b>ย้ายแผนกจริง</b>
                        <span class="muted">เปิดทะเบียนในแผนกใหม่ ประวัติในแผนกเดิมยังอยู่ที่เดิม</span></span></label>
                    <label class="choice"><input type="radio" name="rwAns" value="use_register">
                        <span><b>ไฟล์เขียนผิด ใช้แผนกในทะเบียน</b>
                        <span class="muted">บันทึกผลไว้ที่แผนกเดิม</span></span></label></div>`,
            };
        },

        unknown_department(q) {
            const p = q.payload, known = p.known_departments || [];
            return {
                title: `ไฟล์ทะเบียนมีแผนก “${esc(p.department_in_file)}” ที่ยังไม่มีในสถานประกอบการนี้`,
                why: '<span class="review-warn">คนในแผนกนี้ยังไม่ถูกบันทึกเข้าทะเบียน จนกว่าจะรู้ว่าแผนกนี้มีจริงไหม</span>',
                body: `<div class="kv">
                    <div class="k">แผนกที่มีอยู่แล้ว</div>
                    <div class="v">${known.length ? known.map(esc).join(' · ') : '<span class="muted">ยังไม่มีแผนกเลย</span>'}</div>
                    <div class="k">เลขบัตรของคนแรกที่อยู่แผนกนี้</div><div class="v mono">${esc(p.cid)}</div></div>`,
                answer: `<div class="wiz-choices">
                    <div class="ask-form">
                        <div class="ask-lead"><b>เพิ่มแผนก “${esc(p.department_in_file)}” เข้าสถานประกอบการนี้</b>
                        <span class="muted">ใช้เมื่อเป็นแผนกจริงที่ยังไม่ได้ลงทะเบียนไว้
                        — ถ้าเป็นการพิมพ์ชื่อแผนกผิด ให้กด “ข้ามไว้ก่อน” แล้วแก้ชื่อในไฟล์ แล้วนำเข้าใหม่</span></div>
                    </div></div>`,
            };
        },

        registry_value(q) {
            const p = q.payload;
            return {
                title: `ทะเบียนกับไฟล์เขียน “${esc(p.header || p.column)}” ไม่ตรงกัน`,
                why: `<span class="muted">เลขบัตร ${esc(p.cid)} · ค่าเดิมยังอยู่จนกว่าจะมีคนตัดสิน</span>`,
                body: `<div class="compare">
                    <div class="compare-side"><div class="muted">ในทะเบียนตอนนี้</div><b>${esc(p.current)}</b></div>
                    <div class="compare-vs">≠</div>
                    <div class="compare-side"><div class="muted">ในไฟล์ที่เพิ่งนำเข้า</div><b>${esc(p.raw)}</b></div></div>`,
                answer: `<div class="wiz-choices">
                    <label class="choice"><input type="radio" name="rwAns" value="replace">
                        <span><b>ใช้ค่าใหม่จากไฟล์</b><span class="muted">${esc(p.raw)}</span></span></label>
                    <label class="choice"><input type="radio" name="rwAns" value="keep">
                        <span><b>เก็บค่าเดิมในทะเบียน</b><span class="muted">${esc(p.current)}</span></span></label></div>`,
            };
        },

        identity(q) {
            const p = q.payload, role = q.role;
            const opts = (p.candidates || []).map(c => c.header === TITLE_DATE
                ? `<option value="${esc(c.header)}">วันที่ในหัวรายงาน (${esc(c.date)})</option>`
                : `<option value="${esc(c.header)}">${esc(c.header)}${(c.samples || []).length ? ' — เช่น ' + esc((c.samples || []).slice(0, 2).join(', ')) : ''}</option>`).join('');
            return {
                title: `ระบบหาคอลัมน์ “${esc(ROLE_TH[role] || role)}” ในไฟล์ไม่เจอ`,
                why: 'ระบบไม่เดาคอลัมน์ที่บอกว่าใครเป็นใคร เพราะเดาผิดแล้วผลตรวจจะไปอยู่กับคนผิด',
                body: `<div class="muted">sheet ${esc(p.sheet)} · ${esc(p.reason || '')}</div>`,
                answer: `<div class="wiz-choices"><label class="choice-field">
                    <span>คอลัมน์ไหนในไฟล์คือ “${esc(ROLE_TH[role] || role)}”</span>
                    <select id="rwIdPick"><option value="">— เลือกคอลัมน์ —</option>${opts}</select></label></div>`,
            };
        },

        department(q) {
            const p = q.payload;
            return {
                title: `แผนก “${esc(p.name)}” ยังไม่มีรหัส`,
                why: `มีพนักงาน ${Number(p.count || 0)} คนอยู่ในแผนกนี้ · ตอบครั้งเดียว ระบบจะจำไว้ให้หน่วยบริการนี้`,
                answer: `<div class="wiz-choices"><label class="choice-field">
                    <span>รหัสแผนก (ตัวอักษรอังกฤษ/ตัวเลข)</span>
                    <input id="rwDeptCode" placeholder="เช่น QC หรือ PROD-01"></label></div>`,
            };
        },

        comment(q) {
            const p = q.payload, a = p.proposal || {}, b = p.check || {};
            const v = x => x.value === 1 ? '<span class="tag ok">ปกติ</span>'
                : x.value === 2 ? '<span class="tag bad">ผิดปกติ</span>' : '<span class="tag warn">ไม่แน่ใจ</span>';
            return {
                title: `ข้อความ “${esc(p.text)}” หมายถึงปกติหรือผิดปกติ`,
                why: `พบในช่อง ${esc(p.column)} ของ ${q.group.length} คน · ตอบครั้งเดียว ใช้กับทุกคนที่มีข้อความนี้`,
                answer: `<div class="wiz-choices">
                    <label class="choice"><input type="radio" name="rwAns" value="1"><span><b>ปกติ</b></span></label>
                    <label class="choice"><input type="radio" name="rwAns" value="2"><span><b>ผิดปกติ</b></span></label></div>`,
                evidence: `<div class="review-grid">
                    <div><b>AI ตัวที่ 1</b> ${a.value !== undefined ? v(a) : '—'}<br><span class="muted">${esc(a.reason || '')}</span></div>
                    <div><b>AI ตัวที่ 2</b> ${b.value !== undefined ? v(b) : '—'}<br><span class="muted">${esc(b.reason || '')}</span></div>
                    <div><b>ตรงกันไหม</b> ${a.value !== undefined && a.value === b.value
                        ? '<span class="tag ok">ตรงกัน</span>' : '<span class="tag warn">ไม่ตรงกัน</span>'}</div></div>`,
            };
        },

        mapping(q) {
            const p = q.payload, prop = p.proposal || {}, ver = p.verification || {};
            // a wide file's header carries its unit in brackets ("ค่าเหล็กในเลือด (µg/dL)") and
            // the payload's unit is empty then: a new company column should start from that
            // unit and the bare name, or it is saved as "no unit" and every later unit check
            // compares against nothing
            const lm = /^(.*?)\s*[(\[]\s*([^()\[\]]+?)\s*[)\]]\s*$/.exec(String(p.label || ''));
            const looksUnit = lm && (/[\/%µμ]/.test(lm[2]) || /^[A-Za-z0-9^.·\s]+$/.test(lm[2]));
            const fileUnit = String(p.unit || (looksUnit ? lm[2] : '')).trim();
            const colName = looksUnit ? lm[1] : p.label;
            // the model's bare "__extra__" can't be agreed to as is: a company's extra is a
            // column someone names (CONTEXT.md), so it only preselects that answer
            const propExtra = prop.target === '__extra__' && !!p.company_id;
            const hasProp = prop.target && prop.target !== '__unknown__' && !propExtra;
            const rangeSuspect = !!(p.range_suspect || /นอกช่วง/.test(p.reason || ''));
            const reg = p.field_set === 'registry';
            const cols = reg ? registryColumns : templateColumns;
            const colOptions = cols.map(c =>
                `<option value="${esc(c.column)}" ${c.column === (prop.target || p.suggestion) ? 'selected' : ''}>${esc(c.header || c.column)}${c.desc ? ' — ' + esc(c.desc) : ''}</option>`).join('');
            if (reg) return {
                title: `คอลัมน์ “${esc(p.label)}” ในไฟล์ทะเบียนคือข้อมูลอะไร`,
                why: '<span class="muted">ตอบครั้งเดียว ระบบจะจำไว้ให้หน่วยบริการนี้</span>',
                body: `<div class="muted">sheet ${esc(p.sheet)}</div>`,
                answer: `<div class="wiz-choices">
                    <label class="choice"><input type="radio" name="rwAns" value="set">
                        <span><b>เป็นข้อมูลของพนักงาน</b><span class="muted">เลือกช่องในทะเบียน</span></span></label>
                    <div class="choice-extra" id="rwSetBox" hidden>
                        <select id="rwSetTarget"><option value="">— เลือกช่องในทะเบียน —</option>${colOptions}</select>
                    </div>
                    <label class="choice"><input type="radio" name="rwAns" value="ignore">
                        <span><b>ไม่ใช่ข้อมูลทะเบียน</b>
                        <span class="muted">เช่น ลำดับที่ รหัสภายในของบริษัท — ระบบจะไม่ถามคอลัมน์นี้อีก</span></span></label></div>`,
                onShow() {
                    const sync = () => {
                        const v = root.querySelector('input[name=rwAns]:checked');
                        $('rwSetBox').hidden = !v || v.value !== 'set';
                    };
                    root.querySelectorAll('input[name=rwAns]').forEach(el => el.addEventListener('change', sync));
                    sync();
                },
            };
            const agree = ver.verdict
                ? (ver.agrees ? '<span class="tag ok">AI สองตัวตรงกัน</span>'
                   : ver.verdict === 'wrong' ? '<span class="tag bad">AI สองตัวไม่ตรงกัน</span>'
                   : '<span class="tag warn">AI ตัวที่สองไม่แน่ใจ</span>') : '';
            return {
                title: `คอลัมน์ “${esc(p.label)}” ในไฟล์คือผลตรวจอะไร`,
                why: p.company_column_conflict
                    ? `<div class="review-warn"><b>${esc(p.reason || '')}</b><br>
                         เลือกคอลัมน์ “${esc(p.company_column_conflict.name)}” จากรายการด้านล่างได้ถ้าจะใช้คอลัมน์เดิมต่อ
                         (ค่าจะถูกเก็บตามที่ไฟล์นี้เขียนมา ไม่แปลงหน่วยให้) หรือตั้งชื่อใหม่ถ้าเป็นคนละเรื่องกัน</div>`
                    : p.maybe_identity
                    ? '<span class="review-warn">ค่าในคอลัมน์นี้อาจเป็นชื่อหรือแผนก ไม่ใช่ผลตรวจ ระบบจึงไม่บันทึกเองแม้ AI จะเสนอ</span>'
                    : rangeSuspect
                    ? `<div class="review-warn"><b>ถามซ้ำเพราะค่าในไฟล์ไม่ตรงกับช่วงที่เป็นไปได้ของ ${esc(p.suggestion || 'ช่องนี้')}</b><br>
                         ระบบคาดว่าน่าจะเป็นเรื่องหน่วย: แบบฟอร์มเก็บเป็น <b>${esc(p.canonical_unit || '')}</b>
                         (ช่วง ${esc(p.lo)}–${esc(p.hi)}) แต่ค่าตัวอย่างข้างล่างอยู่คนละสเกล<br>
                         ดูตัวเลขแล้ว <b>เลือกหน่วยที่ตรงกับตัวเลขเหล่านั้น</b> ที่ช่อง “หน่วยของค่าในไฟล์” ระบบจะแปลงให้เอง</div>`
                    : `<span class="muted">มี ${Number(p.count || 0)} ค่าในคอลัมน์นี้${fileUnit ? ' · หน่วยที่เขียนในไฟล์ ' + esc(fileUnit) : ''}</span>`,
                body: `<div class="muted">ค่าตัวอย่างในไฟล์</div>
                       <div class="sample-strip">${samples(p.samples, 8)}</div>
                       ${hasProp ? `<div class="ai-box">AI เสนอว่าเป็น <b>${esc(prop.target)}</b>${prop.unit ? ' หน่วย ' + esc(prop.unit) : ''}
                            <div class="chips">${agree}</div></div>`
                         : propExtra ? `<div class="ai-box">AI เสนอว่าเป็น <b>ผลตรวจที่ไม่มีช่องในแบบฟอร์ม</b>
                            — เลือกคอลัมน์ของบริษัทที่มีอยู่ หรือตั้งชื่อคอลัมน์ใหม่ด้านล่าง
                            <div class="chips">${agree}</div></div>` : ''}`,
                answer: `<div class="wiz-choices">
                    ${hasProp ? `<label class="choice"><input type="radio" name="rwAns" value="approve">
                        <span><b>ใช่ ตามที่ AI เสนอ</b><span class="muted">${esc(prop.target)}</span></span></label>` : ''}
                    <label class="choice"><input type="radio" name="rwAns" value="set">
                        <span><b>เป็นผลตรวจอย่างอื่น</b><span class="muted">เลือกช่องเอง</span></span></label>
                    <div class="choice-extra choice-extra-col" id="rwSetBox" hidden>
                        <select id="rwSetTarget">${prop.target || p.suggestion ? '' : '<option value="">— เลือกคอลัมน์ —</option>'}${colOptions}</select>
                        <label class="choice-field" id="rwUnitField" hidden style="margin:0;">
                            <span>หน่วยของค่าในไฟล์ <b class="req">*</b></span>
                            <select id="rwSetUnit"></select>
                            <small class="muted" id="rwUnitHint"></small>
                        </label>
                    </div>
                    <label class="choice"><input type="radio" name="rwAns" value="extra">
                        <span><b>เป็นผลตรวจจริง แต่ไม่มีช่องในแบบฟอร์ม</b>
                        <span class="muted">ตั้งเป็นคอลัมน์ของบริษัทนี้ หรือใช้คอลัมน์ที่เคยตั้งไว้แล้ว</span></span></label>
                    <div class="choice-extra" id="rwExtraBox" hidden style="flex-direction:column;align-items:stretch;">
                        <select id="rwExtraPick">
                            <option value="">— เลือกคอลัมน์ที่มีอยู่แล้วของบริษัทนี้ —</option>
                            ${currentCompanyCols.map(c => `<option value="${c.id}">${esc(c.name)}
                                (${c.kind === 'numeric' ? 'ตัวเลข' + (c.unit ? ' · ' + esc(c.unit) : '') : 'ข้อความ'})</option>`).join('')}
                            <option value="__new__">+ ตั้งคอลัมน์ใหม่</option>
                        </select>
                        <div id="rwExtraNewFields" hidden style="display:flex;flex-direction:column;gap:8px;margin-top:8px;">
                            <label class="choice-field"><span>ชื่อคอลัมน์ใหม่</span>
                                <input id="rwExtraName" placeholder="เช่น ${esc(colName)}" value="${esc(colName)}"></label>
                            <label class="choice-field"><span>ชนิดข้อมูล</span>
                                <select id="rwExtraKind">
                                    <option value="numeric">ตัวเลข</option>
                                    <option value="text">ข้อความ</option>
                                </select></label>
                            <label class="choice-field" id="rwExtraUnitField">
                                <span>หน่วย (ถ้ามี — เก็บตามที่พิมพ์ ไม่แปลง)</span>
                                <input id="rwExtraUnit" placeholder="${fileUnit ? 'เช่น ' + esc(fileUnit) : 'เช่น mg/dL — เว้นว่างได้'}" value="${esc(fileUnit)}"></label>
                        </div>
                        <div id="rwExtraUnitWarn" class="review-warn" style="margin-top:8px;" hidden></div>
                    </div>
                    <label class="choice"><input type="radio" name="rwAns" value="ignore">
                        <span><b>ไม่ใช่ผลตรวจ</b><span class="muted">เช่น ลำดับที่ รหัสภายใน</span></span></label></div>`,
                evidence: `<div class="review-grid">
                    <div><b>ค่าตัวอย่างทั้งหมด</b><br>${samples(p.samples, 12)}</div>
                    <div><b>AI ตัวที่ 1</b> ${hasProp ? `${esc(prop.target)} <span class="muted">มั่นใจ ${esc(prop.confidence)}</span>` : 'ไม่ได้เสนอ'}
                         <br><span class="muted">${esc(prop.reason || p.reason || '')}</span></div>
                    <div><b>AI ตัวที่ 2</b> ${agree || '—'}${ver.agrees === false && ver.target ? ' → ' + esc(ver.target) : ''}
                         <br><span class="muted">${esc(ver.reason || '')}</span></div>
                    <div><b>ตรวจช่วงค่าด้วยโค้ด</b> ${prop.range_ok === true ? '<span class="tag ok">ผ่าน</span>'
                        : prop.range_note ? `<span class="tag warn">${esc(prop.range_note)}</span>` : '—'}</div></div>`,
                onShow() {
                    const sync = () => {
                        const v = root.querySelector('input[name=rwAns]:checked');
                        $('rwSetBox').hidden = !v || v.value !== 'set';
                        $('rwExtraBox').hidden = !v || v.value !== 'extra';
                    };
                    root.querySelectorAll('input[name=rwAns]').forEach(el => el.addEventListener('change', sync));
                    if (propExtra && !root.querySelector('input[name=rwAns]:checked')) {
                        root.querySelector('input[name=rwAns][value=extra]').checked = true;
                        if (!currentCompanyCols.length) $('rwExtraPick').value = '__new__';
                    }
                    sync();
                    $('rwSetTarget').addEventListener('change', () => fillUnits(p.unit || prop.unit));
                    fillUnits(p.unit || prop.unit);
                    const syncExtra = () => {
                        const picked = $('rwExtraPick').value;
                        $('rwExtraNewFields').hidden = picked !== '__new__';
                        const warn = $('rwExtraUnitWarn');
                        const col = currentCompanyCols.find(c => String(c.id) === picked);
                        if (col && col.kind === 'numeric' && fileUnit && (col.unit || '') !== fileUnit) {
                            warn.hidden = false;
                            warn.textContent = `หน่วยของไฟล์นี้ (${fileUnit}) ไม่ตรงกับที่ตั้งไว้ตอนแรก `
                                + `(${col.unit || 'ไม่ระบุ'}) — ค่าจะถูกเก็บตามที่ไฟล์นี้เขียนมาโดยไม่แปลง ถ้าไม่ต้องการแบบนี้ ให้ตั้งคอลัมน์ใหม่แทน`;
                        } else {
                            warn.hidden = true;
                        }
                    };
                    $('rwExtraPick').addEventListener('change', syncExtra);
                    syncExtra();
                },
            };
        },
    };

    function fillUnits(preselect) {
        const box = $('rwSetUnit');
        if (!box) return;
        const col = templateColumns.find(c => c.column === $('rwSetTarget').value);
        const units = (col && col.units) || [];
        $('rwUnitField').hidden = !units.length;
        const canon = String((col && col.unit) || '').toLowerCase().replace('μ', 'µ');
        box.innerHTML = '<option value="">— เลือกหน่วย —</option>' + units.map(u =>
            `<option value="${esc(u)}">${esc(u)}${u === canon ? ' (ตรงกับหน่วยของแบบฟอร์ม)' : ''}</option>`).join('');
        $('rwUnitHint').textContent = col && col.unit ? `แบบฟอร์มเก็บเป็น ${col.unit}` : '';
        const want = String(preselect || '').toLowerCase().replace('μ', 'µ').replace(/\s+/g, '');
        const match = units.find(u => u.replace(/\s+/g, '') === want);
        if (match) box.value = match;
    }

    function collect() {
        const q = QUESTIONS[idx];
        if (q.kind === 'identity') {
            const v = $('rwIdPick').value;
            return v ? {review_id: q.id, action: 'identity', role: q.role, header: v} : null;
        }
        if (q.kind === 'department') {
            const v = $('rwDeptCode').value.trim();
            return v ? {review_id: q.id, action: 'department', code: v} : null;
        }
        if (q.kind === 'which_department') {
            const dept = $('rwPickDept').value;
            return dept ? {review_id: q.id, action: 'choose_department', header: dept} : null;
        }
        if (q.kind === 'unknown_department') {
            return {review_id: q.id, action: 'add_department'};
        }
        if (q.kind === 'unregistered_person') {
            const dept = $('rwSnDept').value, first = $('rwSnFirst').value.trim();
            if (!dept) { alert('สถานประกอบการนี้ยังไม่มีแผนก — เพิ่มแผนกที่หน้าทะเบียนสถานประกอบการก่อน'); return undefined; }
            if (!first) { alert('ใส่ชื่อของคนนี้ก่อน หรือกด “ข้ามไว้ก่อน”'); return undefined; }
            return {review_id: q.id, action: 'register', header: dept,
                    first_name: first, last_name: $('rwSnLast').value.trim() || null};
        }
        const picked = root.querySelector('input[name=rwAns]:checked');
        if (!picked) return null;
        if (q.kind === 'comment') return {review_id: q.id, action: 'comment', value: Number(picked.value)};
        if (q.kind === 'department_change' || q.kind === 'registry_value')
            return {review_id: q.id, action: picked.value};
        const d = {review_id: q.id, action: picked.value};
        if (picked.value === 'set') {
            d.target = $('rwSetTarget').value;
            if (!d.target) { alert('เลือกช่องก่อน หรือกด “ข้ามไว้ก่อน”'); return undefined; }
            if ($('rwSetUnit') && !$('rwUnitField').hidden) {
                d.unit = $('rwSetUnit').value || null;
                if (!d.unit) {
                    alert('เลือก “หน่วยของค่าในไฟล์” ก่อน — ดูจากค่าตัวอย่างว่าตัวเลขเหล่านั้นเป็นหน่วยอะไร');
                    $('rwSetUnit').focus(); return undefined;
                }
            }
        }
        if (picked.value === 'extra') {
            const pick = $('rwExtraPick').value;
            if (!pick) { alert('เลือกคอลัมน์ที่มีอยู่แล้ว หรือ “+ ตั้งคอลัมน์ใหม่”'); return undefined; }
            if (pick === '__new__') {
                const name = $('rwExtraName').value.trim();
                if (!name) { alert('ตั้งชื่อคอลัมน์ใหม่ก่อน'); $('rwExtraName').focus(); return undefined; }
                d.column_name = name;
                d.column_kind = $('rwExtraKind').value;
                if (d.column_kind === 'numeric') d.column_unit = $('rwExtraUnit').value.trim() || null;
            } else {
                d.column_id = Number(pick);
            }
        }
        return d;
    }

    function restore(q) {
        const saved = answers[key(q)];
        if (!saved) return;
        const want = saved.action === 'comment' ? String(saved.value) : saved.action;
        const radio = root.querySelector(`input[name=rwAns][value="${want}"]`);
        if (radio) { radio.checked = true; radio.dispatchEvent(new Event('change')); }
        if (saved.action === 'identity' && $('rwIdPick')) $('rwIdPick').value = saved.header;
        if (saved.action === 'department' && $('rwDeptCode')) $('rwDeptCode').value = saved.code;
        if (saved.action === 'set' && $('rwSetTarget')) {
            $('rwSetTarget').value = saved.target;
            fillUnits(saved.unit);
            if ($('rwSetUnit') && saved.unit) $('rwSetUnit').value = saved.unit;
        }
        if (saved.action === 'register' && $('rwSnFirst')) {
            $('rwSnFirst').value = saved.first_name || ''; $('rwSnLast').value = saved.last_name || '';
            if (saved.header) $('rwSnDept').value = saved.header;
        }
        if (saved.action === 'extra' && $('rwExtraPick')) {
            $('rwExtraPick').value = saved.column_id ? String(saved.column_id) : '__new__';
            $('rwExtraPick').dispatchEvent(new Event('change'));
            if (!saved.column_id) {
                if ($('rwExtraName')) $('rwExtraName').value = saved.column_name || '';
                if ($('rwExtraKind')) $('rwExtraKind').value = saved.column_kind || 'numeric';
                if ($('rwExtraUnit')) $('rwExtraUnit').value = saved.column_unit || '';
            }
        }
    }

    $('rwWizNext').addEventListener('click', () => {
        const d = collect();
        if (d === undefined) return;
        const q = QUESTIONS[idx];
        if (d) answers[key(q)] = Object.assign({}, d, {_file: q.source_file_id, _group: q.group, _role: q.role});
        else delete answers[key(q)];
        step(+1);
    });
    $('rwWizSkip').addEventListener('click', () => { delete answers[key(QUESTIONS[idx])]; step(+1); });
    $('rwWizBack').addEventListener('click', () => step(-1));
    $('rwWizRestart').addEventListener('click', () => { idx = 0; show(); });

    function step(n) {
        idx += n;
        if (idx < 0) idx = 0;
        if (idx >= QUESTIONS.length) finish(); else show();
    }

    function labelOf(q) {
        const p = q.payload || {};
        if (q.kind === 'unknown_department') return `แผนก ${p.department_in_file}`;
        if (q.kind === 'registry_value') return `${p.header || p.column} ของ ${p.cid}`;
        return p.label || p.text || p.name || p.name_in_file || p.cid || ROLE_TH[q.role] || `รายการ ${q.id}`;
    }
    const ACTION_TH = {approve: 'ยอมรับตามที่ AI เสนอ', extra: 'เก็บเป็นข้อมูลเพิ่มเติม',
        ignore: 'ไม่ใช่ข้อมูลที่ต้องเก็บ', register: 'เพิ่มเข้าทะเบียน', move_department: 'ย้ายแผนกจริง',
        use_register: 'ใช้แผนกในทะเบียน', add_department: 'เพิ่มแผนกนี้',
        choose_department: 'เลือกแผนกแล้ว',
        keep: 'เก็บค่าเดิม', replace: 'ใช้ค่าใหม่จากไฟล์'};
    function actionTh(a) {
        if (a.action === 'set') return `ตั้งเป็น ${a.target}`;
        if (a.action === 'identity') return `คอลัมน์ ${a.header}`;
        if (a.action === 'department') return `รหัส ${a.code}`;
        if (a.action === 'comment') return a.value === 1 ? 'ปกติ' : 'ผิดปกติ';
        if (a.action === 'choose_department') return `แผนก ${a.header}`;
        return ACTION_TH[a.action] || a.action;
    }

    function finish() {
        $('rwWizard').hidden = true;
        $('rwWizDone').hidden = false;
        const answered = Object.keys(answers).length;
        const left = QUESTIONS.length - answered;
        $('rwWizDoneTitle').textContent = QUESTIONS.length
            ? `ตอบแล้ว ${answered} ข้อ จาก ${QUESTIONS.length} ข้อ` : 'ไม่มีคำถามรอตอบ';
        $('rwWizDoneNote').textContent = left
            ? `ข้ามไว้ ${left} ข้อ จะยังรออยู่ที่นี่ กดบันทึกได้เลย`
            : (QUESTIONS.length ? 'กดบันทึกเพื่อให้ระบบนำไฟล์ไปประมวลผลใหม่' : '');
        $('rwWizSave').hidden = !answered;
        $('rwWizRestart').hidden = !QUESTIONS.length;
        $('rwWizDoneList').innerHTML = QUESTIONS.filter(q => answers[key(q)]).map(q =>
            `<div class="summary-row"><span>${esc(labelOf(q))}</span><b>${esc(actionTh(answers[key(q)]))}</b></div>`).join('');
    }

    $('rwWizSave').addEventListener('click', async () => {
        const btn = $('rwWizSave');
        btn.disabled = true; btn.textContent = 'กำลังบันทึก…';
        const byFile = {};
        for (const a of Object.values(answers)) {
            const d = Object.assign({}, a);
            const fid = d._file, group = d._group;
            delete d._file; delete d._group; delete d._role;
            if (group && (d.action === 'comment' || d.action === 'register')) {
                group.forEach(r => {
                    const l = byFile[r.source_file_id] = byFile[r.source_file_id] || [];
                    l.push(Object.assign({}, d, {review_id: r.id}));
                });
            } else {
                (byFile[fid] = byFile[fid] || []).push(d);
            }
        }
        const saved = [];
        let failure = null;
        for (const [fid, decisions] of Object.entries(byFile)) {
            try {
                await api(`/api/files/${fid}/decisions`, {method: 'POST',
                    body: JSON.stringify({decisions, by: 'reviewer'})});
                saved.push(fid);
            } catch (e) { failure = {fid, message: e.message}; break; }
        }
        if (!failure) Object.keys(answers).forEach(k => delete answers[k]);
        await load();
        await loadConflicts();
        if (failure) {
            const stillOpen = new Set(QUESTIONS.map(key));
            Object.keys(answers).forEach(k => { if (!stillOpen.has(k)) delete answers[k]; });
            const name = (FILES[String(failure.fid)] || {}).filename || `ไฟล์ #${failure.fid}`;
            alert(`บันทึกไม่สำเร็จที่ ${name}: ${failure.message}\n\n`
                + (saved.length ? `ไฟล์ที่บันทึกไปแล้ว ${saved.length} ไฟล์ ไม่ต้องตอบซ้ำ\n` : '')
                + 'คำตอบที่ยังไม่ได้บันทึกยังอยู่ กดบันทึกใหม่ได้เลย');
            if (Object.keys(answers).length) finish();
        }
        btn.disabled = false; btn.textContent = 'บันทึกคำตอบทั้งหมด';
    });

    async function dismissKind(kind) {
        const rows = SKIPPED.filter(r => r.kind === kind);
        if (!rows.length) return;
        if (!confirm(`ยืนยันว่าแก้ไฟล์ต้นฉบับแล้ว และนำเข้าไฟล์ที่แก้แล้ว?\n` +
                     `จะปิด “${KIND_LABEL[kind] || kind}” ${rows.length} รายการ และบันทึกว่าใครเป็นคนปิด`)) return;
        const byFile = {};
        rows.forEach(r => (byFile[r.source_file_id] = byFile[r.source_file_id] || []).push(
            {review_id: r.id, action: 'dismiss'}));
        try {
            for (const [fid, decisions] of Object.entries(byFile))
                await api(`/api/files/${fid}/decisions`, {method: 'POST', body: JSON.stringify({decisions, by: 'reviewer'})});
        } catch (e) { alert(e.message); }
        await load();
        await loadConflicts();
    }

    async function loadConflicts() {
        const rows = await api('/api/conflicts?status=open&limit=5000' + extraQuery);
        const pill = $('rwConflictCount');
        pill.textContent = rows.length; pill.hidden = !rows.length;
        $('rwConflictEmpty').hidden = rows.length > 0;
        const byFile = {};
        rows.forEach(c => (byFile[c.source_file_id] = byFile[c.source_file_id] || []).push(c));
        $('rwConflictList').innerHTML = Object.entries(byFile).map(([fid, cs]) => {
            const f = FILES[String(fid)];
            return `<div class="card" style="margin-bottom:14px;">
                <div class="review-file-head">
                    <span>${esc(f ? f.filename : 'ไฟล์ #' + fid)}</span>
                    <button class="btn btn-sm" data-accept-all="${Number(fid)}">ใช้ค่าใหม่ทั้งไฟล์</button></div>
                <div class="table-wrap"><table><thead><tr>
                    <th>คน</th><th>ช่อง</th><th>ค่าที่เก็บไว้</th><th>ค่าที่ส่งมาใหม่</th><th></th>
                </tr></thead><tbody>${cs.map(c => `<tr>
                    <td>${esc(c.name) || esc(c.cid)}<div class="muted">${esc(c.visit_date)}</div></td>
                    <td>${esc(c.column)}</td>
                    <td><b>${esc(c.current_value)}</b><div class="muted">${esc(c.current_from.file || '')}</div></td>
                    <td><b>${esc(c.incoming_value)}</b><div class="muted">${esc(c.incoming_from.file || '')}</div></td>
                    <td class="row-actions">
                        <button class="btn btn-sm" data-resolve="${Number(c.id)}" data-action="keep">เก็บค่าเดิม</button>
                        <button class="btn btn-primary btn-sm" data-resolve="${Number(c.id)}" data-action="replace">ใช้ค่าใหม่</button>
                    </td></tr>`).join('')}</tbody></table></div></div>`;
        }).join('');
        root.querySelectorAll('[data-resolve]').forEach(b => b.addEventListener('click', () =>
            resolveConflict(Number(b.dataset.resolve), b.dataset.action)));
        root.querySelectorAll('[data-accept-all]').forEach(b => b.addEventListener('click', () =>
            acceptAllConflicts(Number(b.dataset.acceptAll))));
        onChange();
    }

    async function resolveConflict(id, action) {
        await api(`/api/conflicts/${id}/resolve`, {method: 'POST', body: JSON.stringify({action, by: 'reviewer'})});
        loadConflicts();
    }
    async function acceptAllConflicts(fid) {
        if (!confirm('ใช้ค่าใหม่ทั้งไฟล์? ค่าเดิมจะถูกแทนที่ และบันทึกไว้ในประวัติ')) return;
        await api(`/api/files/${fid}/conflicts/accept-all`, {method: 'POST', body: JSON.stringify({by: 'reviewer'})});
        loadConflicts();
    }

    root.querySelectorAll('#rwTabs .tab').forEach(t => t.addEventListener('click', () => {
        root.querySelectorAll('#rwTabs .tab').forEach(x => x.classList.toggle('on', x === t));
        $('rwPaneReviews').hidden = t.dataset.pane !== 'reviews';
        $('rwPaneConflicts').hidden = t.dataset.pane !== 'conflicts';
    }));

    return { refresh: () => load().then(loadConflicts) };
}
