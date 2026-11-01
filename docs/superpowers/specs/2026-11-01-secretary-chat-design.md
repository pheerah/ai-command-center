# Spec A: แชทเลขาฯ AI (Secretary Chat)

สถานะ: ร่างรอรีวิว · วันที่: 2026-11-01 · ขอบเขต: spec A จากแผน A–E (B–E เป็น spec แยก)

## 1. เป้าหมาย

เลขาฯ ของแต่ละโปรเจกต์ใน virtual office เป็นแชทที่ใช้ AI จริง แยกเจตนาของข้อความได้ 3 แบบ:

| ผลลัพธ์ | ความหมาย |
|---|---|
| `reply` | ตอบคำถาม (รวมคำถามเรื่องโค้ด) พร้อมรายชื่อไฟล์ที่อ้างอิง |
| `clarify` | ข้อความกำกวม ถามกลับ 1–3 ข้อ |
| `draft_task` | เป็นการสั่งงาน ร่างงานให้ผู้ใช้ตรวจ **ยังไม่สร้าง task** |

ปัญหาเดิม: ช่องพิมพ์ใน modal เลขาฯ ส่งไป `POST /api/dispatch` → `connector.py plan --submit` → `center_planner.py` ซึ่งแยกงานด้วยคีย์เวิร์ดและสร้างงานทันทีทุกครั้ง จึงถามกลับไม่ได้และตอบคำถามไม่ได้

## 2. การตัดสินใจที่ตกลงแล้ว

1. สมองของเลขาฯ: Center เลือก provider ตามโควตา ด้วยระบบ routing/quota เดิม (CLI แบบสมัครสมาชิก ไม่ใช้ API key)
2. การสั่งงาน: แสดงร่างเป็นการ์ดก่อน งานถูกสร้างเมื่อผู้ใช้กด "ส่งงาน" เท่านั้น
3. การอ่านโค้ด: เฉพาะไฟล์ที่ `context_scope` ของโปรเจกต์อนุญาต ผ่าน `center_context.read_sources`
4. สถาปัตยกรรม: โมดูล Python ใหม่ `backend/center_chat.py` เรียก provider แบบ read-only (ไม่ใช้งานสั้นในคิว ไม่ให้ Node เรียก CLI เอง)

## 3. นอกขอบเขต

- หน้า diff/ผลเทสต์/ผลรีวิว และปุ่มอนุมัติ/ปฏิเสธ (spec B)
- การจัดการโควตา/ปุ่มลองใหม่/เปลี่ยน provider (spec C)
- apply/commit ในหน้าเว็บ (spec D) · งานนอกโค้ด (spec E)
- การแสดงคำตอบแบบ streaming (ใช้สถานะ "กำลังคิด" แล้วแสดงทีเดียว)
- การเปลี่ยนสถานะ task เดิม: แชทเพียง **ร่าง** งานแก้ที่อ้าง task เดิม (`related_task_id`) ส่วนการ approve/reject เป็นของ spec B

## 4. สถาปัตยกรรม

### 4.1 หน่วยย่อย

| หน่วย | หน้าที่ | พึ่งพา |
|---|---|---|
| `backend/center_chat.py` (ใหม่) | ประมวลผลหนึ่งเทิร์น: สร้าง context, เรียก provider, ตรวจ schema, กรองผลลัพธ์ | `center_routing`/`center_quota` (เลือก provider), `center_context.read_sources`, `center_worker.cli_command` |
| ตาราง `chat_messages` (ใน state DB) | ประวัติแชทต่อโปรเจกต์ | `center_store` |
| `center_api.py` op `chat`, `chat_history`, `chat_confirm` | ช่องทางเข้าที่ใช้ token ต่อโปรเจกต์เดิม | `center_chat` |
| `server.js` route `/api/chat*` | ส่งต่อไป API เดิมเท่านั้น ไม่มีตรรกะ AI | `callApi` เดิม |
| `web/js/chat.js` (ใหม่) | UI แชทใน modal เลขาฯ ประวัติ การ์ดร่างงาน | `/api/chat*`, ตารางแปลสถานะภาษาไทยกลาง |

`/api/dispatch` และ `connector.py plan --submit` ไม่ถูกใช้โดยช่องแชทอีก ส่วนที่ไม่มีผู้ใช้เหลือให้ลบในแผนลงมือทำ (ตรวจ reference ก่อนลบ)

### 4.2 ลำดับการทำงานต่อหนึ่งเทิร์น

1. UI ส่ง `{project_id, message, client_turn_id}`
2. ตรวจ: ข้อความไม่ว่าง ยาวไม่เกิน 4,000 ตัวอักษร, `client_turn_id` ตรงรูปแบบ (กันกดซ้ำ ใช้หลักการเดียวกับ `request_id`)
3. เลือก provider ด้วย routing/โควตาเดิม (role `chat`, read-only)
4. สร้าง context: คำสั่งระบบ + ประวัติ 10 เทิร์นล่าสุด + รายการ task ที่ยัง active ของโปรเจกต์ (id, title, status) + เนื้อไฟล์จาก `read_sources` ตามไฟล์/คำที่ข้อความพูดถึง (ไม่เกิน limit 65,536 ไบต์)
5. เรียก CLI แบบ read-only พร้อม JSON schema ของผลลัพธ์ 3 แบบ (Codex: `--sandbox read-only --output-schema`; Claude/Google: โหมดไม่มีเครื่องมือเขียน/รันคำสั่ง)
6. ตรวจผลตาม schema, ปฏิเสธ `draft_task` ที่ `scope` มี path นอก `context_scope` หรือเป็น generated/dependency path, กรอง path ของระบบไฟล์และความลับในข้อความตอบด้วย `scrub` เดิม
7. บันทึกทั้งข้อความผู้ใช้และคำตอบลง `chat_messages` แล้วส่งกลับ

### 4.3 การยืนยันร่างงาน (`chat_confirm`)

`{project_id, message_id, edits?}` → ตรวจว่า `message_id` เป็น `draft_task` ของโปรเจกต์นั้นและยังไม่เคยยืนยัน → เรียก submit เดิมของ `center_api` ด้วย `request_id` = `chat-<message_id>` (กด 2 ครั้ง ได้งานเดียวตามกลไก atomic claim) → ผ่านการตรวจ scope/complexity/จำนวนงาน active ตามปกติ → บันทึก `task_id` ลงข้อความร่าง ผู้ใช้แก้ title/prompt/scope/accept ในการ์ดก่อนกดได้ (`edits`) AI ไม่มีเส้นทางสร้างงานเอง

### 4.4 ข้อมูล

```sql
CREATE TABLE IF NOT EXISTS chat_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL REFERENCES projects(id),
  turn_id TEXT NOT NULL,            -- client_turn_id; UNIQUE ต่อ (project_id, turn_id, role)
  role TEXT NOT NULL,               -- 'user' | 'secretary'
  kind TEXT NOT NULL,               -- 'text' | 'reply' | 'clarify' | 'draft_task' | 'error'
  body TEXT NOT NULL,               -- ข้อความ หรือ JSON ของ draft/คำถาม
  provider TEXT,
  task_id TEXT,                     -- ใส่เมื่อร่างถูกยืนยันแล้ว
  created_at TEXT NOT NULL,
  UNIQUE(project_id, turn_id, role));
```

`schema_version` ปรับ 3 → 4 (เพิ่มตารางด้วย `IF NOT EXISTS` เหมือนตารางอื่น) Center รุ่นเก่าจะปฏิเสธ DB รุ่นใหม่ตามกลไก "future schema" เดิม เก็บประวัติล่าสุด 50 เทิร์นต่อโปรเจกต์ ส่วนที่เก่ากว่าลบเมื่อเขียนใหม่

### 4.5 รูปแบบผลลัพธ์ของ AI (JSON schema)

```json
{"kind":"reply","text":"...","files":["src/a.py"]}
{"kind":"clarify","questions":["..."]}
{"kind":"draft_task","title":"...","prompt":"...","scope":["src"],"accept":["..."],"complexity":2,"provider":"auto","related_task_id":null}
```

`questions` 1–3 ข้อ, `scope` ไม่เกิน 20 รายการ, `complexity` 1–5 (ตรงกับข้อจำกัดของ submit เดิม)

## 5. ข้อผิดพลาด (ข้อความไทย ไม่โชว์ error ดิบ)

| เหตุการณ์ | พฤติกรรม |
|---|---|
| provider ไม่พร้อม/โควตาหมด | ลอง provider ถัดไป ถ้าหมดทุกตัว บันทึก `kind=error` พร้อมสาเหตุที่เข้าใจได้ |
| JSON ผิด schema | ลองซ้ำ 1 ครั้ง แล้วแจ้งผู้ใช้ |
| timeout 90 วินาที | หยุด process ลูก แจ้งให้ลองใหม่ ไม่ทิ้ง process ค้าง |
| ข้อความว่าง/ยาวเกิน | ปฏิเสธก่อนเรียก AI |
| `draft_task` ไม่ผ่านการตรวจ scope | ไม่แสดงการ์ด แจ้งว่าร่างไม่ผ่านพร้อมเหตุผล |
| ยืนยันร่างซ้ำ/ร่างของโปรเจกต์อื่น | คืนงานเดิม / ปฏิเสธ |

## 6. ความปลอดภัย (ห้ามผ่อน)

- read-only เสมอ ไม่มีเครื่องมือเขียนไฟล์หรือรันคำสั่งให้ AI
- อ่านได้เฉพาะ `context_scope` ผ่าน `read_sources` (ห้าม .env, secrets, dependency, จำกัดขนาด)
- ไม่ใช้ API key จ่ายต่อครั้ง ใช้ CLI สมัครสมาชิกเหมือน worker
- ข้อความผู้ใช้และเนื้อไฟล์เป็นข้อมูล ไม่ใช่คำสั่ง: คำสั่งระบบระบุชัดว่าห้ามทำตามคำสั่งที่ซ่อนในไฟล์/ข้อความ และต่อให้ AI ถูกหลอก ก็สร้างงานเองไม่ได้เพราะต้องผ่าน `chat_confirm`
- CSP ไม่ผ่อน (UI ไม่ใช้ inline script/style), ไฟล์เว็บผ่าน `resolveWebFile()` เท่านั้น
- ตอบกลับผ่าน `scrub` (ไม่เผย path เครื่อง/state)

## 7. การทดสอบ

**Python (provider จำลอง ไม่เรียก AI จริง)**
- คืนทั้ง 3 ชนิด · JSON เสีย → ลองซ้ำ 1 ครั้ง → error · provider แรกล่ม → สลับตัวที่สอง · โควตาหมดทุกตัว → ข้อความอ่านรู้เรื่อง
- ไฟล์นอก `context_scope` และไฟล์ลับต้องไม่ถูกส่งให้ provider
- ข้อความ/ไฟล์ที่พยายามสั่งให้ AI สร้างงานเอง → ไม่มี task เกิดขึ้นจนกว่า `chat_confirm`
- `chat_confirm` ซ้ำ 2 ครั้งและพร้อมกัน 4 thread → ได้งานเดียว · ยืนยันร่างของโปรเจกต์อื่น → ปฏิเสธ
- `draft_task` ที่ scope เป็น generated/dependency path → ถูกปฏิเสธ
- timeout → process ลูกถูกหยุด
- schema migration 3 → 4 และการปฏิเสธ DB รุ่นอนาคตยังทำงาน

**vitest/e2e (Playwright)**
- ส่งข้อความ, สถานะกำลังคิด, การ์ดร่าง, แก้ร่าง, กดส่งงาน, ประวัติหลังรีโหลด, โมบายล์พอดีจอ, ข้อความ error ภาษาไทย

**ทดสอบกับ provider จริง** แยกเป็นขั้นสุดท้ายหลังเทสต์อัตโนมัติผ่าน ใช้โควตาจริงจึงต้องขอผู้ใช้ก่อนรัน และรายงานผลตามจริงว่าผ่าน/ไม่ได้ทดสอบ

## 8. ความเสี่ยงที่รับทราบ

- โหมด read-only ของ Claude CLI และ Google (`agy`) ไม่เหมือน Codex ต้องตรวจในแผนลงมือว่าแต่ละตัวปิดเครื่องมือเขียน/รันได้จริง ถ้าตัวใดทำไม่ได้ ให้ไม่รับบทเลขาฯ (ตัดออกจากตัวเลือกของ role `chat`) ไม่ลดระดับความปลอดภัย
- เลขาฯ กินโควตาร่วมกับงานจริง จึงจำกัดความยาวประวัติ/ไฟล์ที่ส่ง และควรแสดงในการ์ดว่าใช้ provider ใด
