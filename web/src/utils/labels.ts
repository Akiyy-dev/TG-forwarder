/** User-visible Chinese labels for API enums and field keys. */

export function roleLabel(role: string | undefined | null): string {
  const map: Record<string, string> = {
    viewer: '只读',
    reviewer: '审核员',
    super_admin: '超级管理员',
  }
  return (role && map[role]) || role || '-'
}

export function ruleActionLabel(action: string): string {
  const map: Record<string, string> = {
    flag: '标记',
    reject: '拒绝',
    require_review: '要求审核',
    replace: '替换',
    remove: '移除',
    add_tag: '加标签',
  }
  return map[action] ?? action
}

export function ruleTypeLabel(ruleType: string): string {
  const map: Record<string, string> = {
    keyword: '关键词',
    phrase: '短语',
    username: '用户名',
    link: '链接',
    domain: '域名',
    regex: '正则',
    has_media: '媒体判断',
  }
  return map[ruleType] ?? ruleType
}

export function publishModeLabel(mode: string): string {
  const map: Record<string, string> = {
    review: '全部审核',
    auto: '自动发布',
    rule_based: '规则决定',
    paused: '暂停发布',
  }
  return map[mode] ?? mode
}

export function permissionStatusLabel(status: string): string {
  const map: Record<string, string> = {
    ok: '正常',
    unknown: '未知',
    missing: '缺失',
    forbidden: '无权限',
    error: '错误',
  }
  return map[status] ?? status
}

export function mediaTypeLabel(mediaType: string): string {
  const map: Record<string, string> = {
    text: '文本',
    photo: '图片',
    video: '视频',
    document: '文档',
    animation: '动图',
    audio: '音频',
    voice: '语音',
    sticker: '贴纸',
    album: '相册',
    unsupported: '不支持',
  }
  return map[mediaType] ?? mediaType
}

export function reviewActionLabel(action: string): string {
  const map: Record<string, string> = {
    created: '创建',
    opened: '打开',
    edited: '编辑',
    approved: '批准',
    rejected: '拒绝',
    publish_started: '开始发布',
    published: '已发布',
    publish_failed: '发布失败',
    retried: '重试',
    rules_reapplied: '重跑规则',
    restored_original: '恢复原文',
    assigned: '指派',
    unassigned: '取消指派',
  }
  return map[action] ?? action
}

export function revisionSourceLabel(source: string): string {
  const map: Record<string, string> = {
    original: '原文',
    rules: '规则',
    reviewer: '审核员',
    system: '系统',
  }
  return map[source] ?? source
}

export function messageStatusLabel(status: string): string {
  const map: Record<string, string> = {
    received: '已接收',
    collecting_album: '收集相册',
    processing: '处理中',
    pending_publish: '待发布',
    pending_review: '待审核',
    publishing: '发布中',
    published: '已发布',
    rejected: '已拒绝',
    failed: '失败',
    retrying: '重试中',
    skipped: '已跳过',
    duplicate: '重复',
  }
  return map[status] ?? status
}

export function logColumnLabel(column: string): string {
  const map: Record<string, string> = {
    id: 'ID',
    review_task_id: '审核任务',
    action: '动作',
    old_status: '原状态',
    new_status: '新状态',
    created_at: '时间',
    message_record_id: '消息记录',
    processor_name: '处理器',
    status: '状态',
    duration_ms: '耗时(ms)',
    rule_name: '规则名',
    matched_text: '命中文本',
  }
  return map[column] ?? column
}

export const RULE_ACTION_OPTIONS = [
  { value: 'flag', label: '标记' },
  { value: 'reject', label: '拒绝' },
  { value: 'require_review', label: '要求审核' },
  { value: 'replace', label: '替换' },
  { value: 'remove', label: '移除' },
  { value: 'add_tag', label: '加标签' },
]

export const RULE_TYPE_OPTIONS = [
  { value: 'keyword', label: '关键词' },
  { value: 'phrase', label: '短语' },
  { value: 'regex', label: '正则' },
  { value: 'has_media', label: '媒体判断' },
]

export const HAS_MEDIA_PATTERN_OPTIONS = [
  { value: 'has', label: '有媒体' },
  { value: 'none', label: '无媒体（纯文本）' },
]

export const PUBLISH_MODE_OPTIONS = [
  { value: 'review', label: '全部审核' },
  { value: 'auto', label: '自动发布' },
  { value: 'rule_based', label: '规则决定' },
  { value: 'paused', label: '暂停发布' },
]
