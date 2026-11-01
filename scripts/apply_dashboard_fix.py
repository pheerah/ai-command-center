with open('dashboard.js', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """  const reason = task.error || events.filter(e => e.event === 'blocked').map(e => e.info.reason).pop();
  if (reason) view.append(node('p', 'view-alert', `สาเหตุที่ติดขัด/ล้มเหลว: ${waitingLabels[reason] || reason}`));"""

new_block = """  const isStuck = task.status === 'blocked' || task.status === 'failed';
  const reason = isStuck ? (task.error || events.filter(e => e.event === 'blocked').map(e => e.info.reason).pop()) : null;
  if (reason) view.append(node('p', 'view-alert', `สาเหตุที่ติดขัด/ล้มเหลว: ${waitingLabels[reason] || reason}`));
  else if (task.status === 'running' && events.some(e => (e.info && e.info.reason && e.info.reason.includes('auto_failover')))) {
    view.append(node('p', 'view-alert', '🔄 ระบบสลับค่าย AI อัตโนมัติ: AI ตัวก่อนหน้าติดขัด กำลังให้ AI ตัวนี้ทำงานต่อ'));
  }"""

content_norm = content.replace('\r\n', '\n')
if old_block in content_norm:
    content_norm = content_norm.replace(old_block, new_block)
    with open('dashboard.js', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: dashboard.js banner logic updated")
else:
    print("ERROR: old_block not found in dashboard.js")
