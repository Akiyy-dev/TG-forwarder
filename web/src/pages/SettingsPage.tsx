import {
  Alert,
  Button,
  Group,
  NumberInput,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { getSettings, putSettings } from '../api/settings'
import { useMe } from '../hooks/useAuth'

const SECTIONS: { key: string; title: string; groups: string[] }[] = [
  { key: 'basic', title: '基础', groups: ['basic'] },
  { key: 'listener', title: '监听与队列', groups: ['listener'] },
  { key: 'processors', title: '规则与处理器', groups: ['processors'] },
  { key: 'review', title: '审核', groups: ['review'] },
  { key: 'history', title: '历史', groups: ['history'] },
  { key: 'web', title: 'Web', groups: ['web'] },
]

const LABELS: Record<string, string> = {
  review_auto_publish_seconds: '批准后自动发布倒计时（秒）',
  review_auto_approve_enabled: '超时自动批准并发布',
  review_auto_approve_minutes: '审核超时自动发布（分钟）',
  history_enabled: '启用历史落盘',
  history_max_per_source: '每个来源历史上限',
  history_dir: '历史目录',
  album_wait_seconds: '相册等待秒数',
  temp_file_ttl_minutes: '临时文件 TTL（分钟）',
  message_footer: '页脚文案',
  enable_keyword_filter: '关键词过滤',
  enable_text_replace: '文本替换',
  enable_link_filter: '链接过滤',
  enable_footer: '启用页脚',
  enable_duplicate_filter: '去重过滤',
  web_host: 'Web Host',
  web_port: 'Web Port',
  database_url: '数据库 URL',
  bot_token: 'Bot Token',
  telegram_api_id: 'API ID',
  telegram_api_hash: 'API Hash',
}

export function SettingsPage() {
  const { section = 'basic' } = useParams()
  const { data: user } = useMe()
  const isAdmin = user?.role === 'super_admin'
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [hint, setHint] = useState<string | null>(null)

  const query = useQuery({
    queryKey: ['settings'],
    queryFn: () => getSettings(),
  })

  const sectionMeta = SECTIONS.find((s) => s.key === section) ?? SECTIONS[0]

  const fields = useMemo(() => {
    const groups = query.data?.groups ?? {}
    return sectionMeta.groups.flatMap((g) => groups[g] ?? [])
  }, [query.data, sectionMeta])

  useEffect(() => {
    if (!query.data) return
    const next: Record<string, unknown> = {}
    for (const f of fields) {
      if (!f.readonly) next[f.key] = f.value
    }
    setDraft(next)
    setHint(null)
  }, [query.data, section, fields])

  const saveMut = useMutation({
    mutationFn: () => putSettings(draft),
    onSuccess: async (res) => {
      if (res.apply === 'restart') {
        setHint('已保存。部分项需要重启进程后生效。')
      } else if (res.apply === 'reload_listener') {
        setHint('已保存。建议重载监听订阅（或重启）。')
      } else {
        setHint('已保存，热更新已生效。')
      }
      await qc.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (err) => setHint(err instanceof ApiError ? err.message : '保存失败'),
  })

  if (!SECTIONS.some((s) => s.key === section)) {
    return <Navigate to="/settings/basic" replace />
  }

  return (
    <Stack gap="md" className="page-enter">
      <div>
        <Title order={2}>设置 · {sectionMeta.title}</Title>
        <Text c="dimmed" size="sm">
          手动保存；密钥项只读展示
        </Text>
      </div>
      <Group gap="xs">
        {SECTIONS.map((s) => (
          <Button
            key={s.key}
            component={Link}
            to={`/settings/${s.key}`}
            size="xs"
            variant={s.key === section ? 'filled' : 'light'}
          >
            {s.title}
          </Button>
        ))}
      </Group>
      {hint && <Alert color="teal">{hint}</Alert>}
      <Stack gap="sm" maw={560}>
        {fields.map((f) => {
          const label = LABELS[f.key] || f.key
          const value = draft[f.key] ?? f.value
          if (typeof f.value === 'boolean' || typeof value === 'boolean') {
            return (
              <Switch
                key={f.key}
                label={`${label}（${f.apply}）`}
                checked={Boolean(value)}
                disabled={f.readonly || !isAdmin}
                onChange={(e) => {
                  const checked = e.currentTarget.checked
                  setDraft((d) => ({ ...d, [f.key]: checked }))
                }}
              />
            )
          }
          if (typeof f.value === 'number' || typeof value === 'number') {
            return (
              <NumberInput
                key={f.key}
                label={`${label}（${f.apply}）`}
                value={Number(value ?? 0)}
                disabled={f.readonly || !isAdmin}
                onChange={(v) => setDraft((d) => ({ ...d, [f.key]: Number(v) || 0 }))}
              />
            )
          }
          return (
            <TextInput
              key={f.key}
              label={`${label}（${f.apply}）`}
              value={String(value ?? '')}
              disabled={f.readonly || !isAdmin}
              onChange={(e) => {
                const value = e.currentTarget.value
                setDraft((d) => ({ ...d, [f.key]: value }))
              }}
            />
          )
        })}
        {!fields.length && <Text c="dimmed">该分类暂无配置项</Text>}
      </Stack>
      {isAdmin && (
        <Button w={120} loading={saveMut.isPending} onClick={() => saveMut.mutate()}>
          保存
        </Button>
      )}
    </Stack>
  )
}
