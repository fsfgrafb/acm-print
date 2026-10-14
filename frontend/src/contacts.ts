const emailPattern = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/

export function adminContactText(contact?: { email: string; phone: string } | null) {
  const details = [contact?.email ? `邮箱：${contact.email}` : '', contact?.phone ? `手机号：${contact.phone}` : ''].filter(Boolean).join('，')
  return '请联系管理员。' + (details ? details + '。' : '')
}

export function validateContacts(emailValue: string, phoneValue: string) {
  const email = emailValue.trim(), phone = phoneValue.trim()
  const local = email.split('@')[0]
  if (email && (email.length > 254 || !emailPattern.test(email) || local.startsWith('.') || local.endsWith('.') || email.includes('..'))) {
    throw new Error('邮箱格式不正确')
  }
  if (phone && !/^(?:\+?86)?1[3-9][0-9]{9}$/.test(phone)) {
    throw new Error('手机号需为 11 位中国大陆手机号，可带 +86 前缀')
  }
  return { email, phone }
}
