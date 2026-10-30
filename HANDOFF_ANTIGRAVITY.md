# รับช่วงเมื่อ Google พร้อม

Google ยังคง unavailable / usage_exhausted / reset unknown ห้ามทดลองเรียกซ้ำหรือเปลี่ยนบัญชีเพื่อหลบ quota

## สิ่งที่ใช้ได้ในเครื่อง

- SQLite durable queue, project registry, scoped worktrees, dispatch/start records, leases, checkpoints, bounded retries และ audit events
- Codex/Claude adapters ผ่าน live implementation/gates/review จริงแล้วทั้งสองบทบาท Maestro รัน command phases โดย Python เป็นผู้จองงาน
- Mock pipeline ของสอง sample projects, independent authorship checks, gates และ dashboard
- Connector template รองรับ health/register/submit/status/claim/worker-start/heartbeat/result/error

## Live verification ที่ยังค้าง

1. ยืนยันจากผู้ใช้ว่า Google quota กลับมาแล้ว ห้ามเดาเวลาหรือ probe model เพื่อเช็ก quota
2. ตรวจเอกสาร Antigravity รุ่นที่ติดตั้งและช่องทางที่รองรับจริง ไม่สมมติ consumer CLI wrapping/OAuth endpoint
3. ใช้ sample project เท่านั้น คัดลอก connector template ปรับ canonical paths และลงทะเบียน
4. ทดสอบ IDE health → submit → explicit claim → worktree → worker-start พร้อม actual IDE session ref → deterministic heartbeat → result/gates → independent review → human approval
5. ทดสอบว่า Center ติดต่อไม่ได้แล้ว IDE รายงาน blocked ไม่รับไปทำทั้งหมดเอง และ heartbeat ล้มเหลวแล้วหยุดแก้ไฟล์
6. พิสูจน์ provider/model/session reference ที่เครื่องมือจริงส่งให้ ก่อนเรียกสถานะว่า live-tested; handoff identity ปัจจุบันเป็น reported identity
7. Codex/Claude subscription adapters ทดสอบครบแล้วใน `sandbox/runs/live-612c4b12/live-summary.json` ไม่ต้องเรียกซ้ำเพื่อพิสูจน์เรื่องเดิม ตรวจ authentication/CLI version ใหม่เฉพาะเมื่อมีการเปลี่ยนแปลง ห้ามเปลี่ยนไป paid API
8. ตรวจ cancellation/process cleanup และ patch scope กับเครื่องมือจริง ถ้า reviewer จากอีก provider ไม่พร้อม ต้อง waiting_for_independent_review ไม่มี mock approval

## หลักฐานที่ต้องเก็บ

task/project ID, provider/model/session refs, attempt/worktree/base revision, checkpoint/hash, dispatch/start events, gate logs, independent review verdict และ human approval ที่ผูกกับ patch เดียวกัน ไม่เก็บ secrets/auth files/full chat history

ไม่ต้องอ่าน source ทุกโปรเจกต์ใหม่ทุกงาน ใช้ project instructions + scoped task data + patch-first handoff ขยาย context เฉพาะเมื่อจำเป็น Status polling ใช้โปรแกรมหรือ dashboard ไม่ใช้ AI reasoning loop ไม่มี commit/push/merge/deploy อัตโนมัติ

เอกสารที่ตรวจระหว่างพัฒนา: [Codex noninteractive](https://learn.chatgpt.com/docs/non-interactive-mode), [Claude CLI](https://code.claude.com/docs/en/cli-reference), [Maestro upstream](https://github.com/tiagojcperez/maestro-cli)

ตรวจ discovery format กับ [Antigravity Rules](https://antigravity.google/docs/rules/) และ [Skills](https://antigravity.google/docs/skills) แล้ว `.agents/rules/*.md` ของ template มี YAML trigger=always_on และ skill มี name/description ถูกต้อง มี local connector check กับ task จริงที่เสร็จแล้ว โดยไม่ได้เรียก Google model หรือแก้ global settings
