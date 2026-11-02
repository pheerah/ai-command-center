# Specs B–E: ผลงานที่ตรวจได้, ล้มเหลว/โควตา, นำไปใช้, ตรวจสุขภาพระบบ

สถานะ: เขียนหลังสำรวจโค้ด ตามการตัดสินใจของผู้ใช้ (2 พ.ย. 2026): D = apply เท่านั้น ไม่ commit; E = อ่านอย่างเดียว (ตรวจสุขภาพระบบ)
ทำงานต่อเนื่องตามคำสั่ง "ทำให้ครบแล้วรันเทสต์ทีเดียว" จึงไม่มีจุดรออนุมัติระหว่าง spec ผู้ใช้รีวิวได้ตอนส่งมอบ

## สิ่งที่มีอยู่แล้ว (สำคัญต่อการออกแบบ)

- `center_api._task_detail` ให้ events + evidence (ชนิด/ผล) ต่อ task; `export_patch` ให้ diff + ไฟล์ใหม่ (base64) เมื่อ task อยู่ที่ `ready_for_human_approval`/`approved`
- **การอนุมัติบนเว็บ (`POST /api/tasks/:id/approve`) อนุมัติแล้วนำ patch ไปใช้ในโปรเจกต์ทันที** (`approve --yes` → `Center.approve` + `Center.auto_apply`: `git apply --check` แล้ว `git apply`, ไม่ commit) ถ้า apply ล้มหลังอนุมัติ task จะค้างเป็น `approved` โดยยังไม่ได้ apply
- ไม่มี op "ปฏิเสธพร้อมเหตุผล" และไม่มี op "สั่งแก้ซ้ำใน task เดิม"; `reconcile` (เดิม) คิวงานใหม่ได้เฉพาะ task ที่ `failed/blocked` และไม่ผ่อนกฎ "Attempt limit reached"
- กฎที่ห้ามผ่อน: Center ไม่รัน `git commit/push/merge/...` (`test_no_git_actions`), `auto_commit=false`, อนุมัติต้องผ่านหลักฐาน/ patch hash ปัจจุบัน

## B. หน้าดูผลงาน (Review)

**เป้าหมาย:** เห็น diff, ผล gates, ผลรีวิว, ไฟล์ที่เปลี่ยน และตัดสินใจได้ในหน้าเดียว: อนุมัติ (+apply เดิม), ปฏิเสธพร้อมเหตุผล, สั่งแก้ซ้ำใน task เดิมพร้อมคำสั่ง

**Backend (`center_api`, ops สำหรับ dashboard เท่านั้น ไม่เปิดใน `/api/v1`):**
- `review` (`task_id`) → `{task, changes: {files:[{path, status, added, removed}], diff: <unified diff text, ตัดที่ 200 KB>, truncated, untracked:[{path, size, preview}]}, gates: [{command, passed, seconds}], review: {verdict, summary, provider}, human_reviews: [...], applied: bool, actions: {approve, reject, rework, apply}}` ข้อความทั้งหมดผ่าน `scrub` ทีละ field (ไม่ scrub JSON ทั้งก้อน)
- `reject` (`task_id`, `reason` 1–1000 ตัวอักษร): `ready_for_human_approval → rejected` (ใหม่ใน `TRANSITIONS`; terminal), บันทึก event `human_rejected{reason}`; ไม่ apply อะไร
- `rework` (`task_id`, `instructions` 1–2000 ตัวอักษร): ได้เฉพาะ `ready_for_human_approval` ที่ไม่มี session และยังไม่เกิน `max_attempts` → เปลี่ยน `ready_for_human_approval → waiting_for_independent_review → blocked → queued` ตามที่ state machine เดิมอนุญาต (หรือเพิ่ม edge `ready_for_human_approval → queued` ผ่านเมธอดเดียว) บันทึก event `human_rework_requested{instructions}`; `_prior_attempt` เพิ่ม `human_instructions` (ตัดที่ 2000) เพื่อให้ attempt ถัดไปเห็น คำสั่งแก้ล้อมเป็นข้อมูล (ไม่ใช่คำสั่งระบบ) กฎ attempt limit ไม่ผ่อน
- `approve` เดิม (`/api/tasks/:id/approve`) ไม่เปลี่ยน

**UI:** ปุ่ม "ตรวจผลงาน" ในการ์ดงาน/บนกระดาน/modal เลขาฯ เปิดแผงตรวจ: แท็บ "การเปลี่ยนแปลง" (diff แบ่งสีบรรทัด + เพิ่มจำนวนบรรทัด), "ผลตรวจ" (gates + รีวิว), ปุ่ม อนุมัติ/ปฏิเสธ(ต้องกรอกเหตุผล)/สั่งแก้(ต้องกรอกคำสั่ง) ข้อความทั้งหมดตั้งด้วย `textContent`

## C. ล้มเหลวและโควตา

**เป้าหมาย:** งานที่ติดขัดบอกสาเหตุเป็นภาษาไทยที่เข้าใจได้ และมีปุ่มทางออกที่ปลอดภัย
- `diagnose` (`task_id`) → `{reason_code, explanation_th, suggestions:[{action, label_th, enabled}]}` จากตารางเดียว `FAILURE_ADVICE` (quota ต่ำ/หมด, gate ไม่ผ่าน, ผู้ตรวจปฏิเสธ, provider ไม่พร้อม, หมดเวลา, scope ใหญ่เกิน, ถึงจำนวนครั้งสูงสุด, ไม่รู้สาเหตุ) ใช้ค่าจาก `task.error` + evidence + `provider_status`/quota
- action `retry` (= `reconcile` เดิมพร้อมเหตุผลคงที่ `owner_retry_from_web`, ต้องไม่มี worker ที่ยังมีชีวิต, ไม่ผ่อน attempt limit) และ `switch_provider` (= `reconcile` พร้อม `provider` ที่อยู่ใน `allowed_providers` และยังไม่เคยลอง)
- UI: ในแผงตรวจแสดงสาเหตุ + ปุ่ม "ลองใหม่" / "ลองด้วย <provider>" ที่ `enabled` เท่านั้น

## D. นำไปใช้ (apply เท่านั้น)

- `apply` (`task_id`): สำหรับ task สถานะ `approved` ที่ยังไม่มี event `auto_applied_to_workspace` (apply ล้มหลังอนุมัติ) → `Center.auto_apply` (เดิม: `git apply --check` แล้ว apply) ล้มแล้วรายงานสาเหตุ (เช่น base เปลี่ยน) ไม่ลบอะไร
- แผงตรวจแสดงสถานะ: "ยังไม่ได้อนุมัติ" / "อนุมัติแล้ว ยังไม่ได้ apply [ปุ่ม apply]" / "apply แล้ว" พร้อม **ข้อความ commit ที่แนะนำ** (จากชื่องาน + รายการไฟล์) ให้คัดลอก ไม่มีปุ่ม commit และไม่มีโค้ดที่รัน git commit (`test_no_git_actions` ต้องผ่านต่อ)

## E. ตรวจสุขภาพระบบ (อ่านอย่างเดียว) ผ่านเลขาฯ

- เลขาฯ ตอบคำถามเรื่องระบบ (scheduler ทำงานไหม, provider/โควตา, งานค้างเพราะอะไร) โดย Center ใส่ **ข้อมูลสุขภาพ** (scheduler running/heartbeat, provider availability+quota ที่ลบ path, จำนวนงานต่อสถานะ, งานติดขัดพร้อม `diagnose`) ลงในบล็อกข้อมูลของ prompt (`build_context` เพิ่มบล็อก `system health`) เมื่อข้อความเกี่ยวกับระบบ (คำสำคัญ: scheduler, โควตา, provider, ระบบ, ค้าง, ทำไมงาน) หรือเสมอแบบย่อ
- แก้ค่าตั้งค่า/แก้ตัว Center ไม่ได้: กฎระบบ (`SYSTEM_RULES`) ระบุว่าเป็นอ่านอย่างเดียวอยู่แล้ว; ไม่เพิ่ม op เขียนใด ๆ

## ความปลอดภัยและกฎร่วม

- ops ใหม่ทั้งหมดเข้าถึงได้ผ่าน route ของ dashboard เท่านั้น (ตรวจ Origin/Host เดิม) ไม่อยู่ใน `V1_ROUTES`
- ทุกการเปลี่ยนสถานะผ่าน `transition()` + หลักฐานเดิม; ไม่มีการลดกฎ attempt limit, patch fence, หรือการตรวจ patch hash
- ผล/ข้อความที่แสดง ไม่มี path ของเครื่อง/state (scrub รายฟิลด์)
- ขอบเขตที่ไม่ทำ: commit/push, การแก้ config จากเว็บ, streaming diff ขนาดใหญ่เกิน 200 KB (ตัดและบอกว่าถูกตัด)
