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

## เปลี่ยน IDE เป็น Claude Code (31 ต.ค. 2026)

- ช่องทางสั่งงานหลักเปลี่ยนจาก Antigravity เป็น VS Code Claude Code ของแต่ละโปรเจกต์ ใช้ `scripts/install_project.py` และ template `connector-template/CLAUDE.md` + `.claude/skills/ai-command-center` (แทน `.agents/`)
- พิสูจน์แล้วใน sample แยก state: Claude Code handoff จริง + heartbeat จาก watcher + gates + Codex review จริง → ready_for_human_approval ยังไม่ได้ทดสอบ failure scenarios ด้วยมือ (Center ติดต่อไม่ได้, lease loss, cancellation) และยังไม่ได้ติดตั้งลงโปรเจกต์จริง
- Dashboard มี `/api/quota` อ่าน quota 5 ชม./รายสัปดาห์สดของ Codex (session log), Claude (เรียก CLI ของ Claude เองแล้วอ่าน rate_limit_event) และ Google (`RetrieveUserQuotaSummary` ของ Antigravity language server ในเครื่อง ใช้ได้เมื่อ Antigravity เปิดอยู่) การ์ด Codex แสดงเป็น ChatGPT
- Google เปิดเป็น available แล้ว (adapter `agy` headless, ผ่าน live: Google เขียน → gates → Codex ตรวจอิสระ → ready_for_human_approval ใน state แยก) Google เป็นผู้ตรวจยังไม่ได้ทดสอบ
- Center เลือก provider ตาม quota จริง, model ตามแคตตาล็อกจริง, effort ตามความซับซ้อน/quota และ skill ตามชนิดงาน ดู README หัวข้อ "Center เลือกเอง" ทดสอบ failure scenarios ด้วยมือแล้วใน sample แยก: Center ติดต่อไม่ได้ → blocked, lease หลุด → watcher หยุดแก้ไฟล์, ยกเลิก → slot ถูกกันไว้จน worker-stopped
- เพิ่ม `--hold-for-ide` เพราะ scheduler หยิบงาน live ที่ submit ไปรันเองทันที (เจอระหว่างทดสอบ) โหมดนี้ใช้ได้เฉพาะ connector แบบไฟล์ (`connector_local.py`, ผู้ดูแล Center เท่านั้น)
- **API สำหรับโปรเจกต์อื่น (/api/v1)** พร้อมแล้ว: token ต่อโปรเจกต์, connector HTTP, ตัวติดตั้งที่ไม่ส่ง path ของ Center ให้โปรเจกต์ ดู README หัวข้อ API ทดสอบ end-to-end จริงใน sample แยก: Center เลือก Codex (gpt-6-luna, effort low, skill TDD) เขียน, Claude (haiku, low) ตรวจอิสระ, gates ผ่าน, `patch` ส่งออกได้, `apply` ปฏิเสธก่อนอนุมัติ และเขียนไฟล์ได้เมื่อ (จำลองใน sandbox เท่านั้น) สถานะ approved
- **Usage meter เป็นของ Python ที่เดียว** (`center_quota.py` → `quota-last.json`) เลิกอ่าน `~/.claude/.credentials.json` หลังรอบตรวจพบว่าขัดกับกฎ no-credential-reading
- ผลตรวจรอบสองจาก 3 AI (Claude, Google, Codex) ที่ใช้แก้: build.js ขาดโมดูลใหม่, เปิดเผย patch_hash, lockout ข้ามโปรเจกต์, ไม่มีเพดานโหลด/งานซ้ำ, ตรวจ checkpoint ก่อน export, path ใน apply, token store race, ตัวติดตั้งรับ root ที่ซ้อนกับ Center ข้อที่ปฏิเสธเพราะขัดกับหลักฐาน: Google ว่า adapter agy เสีย (ทดสอบ live ผ่านแล้ว ไฟล์ agy เป็น .exe จริง และรุ่น model มาจาก `agy models`)

## ให้ Google เขียน / Codex ตรวจ ผ่าน Center เอง (31 ต.ค. 2026)

- ใช้ Center สร้างงานจริงใน repo สำเนาแยก (นอกโฟลเดอร์ Center) ให้ Google เขียน `scripts/autostart.py` + test และ test ยกเลิกงานที่ตัวรันตาย รอบแรก Codex (gpt-6-sol, effort medium) ตรวจเจอข้อผิดพลาดจริงในโค้ดของ Google และปฏิเสธ รอบที่สอง gate ล้มด้วย test ที่ Google เขียนเอง (ไม่ผ่านขั้นตรวจ) ผมจึงรับร่างมาแก้เองแล้วรัน test ผ่าน ไม่ได้ผ่านขั้น independent review ครบวงจรสำหรับเวอร์ชันที่ลงในรีโป
- ข้อค้นพบที่แก้แล้ว: โมเดล `claude-opus-4-6-thinking` ผ่าน agy ใน headless พยายามรัน command ที่ถูกปฏิเสธแล้วจบเทิร์นโดยไม่มีผลลัพธ์ จึงถอนออกจากแคตตาล็อก Google (เหลือ Gemini 3 ระดับ) และการเลือก skill เคยตัดสินจากคำทั่วไปใน prompt ตอนนี้ดูชื่อเรื่องก่อน
- ผลวิเคราะห์ cancel กับ owner ที่ตายแล้ว: `recover()` ปิดงานให้หลัง lease หมดอายุ (≤ lease_seconds) ไม่ใช่ทันที (test `expectedFailure` บันทึกไว้เป็นพฤติกรรมตามดีไซน์ และมี test ที่ผ่านสำหรับกรณี lease หมด)
- ข้อจำกัดของการ host ตัวเอง: test ชุดเดิมของ Center คัดลอก `.git/objects` จากราก repo จึงรันใน worktree ของ Center ไม่ได้ ต้อง gate ด้วยไฟล์ test ที่ไม่ใช้ fixture นี้

## ปิดช่องว่างจาก Audit (31 ต.ค. 2026) — แบ่งงานให้ ChatGPT/Google

คำตอบผู้ใช้: ใช้ hooks ระดับโปรเจกต์, ผู้ใช้ยืนยัน Google ใน config, สำรองจำนวน session ของ IDE ใน config

| ช่องว่างใน Audit | สถานะตอนนี้ | ใครทำ |
|---|---|---|
| บังคับไม่ให้ Claude Code แก้ checkout เอง | Hook ติดตั้งอัตโนมัติ ทดสอบกับ Claude Code CLI จริง (`scripts/claude_acceptance.py`); ส่วนขยาย VS Code ยังต้องลองมือ | Google เขียนร่าง (ผ่าน Center, Codex ตรวจปฏิเสธรอบแรก) ผมเพิ่มการป้องกันไฟล์ควบคุม/fail-closed/anchor ตามตำแหน่งติดตั้ง หลัง Codex ตรวจรอบสอง |
| ยืนยัน Google เป็น subscription | ต้อง attest ใน terminal ก่อนเรียก Google (Google จึงถูกบล็อกจนกว่าผู้ใช้ attest) | ผม |
| นับ session ของ Claude Code | `ide_reserved_sessions` หักจากความจุ + แสดงว่านับ session นอก Center ไม่ได้ | ChatGPT (Codex) เขียนโมดูล `center_capacity.py` Google ตรวจอนุมัติ; Codex ร่างชุดแก้ผสานเข้า runtime ผมใช้และทดสอบ |
| gate ล้ม/review ปฏิเสธแล้วทำซ้ำเอง | `auto_retry` มี test (ไม่ retry error สิทธิ์, evidence เสียไม่ล้มทั้งชุด) | ผม ตามข้อติของ Codex |
| ไม่มี test เชิงลบเรื่อง commit/push | `tests/test_no_git_actions.py` (static AST) | ผม |
| gate preset | `scripts/gate_presets.py` + `--detect-gates` | Google เขียน Codex ปฏิเสธ 2 รอบ ผมแก้ตามข้อติ |

บทเรียนจากการแบ่งงาน: ผู้ตรวจ Codex เจอข้อบกพร่องจริงในงานของ Google ทุกชิ้น (3 จาก 3) Google เป็นผู้ตรวจครั้งแรกอนุมัติงานของ Codex ใน 1 รอบ ซึ่งยังไม่พอสรุปว่า Google ตรวจเข้มพอ Codex ผ่าน Center แก้ไฟล์ใหญ่ (เช่น `center_runtime.py`) ไม่ได้เพราะเกินขนาด context และ sandbox ฝั่ง Windows ไม่ให้เขียนไฟล์ จึงใช้แบบร่างชุดแก้ที่ผมตรวจและใช้เอง

ยังเปิดอยู่: ทดสอบ hook กับส่วนขยาย VS Code จริง, Bash guard ยังเป็น heuristic, การ attest/อนุมัติใช้ TTY ซึ่ง agent บนเครื่องเดียวกันเลียนแบบได้, ยังไม่ได้ติดตั้งลงโปรเจกต์จริง, ยังไม่ได้ commit, adaptive concurrency ตาม RAM/CPU ยังไม่ได้ทำ (ผู้ใช้เลือกแค่การสำรองจำนวน)

## แชทเลขาฯ AI (2 พ.ย. 2026)

- ทำครบตาม spec A: `backend/center_chat.py`, `backend/center_chat_store.py`, op `chat` / `chat_history` / `chat_confirm` ใน `center_api.py`, route `/api/chat*` ใน `server.js` (เฉพาะ dashboard, token ของโปรเจกต์เข้าไม่ถึง), `web/js/chat.js`
- ทดสอบแล้ว: เทสต์ Python `test_chat_*.py` (provider จำลอง), vitest, Playwright `secretary-chat.spec.js` ด้วย mock adapter
- ทดสอบกับ provider จริงแล้ว (2 พ.ย. 2026, repo ทดลองใน temp + ไฟล์ลับล่อเป้านอกโปรเจกต์, 3 เทิร์นต่อ provider: คำถามปกติ / คำสั่งแฝงในไฟล์ / ขอให้อ่านไฟล์นอก scope):
  - **Claude** (ไม่มี tool): ผ่านทั้ง 3 เทิร์น ตอบถูกรูปแบบ ไม่ทำตามคำสั่งแฝง (บอกผู้ใช้ว่าไฟล์มีคำสั่งแฝง) ไม่เปิดเผยไฟล์ลับ ไฟล์ใน repo ไม่เปลี่ยน ไม่มี task ถูกสร้าง
  - **Codex** (`--sandbox read-only`): ไม่รั่ว ไม่แก้ไฟล์ ไม่สร้าง task แต่เทิร์นแรกหมดเวลา 90 วินาที 1 ครั้ง (อีก 2 เทิร์นตอบใน 6-8 วินาที) และการสั่งตรง ๆ ให้ shell อ่านไฟล์นอกโปรเจกต์ถูกปฏิเสธด้วย "blocked by policy" บนเครื่องนี้ (Codex 0.164, Windows) ทดลองครั้งเดียวจึงยังไม่ใช่การรับประกัน จึงยังไม่เปิดเป็นค่าเริ่มต้น
  - **Google (agy)**: **ยังไม่ได้ทดสอบ** ระบบความปลอดภัยของ Claude Code ปฏิเสธการรัน เพราะคำสั่งต้องใช้ `--dangerously-skip-permissions` จึงยังปิดอยู่
  - ผ่านเฉพาะกรณีที่ทดสอบ ไม่ใช่การรับประกันว่า prompt injection ทุกแบบจะถูกกัน (การปฏิเสธของโมเดลเป็นชั้นป้องกันที่เชื่อถือได้ไม่เต็มที่ ชั้นที่แน่นอนคือ Claude ไม่มี tool และไม่มีเส้นทางสร้างงานโดยไม่กดยืนยัน)

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
