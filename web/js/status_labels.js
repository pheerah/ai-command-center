// The one table that turns a task status into Thai text. dashboard.js and the office window both read it, so a new
// status is named in one place. An unknown status is shown as it is, never as "undefined".
(function() {
  'use strict';

  const step = {
    queued: 'รอคิว', retry_wait: 'รอลองใหม่', assigned: 'รับงานแล้ว กำลังเตรียม', running: 'AI กำลังเขียนโค้ด',
    implementation_done: 'เขียนเสร็จ รอรัน gates', gates: 'กำลังรัน gates (ไม่ใช้ AI)', waiting_for_independent_review: 'รอผู้ตรวจจากอีกค่าย',
    review: 'ผู้ตรวจกำลังตรวจ', ready_for_human_approval: 'รอคุณอนุมัติ', approved: 'อนุมัติแล้ว', blocked: 'ติดขัด ต้องดูสาเหตุ',
    failed: 'ล้มเหลว', cancelled: 'ยกเลิกแล้ว', rejected: 'ถูกปฏิเสธ',
  };

  function label(status) {
    return Object.hasOwn(step, status) ? step[status] : String(status);
  }

  window.StatusLabels = { step, label };
})();
