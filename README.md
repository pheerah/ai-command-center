# AI Dev Command Center

Center กลางในเครื่องสำหรับหลายโปรเจกต์ ใช้ **SQLite** เก็บคิว การมอบหมายงาน session ประวัติผู้เขียน checkpoint และหลักฐานทดสอบ ไม่ต้องใช้ Supabase หรือ API key

ชุดปัจจุบันทดสอบ Codex/Claude จริงครบทั้งสองบทบาทแล้ว: Codex เขียน Python → Claude review และ Claude เขียน JavaScript → Codex review ผ่าน functional gates และจบที่ ready_for_human_approval พร้อม parallel mock supervisor smoke ดู [VALIDATION.md](VALIDATION.md) สำหรับหลักฐานและขอบเขตการตรวจ

Python เป็นเจ้าของ scheduler/atomic claim เพียงตัวเดียว ส่วน Maestro 2.5.4 รัน phase ที่ได้รับมอบหมายผ่าน command task แบบ argument array ไม่มี scheduler อีกตัวมา claim งานซ้ำ งานแยก worktree ตาม project/task/attempt

## เริ่มใช้งานบน Windows

รันจากโฟลเดอร์ Center:

```powershell
# ใช้ .venv เดิมที่ติดตั้งไว้แล้ว หรือเตรียมใหม่ด้วย python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci --ignore-scripts
.\.venv\Scripts\python.exe smart_router.py doctor
.\.venv\Scripts\python.exe smart_router.py start --mode live

# ทดลองสองโปรเจกต์ผ่าน Maestro จริง + AI adapters จำลอง ไม่มี model calls
npm.cmd run demo

# หน้าเว็บดูสถานะ
npm.cmd start
```

เปิด http://127.0.0.1:3939 หน้า dashboard อ่านสถานะจาก SQLite เท่านั้น การส่ง/ยกเลิกงานของโปรเจกต์ทำผ่าน /api/v1 (ต้องมี token) หรือ CLI ไม่มีเส้นทางเรียก AI โดยตรง อ่าน/refresh token หรือแก้ global IDE settings

Demo สร้างโปรเจกต์ Node.js และ Python ใน `sandbox/runs/<run-id>/` และมี `report.json` บอกตำแหน่ง state/worktrees หลักฐานเป็น **mock-tested** ไม่ใช่ AI approval จริง Demo ใช้ Git history ที่มีอยู่แล้วเป็น fixture base ไม่สร้าง commit และไม่แตะโปรเจกต์ go-live

หากต้องการดูผล demo ผ่านหน้าเว็บ ให้ตั้ง state ตาม `report.json` ก่อนเปิด server:

```powershell
$env:AI_CENTER_STATE_DIR = 'C:\...\sandbox\runs\RUN_ID\state'
npm.cmd start
```

## ตั้งค่า Center

แก้ `center.config.json`:

- `global_capacity` และ `providers.<name>.capacity` ปรับจำนวน sessions ได้ ค่าเริ่มต้นรวม 4 และค่ายละ 2 เป็นเพียงค่าเริ่มต้น ไม่ใช่ข้อจำกัดตายตัว
- `roles`, `max_complexity` และ optional `model` กำหนดความสามารถของ provider ไม่มี role ที่ผูกตายตัวกับค่ายใด ไม่มีการ hardcode ชื่อโมเดล หากไม่ระบุ model จะบันทึกว่า provider default / unknown
- Router ดู capability, complexity, entitlement, availability, cooldown และ capacity ปัจจุบัน quota ที่ไม่มีแหล่งข้อมูลแสดง `unknown` พร้อม source ไม่สร้างเปอร์เซ็นต์ขึ้นเอง จำนวน sessions ไม่ได้เพิ่ม quota ของบัญชี
- `lease_seconds`, `heartbeat_seconds`, `worker_timeout_seconds`, `max_attempts`, `retry_base_seconds` และ `max_checkpoint_bytes` จำกัดเวลา จำนวนครั้งและขนาด checkpoint
- `live_execution=true` เปิดใช้งาน Codex/Claude ที่ผ่าน live smoke แล้ว คำสั่ง run/review ยังต้องระบุ `--live` หรือเปิด supervisor ด้วย `start --mode live` การทดสอบจำลองใช้ config/state แยกและตั้ง live_execution=false
- Google ตั้งเป็น `available` หลังทดสอบ adapter `agy` จริงแล้ว (ถ้าต้องปิดชั่วคราวใช้ `smart_router.py provider set google --availability unavailable --reason ...`) ไม่ดึง OAuth token

SQLite จะเลือก WAL เมื่อไลบรารีมี fix ของ WAL-reset bug แล้ว สำหรับ Python ที่ติดตั้งในเครื่องนี้ SQLite 3.50.4 จะใช้ rollback journal (`DELETE`) เพื่อหลีกเลี่ยงบั๊กดังกล่าวโดยยังใช้ transaction/atomic claim เหมือนเดิม ดู [SQLite WAL-reset bug](https://www.sqlite.org/wal.html#walresetbug) เก็บไฟล์ฐานข้อมูลบน local disk ไม่ใช้ network share หรือโฟลเดอร์ sync ระหว่างกำลังทำงาน

## เปิด–ปิด scheduler

```powershell
.\.venv\Scripts\python.exe smart_router.py start --mode live
.\.venv\Scripts\python.exe smart_router.py service-status
.\.venv\Scripts\python.exe smart_router.py status
.\.venv\Scripts\python.exe smart_router.py stop
.\.venv\Scripts\python.exe smart_router.py recover
```

`start` เปิด process ที่ซ่อนหน้าต่างบน Windows ไม่มีการติดตั้ง auto-start ระดับระบบ `stop` หยุดรับงานใหม่และรอ phase ปัจจุบันจบ ถ้าต้องการหยุดงานให้ใช้ `cancel TASK_ID` ก่อน เมื่อตัว service หยุดหรือเครื่องรีสตาร์ต ให้ตรวจ `recover` และ `status` ก่อนเปิดใหม่

ใช้ `--state-dir PATH` และ `--config PATH` **ก่อนชื่อคำสั่ง** เพื่อแยก test state จากข้อมูลจริง เช่น:

```powershell
.\.venv\Scripts\python.exe smart_router.py --state-dir '.ai-team\local-test' start --mode mock
```

## ลงทะเบียนโปรเจกต์และส่งงาน

ใช้ `scripts/install_project.py` (ดูด้านล่าง) แทนการคัดลอกเอง ตัวติดตั้งวาง `connector.py`, `project.config.json` และไฟล์กฎของ IDE ที่เลือกด้วย `--ide claude|antigravity|both` (ค่าเริ่มต้น claude) โปรเจกต์ต้องเป็น Git root ที่แน่นอน ID เปลี่ยนไปชี้ repository อื่นไม่ได้ และไม่อนุญาต registry ที่ path ซ้อนกัน ตรวจ scripts ของ gates ก่อนลงทะเบียน

```powershell
.\.venv\Scripts\python.exe smart_router.py project register --id my-project --path 'C:\path\my-project'
.\.venv\Scripts\python.exe smart_router.py project show my-project
.\.venv\Scripts\python.exe smart_router.py submit --project my-project --title 'เพิ่มฟังก์ชัน' --prompt 'รายละเอียดงาน' --scope src --scope tests --accept 'ผ่านชุดทดสอบที่กำหนด' --mode live
.\.venv\Scripts\python.exe smart_router.py status TASK_ID
.\.venv\Scripts\python.exe smart_router.py report TASK_ID
```

ต้องระบุ scope และ acceptance criteria เสมอ ตั้ง `--depends-on TASK_ID` ซ้ำได้ งานขึ้นต่อกันต้องอยู่โปรเจกต์/โหมดเดียวกัน และรอ dependency ได้รับ human approval ก่อนเริ่ม โปรแกรมไม่ auto-register โปรเจกต์ และปฏิเสธการส่งงานจาก checkout ที่มีงานไม่ commit เพื่อไม่ทำงานค้างหายจากบริบท คุณเป็นผู้ตัดสินใจเรื่อง commit เอง Center ไม่ทำให้

Quality gates ต้องเป็น argument arrays เช่น `["node","--test"]`, `["npm","test"]`, `["python","-m","unittest","discover","-s","tests"]` ไม่รับ shell strings เครื่องมือหาย คำสั่งผิด หรือไม่มี gates จะไม่ถูกนับว่าผ่าน โปรเจกต์ที่มี lint/typecheck/Vitest/coverage/Playwright/build/duplication/unused checks ต้องระบุ gates เหล่านั้นตามมาตรฐานเดิม ไม่ลด threshold

## API สำหรับโปรเจกต์อื่น (/api/v1)

โปรเจกต์อื่นเรียก Center ผ่าน HTTP เท่านั้น ไม่ต้องรู้ path และไม่ต้องอ่านไฟล์ใน Center เลย ฟังที่ `127.0.0.1:3939` เท่านั้น

ติดตั้งทีละโปรเจกต์ (เจ้าของ Center รันจากฝั่ง Center):

```powershell
.\.venv\Scripts\python.exe scripts/install_project.py --path 'D:\projects\my-project' --id my-project --gate "npm test" --scope src --scope tests
```

ตัวติดตั้งลงทะเบียนโปรเจกต์ ออก token เฉพาะโปรเจกต์ (เก็บแค่ hash ฝั่ง Center) เขียน `center.connection.json` (URL + token, git-excluded) ให้โปรเจกต์ ใส่ `connector.py` (HTTP, stdlib ล้วน), skill และกฎใน `CLAUDE.local.md` และกฎ deny การอ่านโฟลเดอร์ Center ใน `.claude/settings.local.json` (รูปแบบ rule นี้ยังไม่ได้ยืนยันกับ Claude Code จริง คำสั่งใน CLAUDE.md ยังเป็นด่านหลัก) `project.config.json` ในโปรเจกต์ไม่มี path ของ Center อีกแล้ว

| คำสั่งใน connector | API | ความหมาย |
|---|---|---|
| `health` | GET /api/v1/health | scheduler พร้อมไหม, สถานะ provider |
| `submit` | POST /api/v1/tasks | ส่งงาน (Center เลือก provider/model/effort/skill เอง) ส่ง `request_id` กันงานซ้ำเมื่อ retry |
| `list` / `status` / `report` | GET /api/v1/tasks[/ID] | งานของโปรเจกต์ตัวเองเท่านั้น พร้อมแผนที่ใช้ในแต่ละขั้น |
| `cancel` | POST /api/v1/tasks/ID/cancel | ยกเลิก |
| `patch` / `apply` | GET /api/v1/tasks/ID/patch | รับ patch เป็นข้อมูลหลัง gates + independent review `apply` เขียนไฟล์เมื่อผู้ใช้อนุมัติแล้วเท่านั้น ไม่ commit |
| `wait` | (poll status) | รอจนงานถึงสถานะสุดท้าย ไม่ใช้ AI |

ความปลอดภัยที่บังคับในโค้ด: token ผูกกับโปรเจกต์เดียวและโปรเจกต์ไม่ถูกอ่านจาก request, งานของโปรเจกต์อื่นตอบ 404 เหมือนไม่มี, response สร้างจาก allowlist และ scrub path ทุกชนิด (ไม่มี worktree/state/config), ไม่เปิดเผย `patch_hash` (วลีอนุมัติคำนวณจากมัน) และ export patch ต่อเมื่อ checkpoint ตรงกับ hash ที่ตรวจแล้ว, จำกัดขนาด body 64 KB, สูงสุด 4 คำขอพร้อมกัน (503 เมื่อเต็ม), งาน active ไม่เกิน 20 ต่อโปรเจกต์, throttle เฉพาะ token ที่ผิด, connector ส่ง token ไปที่ loopback เท่านั้นและเขียนไฟล์ patch แบบสร้างใหม่เท่านั้น

ขอบเขตที่ต้องรู้: ถ้าทั้งโปรเจกต์และ Center รันเป็น OS user เดียวกัน การกั้นนี้เป็นการกั้นระดับโปรโตคอลและกฎ ไม่ใช่ sandbox ของระบบปฏิบัติการ และการอนุมัติยังเป็น terminal แบบ interactive ที่ agent ซึ่งมี pty ในเครื่องเดียวกันอาจเลียนแบบได้ถ้ารู้ที่อยู่ของ Center ซึ่งตัวติดตั้งไม่บอก หน้า dashboard `/api/status` ยังอ่านได้โดยไม่ต้องมี token (เจ้าของใช้) จัดการ token: `smart_router.py token list|create --project ID|revoke ID`

### หน้า dashboard: แยก 2 แท็บ

**Monitor งาน** (แท็บเริ่มต้น): สถานะ scheduler, จำนวนงานตามสถานะ, "กำลังรันอยู่ตอนนี้" (AI ตัวไหน บทบาทอะไร model/effort อะไร โปรเจกต์ไหน เริ่มเมื่อไหร่), บอร์ด 6 คอลัมน์ (ต้องทำ / กำลังทำ / ตรวจโดยอีกค่าย / รอคุณอนุมัติ / เสร็จ / ติดปัญหา) กรองรายโปรเจกต์ได้, ตารางงานทั้งหมดพร้อมค้นหา/กรอง กด "ดู" หรือ "ดูรายละเอียด" เปิดแผงรายละเอียดเต็มของงาน: สถานะและสาเหตุ, ภาพรวม, prompt/scope/acceptance/gates ที่สั่ง, AI ที่ Center เลือกในแต่ละขั้นพร้อมเหตุผล, ผล gates ทีละคำสั่ง, ผลการตรวจ, ผลที่ AI ส่งกลับ, ผู้เขียนทั้งหมด, session, ไทม์ไลน์เหตุการณ์ทั้งหมด, ตำแหน่งไฟล์ และ JSON ดิบ (ปิดด้วย Esc)

**Usage Meter**: เปอร์เซ็นต์ที่เหลือของ 5 ชั่วโมง/รายสัปดาห์ของ ChatGPT, Claude, Google และกราฟ token รายวัน ลิงก์ตรง `/#usage` และ `/#monitor` แท็บล่าสุดถูกจำไว้ใน browser

### งานที่ scope ใหญ่เกินสำหรับ Codex

Codex adapter อ่านทุกไฟล์ใน scope ใส่ prompt (จำกัด `max_model_context_bytes` = 64 KB) ส่วน Claude และ Google อ่านไฟล์เอง ตอนนี้ Center ประเมินขนาด scope ล่วงหน้า (จากไฟล์ที่ track ใน base revision) ถ้าเกิน จะข้าม Codex ในขั้นเขียนโค้ดและเลือกค่ายอื่นแทน (บันทึกใน event `candidate_notes`) แทนที่จะจบที่ `blocked / needs_narrower_scope` ถ้าต้องการให้ Codex ทำจริง ให้ระบุไฟล์ที่ต้องอ่านด้วย `python connector.py submit ... --read-file path/to/file` (ต้องอยู่ใน scope)

### กฎของ Center อยู่ใน `CLAUDE.local.md` (ไม่ track) และการอัปเดตโปรเจกต์ที่ติดตั้งแล้ว

Claude Code โหลด `CLAUDE.local.md` ควบคู่กับ `CLAUDE.md` (ทดสอบแล้วว่าโหลดจริง) ตัวติดตั้งจึงไม่แก้ `CLAUDE.md` ที่ track อยู่อีก เพราะการแก้ไฟล์ที่ track ทำให้ git ไม่สะอาดและ Center ปฏิเสธรับงาน ส่วนที่เคยต่อท้ายไว้ใน `CLAUDE.md` จะถูกลบออกเฉพาะบล็อกของ Center โดยคงรูปแบบบรรทัดเดิม (LF/CRLF) ถ้าแก้เทมเพลต hook skill หรือกฎของ Center แล้วต้องการอัปเดตโปรเจกต์ที่ติดตั้งไปแล้วโดยไม่แตะการลงทะเบียน token หรือ gate: `install_project.py --path ... --id ... --update` แล้วเริ่ม session Claude Code ใหม่

คำสั่ง `--gate` และ `--prepare` รับข้อความธรรมดาได้ เช่น `--gate "npm run lint"` (แนะนำบน Windows PowerShell เพราะ PowerShell 5.1 ตัดเครื่องหมายคำพูดของ JSON ทิ้ง)

hook ไม่บล็อกคำสั่ง `python connector.py <health|submit|list|status|report|cancel|patch|wait|apply>` และไม่นับ `2>&1` หรือ `>/dev/null` เป็นการเขียนไฟล์ ซึ่งเป็นสองกรณีที่บล็อกผิดในการใช้งานจริงครั้งแรกกับโปรเจกต์ Horoscope

### กันไม่ให้ Claude Code แก้ไฟล์เองโดยไม่ผ่าน Center (edit-guard hook)

ตัวติดตั้งใส่ PreToolUse hook (`.claude/hooks/center_guard.py` + ตั้งค่าใน `.claude/settings.local.json`) ที่ปฏิเสธ Edit/Write/MultiEdit/NotebookEdit ในโฟลเดอร์ `context_scope` ของโปรเจกต์ ผู้ใช้เปิดหน้าต่างแก้ตรงแบบมีเวลา (สูงสุด 4 ชั่วโมง) ด้วยตัวเองใน terminal: `python connector.py allow-direct --minutes 30 --reason "..."` และปิดด้วย `revoke-direct` ไฟล์ควบคุม (`.center-direct-edit.json`, `.claude/settings*`, `.claude/hooks/*`, `connector.py`, `project.config.json`, `center.connection.json`) agent แก้ไม่ได้เสมอแม้ในหน้าต่างอนุญาต hook ผูกกับตำแหน่งที่ติดตั้ง จึงไม่หลุดแม้ `project.config.json` ถูกลบ และล้มแบบปฏิเสธเมื่อ config อ่านไม่ได้หรือ hook พังเอง

ทดสอบกับ Claude Code CLI จริง (headless) แล้วด้วย `scripts/claude_acceptance.py`: ไม่มีหน้าต่าง → hook บล็อก, มีหน้าต่าง → เขียนได้ ยังไม่ได้ทดสอบกับส่วนขยาย VS Code เอง ต้องลองมือหนึ่งครั้ง ข้อจำกัดที่ต้องรู้: ส่วนของ Bash ตรวจด้วย pattern (redirect, tee, sed -i, mv/cp/rm, python -c ... ที่มีชื่อ path ใน scope) จับได้แค่กรณีตรงไปตรงมา agent ที่ตั้งใจเลี่ยงยังหาทางเขียนผ่าน shell ได้ จึงเป็นการ "ปิดประตูหลัก" ไม่ใช่ sandbox

### ความจุที่สำรองไว้ให้ session ของ Claude Code

`ide_reserved_sessions` ใน `center.config.json` (ค่าเริ่มต้นที่ส่งมา = 1) ถูกหักจาก `global_capacity` ก่อนจัดคิว (`usable_capacity`) หน้า dashboard แสดง "ใช้อยู่ / ใช้ได้ (สำรอง IDE N)" และ API status มี `capacity.external_sessions: "unknown"` เพราะ Center นับ session ที่เปิดนอก Center ไม่ได้ ตัวเลขสำรองเป็นค่าที่ตั้งเอง ไม่ใช่ค่าที่วัด

### Google ต้องให้ผู้ใช้ยืนยัน

Center พิสูจน์เองไม่ได้ว่า `agy` ล็อกอินแบบ subscription หรือ API/AI Studio จึงไม่เรียก Google จนกว่าผู้ใช้ยืนยันใน terminal จริง: `smart_router.py provider attest google --plan "Google AI Pro"` แล้วพิมพ์วลียืนยัน agent ที่รันโค้ดบนเครื่องเดียวกันอาจเลียนแบบ terminal ได้ จึงเป็นการยืนยันตามกติกาไม่ใช่การพิสูจน์ตัวตน

### ทำซ้ำเองเมื่อ gate ล้มหรือ reviewer ปฏิเสธ

`auto_retry: true` ใน config ให้ scheduler ส่งงานที่ `quality_gate_failed` หรือถูก review ปฏิเสธ (และไม่มี error อื่น) กลับเข้า routing เองจนครบ `max_attempts` พร้อม log ของ gate และ feedback ของ reviewer ไม่ retry งานที่ถูกยกเลิก, blocked หรือ error ด้านสิทธิ์/คอนฟิก

**ไม่ให้ loop หยุดเงียบ ๆ**
- `auto_failover: true` งานเขียนโค้ดที่ blocked ด้วย `provider_blocked` หรือ `needs_narrower_scope` (เช่น CLI ติดสิทธิ์ หรือ scope ใหญ่เกิน codex) จะถูกส่งไป AI ตัวที่ยังไม่เคยลองเอง ภายใน `max_attempts` ถ้าไม่มีตัวที่เหลือจะคง blocked ให้คนดู งานที่ blocked ตอนรีวิวไม่ถูกส่งไปเขียนใหม่ (ใช้ `retry-review`/`resume-review`)
- งานที่ล็อก codex แต่ scope เกิน `max_model_context_bytes` ตกไป AI อื่นที่ได้รับอนุญาตเอง (บันทึก `requested_codex_unfit_scope_*` ใน audit)
- `queue_stall_seconds` (ค่าเริ่มต้น 1800, 0 = ปิด) งานรอคิวที่ไม่มี AI รับได้เลย (`provider_unavailable_or_handoff_required` หรือ `no_independent_reviewer_available`) เกินเวลานี้จะเป็น `blocked` / `no_provider_available` พร้อมเหตุผล การรอ capacity, quota floor, dependency และ backoff ไม่ถูกตัด
- ไม่เลือกผู้เขียนถ้าไม่เหลือ AI อีกค่ายที่ตรวจได้ (`no_independent_reviewer_available`) เพื่อไม่ให้งานไปค้างที่ขั้นรอผู้ตรวจ
- การ์ดงานบน dashboard แสดงบรรทัดล่าสุดของ log ที่ขั้นกำลังเขียน (`activity`)
- Google/agy รับสิทธิ์ `read_file` เฉพาะ worktree และโฟลเดอร์ run ของงานนั้นผ่าน `--settings` ต่อ session ไม่แก้ settings.json ของผู้ใช้

### ตรวจหา gate ของโปรเจกต์โดยไม่เดา

`install_project.py --detect-gates` ใช้เฉพาะคำสั่งที่โปรเจกต์ประกาศไว้จริง (`npm run lint/typecheck/test/build/test:e2e`, pytest หรือ unittest) ไม่เจอก็ไม่สร้างให้ ดูรายละเอียดด้วย `python scripts/gate_presets.py PROJECT_PATH`

### เปิด Center อัตโนมัติเมื่อ login (ไม่บังคับ)

`scripts/autostart.py` สร้าง Scheduled Task 2 ตัว (scheduler + dashboard) ที่รันเมื่อ login ด้วยสิทธิ์ผู้ใช้ปกติ ไม่ใช้ admin/SYSTEM ค่าเริ่มต้นไม่ได้ติดตั้งอะไรให้: `python scripts/autostart.py print` แสดงคำสั่ง, `install --yes` ติดตั้ง, `status`, `uninstall` สคริปต์นี้ Google เขียน และ Codex ตรวจอิสระเจอข้อผิดพลาดของ Google หนึ่งข้อ (ข้อความปฏิเสธบน non-Windows) ผ่านระบบ Center เอง ส่วนที่เหลือผมแก้ต่อและเพิ่มการกัน path ที่มีเครื่องหมายคำพูด

## Center เลือกเอง: provider, model, effort, skill

ตั้งค่าใน `center.config.json` (`providers.<ชื่อ>.models`, `skills`, `quota_routing`) Center ตัดสินด้วยกฎที่ตายตัว ไม่ถามโมเดล และบันทึกเหตุผลใน event `dispatch_recorded` (`plan_reasons`) ซึ่งหน้า dashboard แสดงในคอลัมน์ผู้รับงานด้วย

- **เลือก AI ตาม usage:** อ่านเปอร์เซ็นต์ quota 5 ชม./รายสัปดาห์จริง (`center_quota.py`: Codex จาก session log, Claude จาก rate_limit_event ของ CLI, Google จาก Antigravity ในเครื่อง) เรียงผู้รับงานจากกลุ่มที่ quota ปกติก่อน แล้วดู load, อัตราล้มเหลวที่เคยเกิด และ quota ที่เหลือมากกว่า provider ที่เหลือต่ำกว่า 25% ถูกลดลำดับ ที่เหลือต่ำกว่า 5% ถูกข้ามจนกว่าจะรีเซ็ต quota ที่อ่านไม่ได้ไม่ถูกนับเป็นศูนย์หรือเต็ม และไม่ตัดสิทธิ์ ผู้ตรวจต้องไม่เคยเป็นผู้เขียนงานนั้นเหมือนเดิม
- **เลือก model:** จากแคตตาล็อกจริงของแต่ละ CLI (Codex: gpt-6-luna/gpt-6-sol/gpt-6.1-sol, Claude: haiku/sonnet/opus 5.5, Google: Gemini 3.8 Flash และ Claude Opus 4.6 ผ่าน Antigravity) แบ่งเป็น light/standard/heavy ตาม `complexity` 1-2/3/4-5 งาน review ไม่ต่ำกว่า standard ยกเว้นงานซับซ้อน 1 ถ้า quota ของ provider ต่ำ จะลดลงหนึ่งขั้น ทุก model ถูกทดสอบเรียกจริง 1 ครั้งว่าบัญชีใช้ได้
- **เลือก effort:** low→xhigh ตามความซับซ้อน ลดเหลือ low เมื่อ quota วิกฤต และถูกตัดให้อยู่ในระดับที่ model นั้นรองรับ (ส่งเป็น `-c model_reasoning_effort` ของ Codex และ `--effort` ของ Claude; model ของ Google ฝังระดับไว้ในชื่อแล้ว)
- **เลือก skill:** จากชนิดงานที่จำแนกจากหัวข้อ/คำอธิบาย (bugfix, feature, refactor, docs, test, security) และ role แล้วใส่คำแนะนำของ skill ลงใน prompt (สูงสุด 2 skill, จำกัดขนาด) skill เป็นข้อความใน config ไม่ใช่ปลั๊กอินของ CLI และไม่เหนือกว่า project policy
- **Google (`agy`):** adapter แบบ headless ผ่าน `agy --print --output-format json` ห้ามรัน shell command (headless ขอสิทธิ์ไม่ได้) ใช้เฉพาะแก้ไฟล์ แล้ว Center รัน gates ให้ ทดสอบจริงแล้วว่า Google เขียน → Codex ตรวจอิสระ ผู้ตรวจเป็น Google ยังไม่ได้ทดสอบ
- **Usage meter:** `center_quota.py` เป็นเจ้าของเดียว: scheduler ดึงทุก 1 นาทีแล้วเขียน `quota-last.json` ใน state dir ส่วน routing และ dashboard อ่านไฟล์นั้น ถ้าอ่านแหล่งใดไม่ได้จะแสดงค่าล่าสุดที่อ่านได้ (ติดป้าย stale) และจำค่าข้ามการรีสตาร์ท ไม่อ่านไฟล์ credential ใด ๆ: Codex จาก session log, Claude จากการเรียก CLI ของ Claude เองด้วย Haiku แบบเล็กที่สุดทุก 5 นาที (ใช้ quota เล็กน้อย) หรือไฟล์ statusline, Google จาก language server ของ Antigravity บน loopback ซึ่งต้องอ่าน csrf token ของ session ที่ไฟล์ daemon ของมัน (ข้อยกเว้นที่ระบุไว้ตรงนี้ ไม่ใช่ credential ของบริการภายนอก)

การรันงาน: `submit` ปกติให้ scheduler ของ Center เลือกและรันเอง ถ้าต้องการให้ session Claude Code ทำเอง ให้ใส่ `--hold-for-ide` เพื่อไม่ให้ scheduler หยิบงานไปก่อน

## สั่งงานจาก Google Antigravity

`install_project.py --ide antigravity` (หรือ `both`) วาง `.agents/rules/ai-command-center.md` (always_on) และ `.agents/skills/ai-command-center/SKILL.md` ที่ใช้ `connector.py` แบบ HTTP เดียวกับ Claude Code (`health/submit/wait/report/apply`) ไม่ใช้โปรโตคอล handoff เก่า (claim/worker-start/heartbeat) ไฟล์ของเรา git-exclude ไว้ checkout จึงสะอาดสำหรับ Center ข้อจำกัด: ตัวติดตั้งไม่ได้ตั้ง edit guard (hook ที่บล็อกการแก้ไฟล์ตรง ๆ) ให้ Antigravity เหมือนที่ทำกับ Claude Code ข้อห้ามจึงอาศัยกฎในไฟล์เท่านั้น ส่วนผู้ลงมือเขียนโค้ดยังเป็น Center เลือกจาก codex/claude/google เหมือนเดิม การเปลี่ยน IDE ไม่แก้ปัญหา Gemini แบบ headless

## Claude Code (VS Code) handoff

สั่งงานผ่าน Claude Code ของแต่ละโปรเจกต์ใน VS Code แล้วให้ Center รับช่วงต่อ ติดตั้งต่อโปรเจกต์ (ไม่เรียกโมเดล ไม่ commit):

```powershell
.\.venv\Scripts\python.exe scripts/install_project.py --path 'D:\projects\my-project' --id my-project --gate "npm test" --scope src --scope tests
```

ตัวติดตั้งคัดลอก `connector.py`, skill `.claude/skills/ai-command-center` และเพิ่มกฎใน `CLAUDE.local.md` (ไม่ทับของเดิม), เขียน `project.config.json`, ซ่อนไฟล์ที่เพิ่มออกจาก git status เพราะ Center ปฏิเสธรับงานเมื่อ checkout ไม่สะอาด แล้วลงทะเบียนโปรเจกต์ หาก `CLAUDE.md` เดิมถูก track อยู่ ต้อง commit ส่วนที่เพิ่มหนึ่งครั้งก่อนส่งงาน Claude Code ใช้ตัวตน `claude` ผู้ตรวจอิสระจึงเป็น provider อื่น (ปกติคือ Codex) ผ่าน end-to-end จริงใน sample แยก state แล้ว (claim → worker-start → watch → result → gates → Codex review → ready_for_human_approval) ยังไม่มี human approval

ส่วนด้านล่างคือโปรโตคอล handoff เดียวกัน (ใช้ได้กับ IDE ใดก็ได้ที่รายงานตัวตนจริง)

## IDE handoff (โหมดไฟล์ สำหรับผู้ดูแล Center เท่านั้น)

ส่วนนี้ใช้ `connector-template/connector_local.py` ซึ่งต้องรู้ path ของ Center และเข้าถึงไฟล์ของ Center จึง**ไม่**ติดตั้งให้โปรเจกต์อื่น โปรเจกต์ทั่วไปใช้ `connector.py` แบบ HTTP ตามหัวข้อ API ด้านบน คำสั่งด้านล่างเปลี่ยน `connector.py` เป็น `connector_local.py` ตามนั้น

คำถามทั่วไปหรือการอธิบายโค้ดตอบได้ตามปกติ งานแก้ source/config/tests ให้ส่งผ่าน connector หาก Center ติดต่อไม่ได้ให้รายงาน blocked ห้าม IDE รับไปทำทั้งหมดเงียบ ๆ

ที่ root ของโปรเจกต์:

```powershell
python connector.py health
python connector.py register
python connector.py submit --title 'งานใหม่' --prompt 'รายละเอียด' --scope src --accept 'เงื่อนไขสำเร็จ' --mode live
python connector.py claim TASK_ID --provider codex --role implementation
python connector.py worker-start SESSION_ID --reference IDE_SESSION_REFERENCE
python connector.py heartbeat SESSION_ID
python connector.py watch SESSION_ID
python connector.py result SESSION_ID --file 'ARTIFACT_DIR_FROM_CLAIM\result.json'
```

ใช้ provider ตามตัวตนจริง (`codex`, `claude`, `google`) ทำงานเฉพาะ worktree ที่ claim คืนมา `worker-start` เป็น acknowledgement พร้อม IDE session reference ใช้ `watch SESSION_ID` เป็น local background timer เพื่อ renew ทุก 5 วินาทีโดยไม่ใช้ AI หยุด timer เมื่องานจบ และหยุดแก้ไฟล์ทันทีเมื่อ renewal ล้มเหลว ถ้า worker ล้มเหลวให้หยุดงานก่อนรายงาน `worker-fail SESSION_ID --reason auth --worker-stopped` IDE automation ยังเป็น **pending_live_verification** จนกว่าจะทดสอบกับ session จริงที่รองรับ ไม่สมมติว่า `agy` หรือ consumer Google CLI เรียก headless ผ่าน third party ได้

ผลต้องเป็นไฟล์ JSON ภายใน `artifact_dir` ที่ claim ส่งกลับเท่านั้น เมื่อยกเลิกงาน handoff ให้หยุด IDE worker ก่อน แล้วรายงาน `worker-stopped SESSION_ID --reason 'หยุดแก้ไขแล้ว'` เพื่อจบ cancellation และคืน slot การหมด lease อย่างเดียวไม่พิสูจน์ว่า IDE หยุดแล้ว และไม่อนุญาตให้ retry ทิ้งคำขอยกเลิก

Implementation result:

```json
{"task_id":"TASK_ID","base_rev":"BASE_REV","simulated":false,"summary":"สิ่งที่ทำและหลักฐาน"}
```

Center คำนวณ patch/checkpoint และรัน gates จากนั้นรอ independent reviewer ซึ่ง claim ด้วย `--role review` ผล review ต้องเพิ่ม `patch_hash`, `verdict` (`approved` หรือ `rejected`) และ `summary` ที่ชัดเจน exit code 0 อย่างเดียวไม่เพียงพอ

## Live CLI adapters

Codex และ Claude ผ่าน live orchestration ใน sample projects แล้ว และเปิดค่าใช้งานจริงไว้ ตรวจ subscription login ผ่านคำสั่ง CLI โดยไม่อ่าน auth files เอง ไม่ inject API keys/third-party credentials และไม่เปลี่ยนไป paid API เมื่อเกิดข้อผิดพลาด

ผลที่ยืนยันแล้วอยู่ `sandbox/runs/live-612c4b12/live-summary.json`: task 95328275aa23 (Codex → Claude) และ 57afad489d98 (Claude → Codex) ผ่าน tests และ independent review จริง ไม่มี human approval/commit/push/merge/deploy

Codex ใช้ read-only sandbox และส่ง structured edits ให้ Center ตรวจ scope/expected SHA-256 ก่อนบันทึกลง worktree แก้ข้อจำกัด native Windows ที่ไม่ยอมเขียนแม้ขอ workspace-write โดยไม่เปิด bypass ส่วน Claude implementation ใช้ restricted file tools; reviewers ทั้งสองค่ายได้รับ full changed files/diff ใน context ที่จำกัดขนาดและไม่ตัดทิ้งเงียบ ๆ จึงตรวจได้โดยไม่ต้องเรียก commands ไม่มีการล็อกชื่อ model จากความจำ รุ่นที่ CLI ไม่รายงานจะคง unknown

หากต้องการทดสอบซ้ำอย่างมีเหตุผล ใช้ `python scripts/live_smoke.py prepare` แล้ว `python scripts/live_smoke.py run RUN_FILE` การ prepare ไม่เรียกโมเดล การ run ใช้ subscription จริงและเก็บหลักฐานใน state แยก ไม่จำเป็นต้องเรียกซ้ำหลังตรวจผ่านแล้ว

Maestro ใช้ `--execution-profile plan` สำหรับ command tasks ที่ Center สร้างเอง ไม่มี provider args อันตรายจาก profile เดิม เหตุผล: Maestro 2.5.4 safe profile ยังสร้าง provider flags บางตัวที่ไม่ตรง help ของ CLI ที่ติดตั้ง จึงให้ adapter กำหนด flags ที่ตรวจแล้วโดยตรง และใช้ Maestro เป็น phase execution engine

## Recovery, retry และ review

Lifecycle หลัก: `queued → assigned → running → implementation_done → gates → waiting_for_independent_review → review → ready_for_human_approval → approved`

มี `retry_wait`, `blocked`, `failed`, `cancelled` พร้อม validated transitions การจองงานอยู่ใน `BEGIN IMMEDIATE` ทำให้ข้ามหลาย process ได้ ไม่มีการปล่อย slot เพียงเพราะ lease หมดหาก process เก่ายังอาจทำงานอยู่

```powershell
.\.venv\Scripts\python.exe smart_router.py cancel TASK_ID
.\.venv\Scripts\python.exe smart_router.py checkpoint TASK_ID
.\.venv\Scripts\python.exe smart_router.py recover
.\.venv\Scripts\python.exe smart_router.py retry TASK_ID --worker-stopped --reason 'หยุด worker เดิมและตรวจ checkpoint แล้ว' --provider claude
.\.venv\Scripts\python.exe smart_router.py check-gates TASK_ID --reason 'แก้สภาพแวดล้อมทดสอบแล้ว ตรวจโค้ดเดิมซ้ำโดยไม่เรียก AI'
.\.venv\Scripts\python.exe smart_router.py retry-review TASK_ID --reason 'มีบริบท review เพิ่มเติมโดย patch เดิมไม่เปลี่ยน'
```

Retry อัตโนมัติมี bounded attempts, exponential backoff/jitter และ provider cooldown เมื่อ rate limit ส่วน auth/config/invalid-model จะ blocked ไม่ retry วน การ fallback เปลี่ยน provider ต้องมีเหตุผลผ่าน Center และเพิ่ม authorship จริงของทุก attempt ไม่โยนงานกลับ IDE โดยเงียบ ๆ Checkpoint เก็บ tracked binary diff และ untracked files ที่อยู่ใน scope มี base revision และ hash; ไม่อ่าน secrets/dependencies หรือเก็บไฟล์ใหญ่เกินขนาดที่กำหนด งานนอก scope จะ blocked และคง worktree เดิมไว้ให้ตรวจ

Worktree ใหม่แยกตาม attempt และ restore checkpoint ที่ตรวจ integrity แล้ว ไม่ลบ worktree หรือแก้ต้นฉบับอัตโนมัติ แต่ละ session มี artifact directory/test port ของตนเอง

Reviewer ต้องต่าง provider จากผู้เขียน **ทุก attempt** ผล gates/review ผูกกับ base revision และ hash ที่รวมไฟล์ใหม่ด้วย หาก patch เปลี่ยนต้องทดสอบ/ตรวจใหม่ หากมีแต่ผู้ตรวจที่เป็นผู้เขียนเองจะรอ ไม่มี self-approval และ mock verdict ไม่พางานไป ready

Human approval ต้องใช้ terminal ที่โต้ตอบได้:

```powershell
.\.venv\Scripts\python.exe smart_router.py approve TASK_ID
```

ผู้ใช้ต้องพิมพ์ task ID และ prefix ของ patch hash การเรียกผ่าน pipe จะถูกปฏิเสธ ไม่มี commit/push/merge/deploy หลังอนุมัติ

## ขอบเขตที่ enforce ได้

- Center บังคับ state transitions, capacity, project/task/worktree ownership, allowed providers, dependency rules, review/authorship และ evidence identity
- ตรวจจับไฟล์เปลี่ยนนอก scope และ base/patch เปลี่ยนหลังทำงานได้ แต่ไม่ได้ป้องกัน IDE อื่นที่มีสิทธิ์บนเครื่องแก้ไฟล์ตรง
- Worktree ไม่ใช่ security sandbox; provider sandbox/restricted tools บังคับได้เฉพาะสิทธิ์ที่เครื่องมือรองรับ ไม่รับประกันการห้ามอ่านข้ามโปรเจกต์ระดับ OS
- Handoff เก็บ provider/session identity ที่ IDE รายงาน ไม่ใช่ cryptographic authentication; local CLI/SQLite เป็น trusted local boundary ต้องมี user/OS permissions เพิ่มหากเปิดให้ผู้ใช้ที่ไม่เชื่อถือ
- Gate commands/scripts เป็น config ที่ต้องตรวจและเชื่อถือก่อนใช้งาน Center ไม่สามารถรับรอง side effects ของ arbitrary project scripts

## Dashboard และ Usage Meter ในหน้าเดียว

เปิด http://127.0.0.1:3939 เพื่อดูสถานะระบบ คิวงาน หลักฐาน และ Usage Meter ในหน้าเดียว เลือกวันนี้ / 7 / 30 วันได้ พร้อม input, output, cache และกราฟรายวันตามเวลา Asia/Bangkok หน้าเว็บอัปเดตทุก 5 วินาทีโดยไม่เรียกโมเดล

Usage นับเฉพาะผล CLI จริงที่ Center บันทึกไว้ใน state ของตน ไม่ใช่ยอดรวมบัญชี ยอดเรียกเก็บเงิน หรือเปอร์เซ็นต์ quota; ค่าที่ไม่มีหลักฐานแสดงว่าไม่ทราบ ไม่อ่าน auth files หรือเรียก provider APIs ตัวเลข cache รวมอยู่ใน input แล้ว ไม่บวกซ้ำ รายการ mock ไม่นับเป็นการใช้งานจริง

หากต้องการรวมผล live smoke ที่เก็บแยกไว้ ให้สร้าง `.ai-team/usage-sources.json` เช่น `{"sources":[{"state_dir":"sandbox/runs/live-612c4b12/state","kind":"live_smoke"}]}` โดย path ต้องอยู่ใน workspace ไฟล์นี้เป็นการตั้งค่าเฉพาะเครื่องและถูก ignore จาก Git; ไม่ค้นหา session หรือ credentials นอก Center อัตโนมัติ วันที่ในกราฟอ้างอิงเวลาแก้ไข log ของ CLI

## ตรวจสอบคุณภาพ

```powershell
npm.cmd run lint
npm.cmd test
npm.cmd run test:python
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.ai-team/browsers'
npx.cmd playwright install chromium
npm.cmd run test:e2e
npm.cmd run build
```

มี unit/integration tests สำหรับ queue/concurrency, recovery, cancellation, retry/fallback, gates และ review รวมทั้ง Vitest API tests และ Playwright browser → API → SQLite tests ที่เปิดหลักฐานจากสอง sample projects Python fixtures ใช้ Git objects เดิม ไม่เรียก `git commit` ไม่มี typecheck/coverage threshold/duplication gate เดิมที่ตั้งไว้ใน Center นี้ จึงไม่อ้างว่าผ่าน checks ที่ไม่ได้กำหนด

ดู [PROJECT_STATE.md](PROJECT_STATE.md), [MIGRATION.md](MIGRATION.md) และ [HANDOFF_ANTIGRAVITY.md](HANDOFF_ANTIGRAVITY.md) สำหรับสถานะและข้อที่ยังต้อง live-verify


## รอบปรับความพร้อมหลังวิเคราะห์ร่วม Codex / Claude Code

Python เป็นเจ้าของ queue/dependencies/atomic claim และ gates เพียงตัวเดียว Maestro เป็น deterministic phase runner ไม่เปิด scheduler สองชุดแข่งกัน ตัว scheduler เลือกเฉพาะงานที่พร้อมและสลับโปรเจกต์ งานรอ dependency/provider จะไม่ขวางงานท้ายคิว Dashboard แยก backend/DB กับ scheduler heartbeat/mode และบอกเหตุผลที่งานรอ ค้นหา/กรองได้ในรายการล่าสุด 100 งาน

Routing ใช้ capacity, capability, subscription entitlement, availability/cooldown และผลสำเร็จที่สังเกตจริง ใช้ token ที่รายงานจริงเป็นตัวช่วยเมื่อทุกตัวเลือกมีข้อมูลในหน้าต่างเดียวกันเท่านั้น ไม่ถือ unknown ว่าใช้ศูนย์ token และไม่แปลง token เป็น quota subscription เมื่อพบ quota_exhausted จะเปิด provider circuit เป็น unavailable/reset unknown จนผู้ใช้ยืนยันกลับมาเอง ไม่ probe ซ้ำและไม่เสีย retry budget จาก outage

### งานต่อเนื่องและ worktree

`--depends-on TASK_ID` มีค่าเริ่มต้นเป็น ordering-only หากงานใหม่ต้องใช้โค้ดจากงานก่อนหน้า ให้ระบุ `--dependency-policy overlay` อย่างชัดเจน Center จะตรวจ approved evidence/checkpoint ของ dependency ทุกตัว นำโค้ดมาประกอบใน worktree ใหม่โดยไม่ commit/merge และเก็บ provenance กับ authorship ที่สืบทอด หาก base ต่างกัน, scope ไม่ครอบคลุมไฟล์ dependency, checkpoint เปลี่ยน หรือไฟล์ชนกัน จะ blocked ให้แก้ความขัดแย้งอย่างชัดเจน ไม่เลือกเขียนทับเอง

Review/gates ครอบคลุม composite patch เทียบ base เดิม การ retry restore composite checkpoint ครั้งเดียว ไม่เอา dependency มาบวกซ้ำ หากทุก provider ที่พร้อมเคยเขียน composite นี้ จะรอ independent reviewer หรือ human review ไม่ self-approve และการ approve ไม่ได้แปลว่าโค้ดถูกนำเข้า branch หลักแล้ว

Project config รองรับ `prepare_commands` เป็น argv arrays ที่ตรวจแล้ว เช่น `[["npm", "ci"]]` สำหรับติดตั้ง dependencies ใน worktree ต้องตรวจ side effects/การใช้ network ก่อนตั้งค่า Center ไม่เดาคำสั่งติดตั้งให้เองและไม่ส่ง secrets จาก environment กำหนด gates ให้ใช้ `AI_CENTER_TEST_PORT` และ `AI_CENTER_ARTIFACT_DIR` ในการเปิดเซิร์ฟเวอร์/เก็บผล พอร์ตจองแยกและคงที่ตลอด session แต่ยังมีโอกาสชนกับโปรแกรมภายนอกที่มา bind หลัง probe จึงต้องรายงาน gate failure ตามจริง

Template เปิด `async_handoff_gates=true`: IDE ส่ง result แล้ว Center รัน gates ใน background process ที่มี owner/heartbeat โดยไม่เรียกโมเดล ไม่ต้องค้างรอใน IDE tool call โปรเจกต์เก่าที่ไม่ตั้งค่ายังคงใช้ gates แบบ synchronous พอร์ต/phase ยังอยู่ใต้ขีดจำกัด session ที่กำหนด ไม่มี system auto-start

### Recovery, review และ policy

```powershell
.\.venv\Scripts\python.exe smart_router.py health --mode live
.\.venv\Scripts\python.exe smart_router.py resume-review TASK_ID --reason 'แก้ login ผู้ตรวจแล้ว โดย patch เดิมไม่เปลี่ยน'
.\.venv\Scripts\python.exe smart_router.py human-review TASK_ID --reason 'ผู้ใช้ตรวจ source และ gate logs เองครบแล้ว'
.\.venv\Scripts\python.exe smart_router.py approve TASK_ID
```

`human-review` และ `approve` เป็นคนละขั้น ต้องให้มนุษย์ตรวจและพิมพ์ task/hash ใน terminal จริง ห้าม agent ทำแทน และ TTY/local CLI ไม่ใช่ขอบเขตความปลอดภัยระดับ OS สำหรับโปรแกรมที่มีสิทธิ์ผู้ใช้เดียวกัน

Retry ได้รับ bounded failure excerpt/review feedback พร้อม checkpoint reference การแก้ไฟล์ที่ไม่ทราบผู้เขียนหลัง implementation จะถูกเก็บหลักฐาน drift และปฏิเสธการ adopt เงียบ ๆ ต้องตรวจ/ระบุเจ้าของและสร้างงานอ้างอิงใหม่อย่างชัดเจน

การเปลี่ยน gates/preparation/scope/providers ของ project ที่ลงทะเบียนแล้วต้องตรวจ config diff แล้วเรียก `project register ... --confirm-config-change` ผ่าน Center โดยตรง connector ไม่เพิ่ม flag นี้ให้อัตโนมัติ เก็บ hash/history และผูก policy hash กับ gate evidence Project instructions ถูกส่งพร้อม hash ให้ทั้งสอง CLI; `--read-file` ช่วยจำกัด source context ภายใน scope ที่อนุญาต กรณีเกิน 64KiB หรือ binary ที่อ่านแบบ UTF-8 ไม่ได้จะ blocked/needs_narrower_scope ไม่ตัดข้อมูลเงียบ ๆ

### Backup, maintenance และการลอง Antigravity

```powershell
.\.venv\Scripts\python.exe smart_router.py backup --verify
.\.venv\Scripts\python.exe smart_router.py maintenance
.\.venv\Scripts\python.exe smart_router.py restore-drill BACKUP_PATH --destination NEW_DIRECTORY
.\.venv\Scripts\python.exe scripts/antigravity_acceptance.py prepare
```

Backup ตรวจ SQLite integrity และบันทึก config hash/worktree/checkpoint references ต้องเก็บ source/config/worktrees/checkpoints ที่อ้างถึงคู่กันด้วย ไม่ได้ถือว่า database file รวม source ทุกชิ้น Restore drill สร้างพื้นที่ใหม่เท่านั้น ไม่ทับหรือสลับฐานข้อมูลที่ใช้อยู่ Maintenance รายงานพื้นที่และ orphan candidates โดยไม่ลบงาน

เตรียม sample Antigravity ล่าสุดไว้ที่ `sandbox/runs/antigravity-fb3e09d6/CHECKLIST.md` task `c33cd247c2c6` การ prepare/check ไม่เรียก AI, ไม่เปลี่ยน Google availability และไม่ start service ผู้ใช้ยืนยัน usage กลับมาเมื่อใดจึงทำตาม checklist ใน state แยกครั้งเดียว ผลยังเป็น pending_live_verification จนมี actual IDE evidence รวม failure/cancel scenarios ครบ

CI ที่เตรียมไว้รันเฉพาะ deterministic tests/lint/build/browser ไม่ติดตั้งหรือเรียก model CLIs และยังไม่อ้างว่า remote CI ผ่านจนมีผลจาก GitHub จริง
