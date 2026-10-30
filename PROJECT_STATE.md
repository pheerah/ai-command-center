# AI Dev Command Center — สถานะส่งมอบ

อัปเดต 2026-10-30 (Asia/Bangkok)

## พร้อมใช้งาน

- **Codex + Claude พร้อมใช้จริงผ่าน Center** ใช้ SQLite ไม่ใช้ Supabase
- เปิด `live_execution=true` ใน `center.config.json`; providers codex/claude = available จาก live implementation และ independent review ที่ผ่านจริง
- Scheduler หลักเปิดแล้วในโหมด live (`instance=91729e579f9140889ed859f3d3c04e8b`) ตรวจซ้ำด้วย `service-status` เพราะ PID/สถานะเปลี่ยนได้เมื่อรีสตาร์ต
- Dashboard http://127.0.0.1:3939 ตอบ health/status HTTP 200, live_execution=true, active_sessions=0 ตอนตรวจส่งมอบ
- Google คง unavailable / usage_exhausted / reset unknown ไม่มีการเรียกโมเดล Google หรือหลบ quota
- ผู้ใช้อนุญาต commit/push ชุดนี้บน branch codex/command-center-dashboard แล้ว ไม่มี merge/deploy และไม่เชื่อม/แก้โปรเจกต์ go-live ไม่มี system auto-start หรือการแก้ global IDE settings

## Live orchestration ที่พิสูจน์แล้ว

ไฟล์หลักฐาน: `sandbox/runs/live-612c4b12/live-summary.json` และ `live-result.json` มี dispatch/start/result/gates/review/provider session references จริง

| Task | โปรเจกต์ตัวอย่าง | ผู้เขียน | ผู้ตรวจ | ผล |
|---|---|---|---|---|
| 95328275aa23 | live-python / src/bounds.py | Codex | Claude | ready_for_human_approval |
| 57afad489d98 | live-node / src/slug.js | Claude | Codex | ready_for_human_approval |

- ทั้งสองงานถูก scheduler จริงส่งผ่าน Maestro ใช้ CLI subscription ที่ตรวจ authentication method แล้ว ไม่มี API keys/paid API fallback
- ผ่าน functional gates จริง และ real independent review ผูกกับ base/patch hash; ตรวจ evidence ซ้ำหลังแก้ adapter แล้ว hash ยังตรง
- **ไม่มี human approval หรือ self-approval** การหยุดรอผู้ใช้เป็นพฤติกรรมปกติของระบบ ไม่ใช่งานพัฒนาที่ยังขาด
- มีความผิดพลาดระหว่างทดสอบที่เก็บไว้ตามจริง: Python fixture gate syntax ผิด, native Windows Codex write sandbox ไม่ยอมเขียน และ reviewer ไม่มี source context ครบ แก้ fixture/adapter แล้ว rerun เฉพาะ phase ที่จำเป็น เก็บโค้ด Claude เดิมไว้ ไม่เรียก implementation ซ้ำเมื่อแก้เฉพาะ gate/context
- Worker model invocations ใน smoke นี้รวม 6 ครั้ง รวม attempts ที่ล้มเหลว ไม่รวม source audits งาน Python ใช้ implementation 2 attempts; งาน Node เก็บ implementation attempt เดิมและ retry review หลังแก้บริบท
- Codex ใช้ read-only structured edits → Center ตรวจ scope/expected SHA256 แล้ว apply; Claude ใช้ restricted file tools; reviewers รับ full changed files/diff แบบ bounded inline context ไม่ต้องเรียก commands
- Provider session/model references มาจาก CLI output จริง รุ่นที่ CLI ไม่รายงานเป็น unknown ไม่เดาจากความจำ

## สิ่งที่ implemented

- SQLite schema version 3: registry, tasks/events, durable sessions, authorship, evidence, provider health, migration/backup และ validated transitions
- Python เป็น scheduler/atomic claim owner เพียงตัวเดียว Maestro รัน command phases ตามที่ได้รับมอบหมาย
- Configurable global/provider concurrency, dependency rules, leases/heartbeats, bounded retries/backoff/jitter/cooldown, cancellation และ explicit reassignment
- Worktree แยก project/task/attempt, scoped binary/untracked patch hashes, checkpoints และ hash-verified restore เก็บงานเก่าทุก attempt
- ไม่ปล่อย slot เมื่อ worker เดิมยังอาจทำงานอยู่; handoff cancellation ต้อง explicit worker-stopped ACK และ retry ทิ้ง cancel request ไม่ได้
- เก็บ conservative authorship หาก worker เปลี่ยนไฟล์ก่อน parent รับ start ACK เพื่อไม่ให้ provider เดิมกลับมา review ผลงานตนเองหลัง crash
- Independent reviewer ต้องไม่อยู่ใน authorship ทุก attempt, explicit verdict + exact base/patch hash; mock review ไม่ให้ approval
- Human approval ต้อง interactive terminal + task/hash phrase, ไม่รับ pipe และไม่ทำ Git actions ต่อเอง
- `check-gates` ตรวจ implementation เดิมซ้ำโดยไม่เรียก AI; `retry-review` ขอทบทวน patch เดิมพร้อมเหตุผลและยังจำกัด attempts ไม่ต้อง reimplement
- `center_context.py` จำกัด source context และตรวจ structured edits ทั้งชุดก่อนเขียน ไม่อ่าน sensitive/dependency paths ปฏิเสธ stale/duplicate/out-of-scope edits
- Windows owned Job Objects / POSIX process groups สำหรับ timeout/cancel/descendant cleanup; worker environment ใช้ allowlist
- Read-only dashboard ปิด legacy direct-AI routes ไม่มี token harvesting หรือ credential refresh
- Project connector, deterministic lease watcher, rules/skill template และ local connector check กับ task ที่ผ่านจริง

## คุณภาพและ independent code review

- Python unittest **51 ผ่าน** และ targeted regression หลังปรับ bytecode filter ผ่าน
- Vitest API **6 ผ่าน**, Playwright browser → API → SQLite **2 ผ่าน** รวม **59 tests**
- ESLint, build, Python syntax และ git diff --check ผ่าน ไม่มีการลด threshold/skip missing tools
- Parallel mock supervisor smoke ผ่าน 4 งาน / 2 โปรเจกต์ / พร้อมกันสูงสุด 4 sessions รายงาน `.ai-team/scheduler-smoke/3312cc8e/report.json`
- SQLite integrity_check ของ state หลักเป็น ok; runtime เลือก journal DELETE สำหรับ SQLite 3.50.4 ที่มากับ Python เนื่องจาก upstream WAL-reset bug รุ่นที่แก้แล้วใช้ WAL
- Code review ผู้เขียน Codex → ผู้ตรวจ Claude ผ่าน subscription ผู้ใช้อนุญาต source 9 ไฟล์เดิมและเพิ่ม 3 ไฟล์ใหม่ (center_context.py, tests/test_context.py, scripts/live_smoke.py) ชัดเจนแล้ว
- รอบ live-adapter audit แรก rejected เฉพาะการข้าม untracked generated paths กว้างเกินไป แก้ให้ยกเว้นเฉพาะ .pyc/.pyo ภายใน __pycache__ เท่านั้น ไฟล์ JS ที่แฝงใน cache และ untracked dist/node_modules ยังถูกปฏิเสธ
- **Final verdict approved**: `.ai-team/audits/live-confirm-7db267b5/response.json` / `review-summary.json`
- Source hash รวม 12 ไฟล์ที่ตรวจใน revision ก่อนเพิ่ม Usage Meter: `0cd1c19c8571f5e273394162ead2c87e3155ed29644e0ad0447a39fa37356b5f`; manifest อยู่ `.ai-team/review-live-bundle/manifest.json` หลังจากนั้น smart_router.py/server.js เปลี่ยนเพื่อเพิ่ม read-only usage จึงไม่อ้างว่า hash นี้ครอบคลุม revision ปัจจุบัน
- Reviewer actual session `ad7456c5-8663-4bb8-a415-0d8a2c556cf0`, observed model `claude-sonnet-5-5`; approval นี้เป็น static diff review ไม่ใช่ human approval

## Dashboard รวม Usage Meter (30 ต.ค. 2026)

- หน้าเดียวมีสถานะระบบ ผู้ให้บริการ input/output/cache กราฟรายวัน และคิวงาน เลือกวันนี้/7/30 วันได้ รองรับมือถือ
- อ่านเฉพาะ Center-owned CLI artifacts; mock ไม่นับ และไม่อ่าน credentials หรือเรียกโมเดล/API เพิ่ม quota/reset ยังคง unknown
- รวม live smoke เดิมผ่าน local usage-sources.json อย่างชัดเจน ตัวเลขไม่ใช่ยอดรวมบัญชีหรือ billing
- ผ่าน usage parser 7 tests, API 8 tests, browser 4 tests รวมถึง responsive/ช่วงเวลา/error state; lint/build ผ่าน ตรวจภาพหน้าจอจริงทั้ง desktop/mobile แล้ว
- รอบ UI นี้ไม่ได้ส่ง source ให้ผู้ตรวจโมเดลเพิ่มเติม และไม่มี human approval/commit/push; scheduler เดิมไม่เปลี่ยน dashboard server โหลด source ใหม่แล้ว

## Antigravity / ขอบเขตที่ยังไม่อ้างว่าพิสูจน์แล้ว

- ตรวจเอกสารทางการปัจจุบันและ `agy --help` แบบไม่เรียกโมเดลแล้ว `.agents/rules/*.md` มี trigger=always_on; skills มี name/description และตำแหน่งตรง discovery format
- `sandbox/runs/live-612c4b12/connector-check.json` ยืนยัน project-local connector อ่าน task จริงที่ผ่านแล้วได้ โดยไม่เรียก Google
- Actual Antigravity model session/handoff/timer ยังต้องยืนยันเมื่อ Google กลับมา **ไม่ใช่ blocker ของ Codex/Claude Center** และห้ามเอา mock ไปอ้างว่า live-tested
- Worktrees ไม่ใช่ OS sandbox, handoff identity เป็น reported identity ไม่ใช่ cryptographic authentication; arbitrary gate scripts ต้องตรวจและเชื่อถือก่อนลงทะเบียน
- Model CLI quotas ยังคง unknown/source=not_observed ไม่สร้างเปอร์เซ็นต์หรือเวลา reset ขึ้นเอง หลาย sessions ไม่เพิ่ม quota ของบัญชี
- ยังไม่มี human approval ของ patch จริง และไม่มีการเชื่อมโปรเจกต์จริงที่กำลัง go-live ตามข้อห้ามเดิม

## ข้อมูลเก่า / recovery

- Branch main, baseline badae3b; งานค้างก่อนเริ่มรักษาไว้ ไม่ reset/clean
- Source เดิมและ audit เดิม: `.ai-team/recovery/pre-v2/`; SQLite backups: `.ai-team/backups/`
- Task เก่า 2 รายการเก็บเป็น approved historical 1 และ blocked legacy evidence 1 ไม่สร้าง v2 approvals ย้อนหลัง
- Supabase เคยตรวจ read-only connectivity ผ่าน แต่ผู้ใช้เลือกไม่ใช้ ไม่มี schema/data migration ไป Supabase
- Rollback ต้องหยุด workers แล้วคืน source/config/database backup เป็นคู่ใน state แยก โดยรักษา worktrees/checkpoints ดู MIGRATION.md

## คำสั่งปกติ

```powershell
.\.venv\Scripts\python.exe smart_router.py doctor
.\.venv\Scripts\python.exe smart_router.py service-status
.\.venv\Scripts\python.exe smart_router.py start --mode live
.\.venv\Scripts\python.exe smart_router.py stop
npm.cmd start
```

ลงทะเบียนเฉพาะโปรเจกต์ที่ผู้ใช้อนุญาตก่อน submit งาน ใช้ scope และ acceptance criteria ที่ชัดเจน ไม่ต้องเรียก live smoke หรือ audits ซ้ำโดยไม่มีการเปลี่ยนแปลงที่ต้องตรวจ รายละเอียด README.md / VALIDATION.md / HANDOFF_ANTIGRAVITY.md
