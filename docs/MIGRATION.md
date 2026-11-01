# Migration และ rollback

## จาก Router v1 เป็น v2

1. หยุด legacy workers และ usage server เดิมก่อน ห้ามเปิดสองเวอร์ชันเขียนฐานข้อมูลเดียวกัน
2. ตรวจ `git status` และเก็บงานค้างของผู้ใช้ไว้ ห้าม reset/clean หรือทับไฟล์จาก backup โดยไม่ตรวจ diff
3. ก่อนเริ่มแก้ครั้งนี้ เก็บสำเนา source เดิมที่ `.ai-team/recovery/pre-v2/` โดยไม่ได้ commit งาน
4. การเปิด `doctor/status` ครั้งแรกจะตรวจ schema และสำรอง SQLite ผ่าน backup API ไป `.ai-team/backups/` ก่อน migrate ใช้ snapshot ที่สอดคล้องกับ WAL ไม่คัดลอกเฉพาะ main database file
5. หาก v1 slot มี PID ที่ยังมีชีวิตหรือ lease ยังไม่หมด จะปฏิเสธ migration และไม่ฆ่า process ใด
6. เพิ่มคอลัมน์/ตาราง sessions, authorship, evidence, provider_health, center_meta โดยรักษา projects/tasks/events และ provider_slots เดิมไว้
7. งาน v1 ที่ยังไม่ terminal จะเป็น `blocked` / `legacy_task_requires_reconciliation` ไม่เชื่อถือ ready/review เดิมที่ไม่ผ่านกฎ v2 งาน approved เดิมเก็บเป็นประวัติ ไม่สร้างหลักฐาน v2 ย้อนหลัง
8. Config โปรเจกต์ v1 ต้องแก้ gates จาก string เป็น argument arrays และลงทะเบียนยืนยันใหม่ งานเก่าอาจไม่มี scope/base/config snapshot จึงควรสร้างงานใหม่อ้างถึงงานเก่า โดยรักษา worktree/patch เดิมไว้ ไม่สั่ง retry legacy task แบบเดา ownership

## สำรองเพิ่ม

```powershell
.\.venv\Scripts\python.exe smart_router.py backup
```

สำรอง source/config, database และ checkpoints/worktrees คู่กัน ตรวจผล `PRAGMA integrity_check` ของ backup ก่อนเก็บระยะยาว ห้ามลบไฟล์ `-wal`/`-shm` เองขณะที่เปิดฐานข้อมูล

## Rollback

หยุด scheduler/dashboard และยืนยันว่าไม่มี worker เขียนอยู่ สำรอง state ปัจจุบันก่อน แล้วคืน source/config ที่ตรงเวอร์ชันพร้อม SQLite backup ก่อน migration ไปยัง **state directory แยก** ทดสอบสถานะก่อนเปลี่ยนกลับ ไม่ทับฐานข้อมูลที่กำลังเปิด และไม่ลบ worktrees/checkpoints ที่มีงาน

การคืน source เดิมจะทำให้ข้อบกพร่อง v1 กลับมาด้วย โดยเฉพาะ credential harvesting, permission bypass และ review/approval ที่ไม่ครบ จึงควรใช้เพื่ออ่านประวัติหรือกู้ patch แบบ offline และไม่เปิด live workers จนแก้ข้อบกพร่องแล้ว ไม่มี rollback/deploy/commit อัตโนมัติ

## Mapping กฎเดิม

| กฎเดิม | การปรับ |
|---|---|
| รวม 3 sessions / ค่ายละ 1 | แทนด้วย configurable global/provider capacity และ cooldown |
| roles ผูกกับค่าย | ใช้ capability/complexity/availability และสลับ implementation/review ได้ |
| worktree = strict security isolation | แยก worktree ownership/scope detection ออกจาก OS/provider enforcement |
| review exit code 0 = ผ่าน | ต้องมี verdict และ base/patch hash ที่ตรง พร้อม provider ต่างจากผู้เขียนทุก attempt |
| noninteractive approve เติมคำตอบเอง | ปฏิเสธ pipe ต้องยืนยันจาก terminal จริง |
| อ่าน tokens เพื่อดู quota | ไม่อ่าน/refresh credential files; ข้อมูลที่ไม่มีหลักฐานเป็น unknown |
| fallback ให้ IDE ทำเอง | ต้องผ่าน Center และบันทึกเหตุผล/authorship |
| SQLite เปลี่ยนเป็น Supabase | ไม่ใช้ Supabase ตามการตัดสินใจของผู้ใช้ |
