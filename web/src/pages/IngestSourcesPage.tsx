import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import {
  type IngestSource,
  createIngestSource,
  listIngestSources,
  patchIngestSource,
  revokeIngestSource,
  rotateIngestSourceToken,
} from '../api/ingest'
import { useMe } from '../hooks/useAuth'

const exampleJson = JSON.stringify({
  message_id: 'capture-000001',
  conversation_id: 'group-001',
  conversation_name: '项目讨论群',
  sender: 'Alice',
  text: '采集到的消息内容',
  timestamp: '2026-10-21T01:30:00+08:00',
}, null, 2)

function toInputDate(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

export function IngestSourcesPage() {
  const { data: user } = useMe()
  const isAdmin = user?.role === 'super_admin'
  const qc = useQueryClient()
  const sources = useQuery({ queryKey: ['ingest-sources'], queryFn: listIngestSources })
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<IngestSource | null>(null)
  const [name, setName] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [secret, setSecret] = useState<{ token: string; sourceId: number } | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [copyMessage, setCopyMessage] = useState<string | null>(null)
  const endpointUrl = `${window.location.origin}/api/ingest/v1/messages`
  const validDate = !expiresAt || !Number.isNaN(new Date(expiresAt).getTime())

  const invalidateSources = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['ingest-sources'] }),
      qc.invalidateQueries({ queryKey: ['channels'] }),
    ])
  }

  const saveMut = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(),
        enabled,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      }
      return editing ? patchIngestSource(editing.id, body) : createIngestSource(body)
    },
    onSuccess: async (result) => {
      setFormOpen(false)
      setMessage(null)
      if ('token' in result && typeof result.token === 'string') {
        setSecret({ token: result.token, sourceId: result.source_id })
        setCopyMessage(null)
      }
      await invalidateSources()
    },
    onError: (error) => setMessage(errorMessage(error, '保存接入来源失败')),
  })

  const toggleMut = useMutation({
    mutationFn: ({ id, value }: { id: number; value: boolean }) =>
      patchIngestSource(id, { enabled: value }),
    onSuccess: invalidateSources,
    onError: (error) => setMessage(errorMessage(error, '更新接入状态失败')),
  })

  const rotateMut = useMutation({
    mutationFn: rotateIngestSourceToken,
    onSuccess: async (result) => {
      setSecret({ token: result.token, sourceId: result.source_id })
      setCopyMessage(null)
      setMessage(null)
      await invalidateSources()
    },
    onError: (error) => setMessage(errorMessage(error, '重新生成 Token 失败')),
  })

  const revokeMut = useMutation({
    mutationFn: revokeIngestSource,
    onSuccess: async () => {
      setMessage(null)
      await invalidateSources()
    },
    onError: (error) => setMessage(errorMessage(error, '撤销接入失败')),
  })

  const busy = saveMut.isPending || toggleMut.isPending || rotateMut.isPending || revokeMut.isPending

  const openForm = (source: IngestSource | null) => {
    setEditing(source)
    setName(source?.name ?? '')
    setExpiresAt(toInputDate(source?.expires_at ?? null))
    setEnabled(source?.enabled ?? true)
    setMessage(null)
    setFormOpen(true)
  }

  const copyText = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopyMessage('已复制')
    } catch {
      setCopyMessage('复制失败，请手动选择并复制内容')
    }
  }

  return (
    <Stack gap="md" className="page-enter">
      <Group justify="space-between">
        <div>
          <Title order={2}>消息接入</Title>
          <Text c="dimmed" size="sm">为采集软件创建独立的接入凭据，提交的文字将进入规则、审核和发布流程</Text>
        </div>
        {isAdmin && <Button onClick={() => openForm(null)}>创建接入来源</Button>}
      </Group>

      <Alert color="blue" title="接入前先配置发送目标">
        新来源默认使用审核模式。请在频道管理中配置发布模式与发送目标，再开始提交消息。
        接入来源由 Token 决定，请勿在消息 JSON 中添加内部来源或路由字段。
      </Alert>
      {message && !formOpen && <Alert color="red" role="alert">{message}</Alert>}

      {sources.isPending ? (
        <Group><Loader size="sm" /><Text size="sm">正在加载接入来源…</Text></Group>
      ) : sources.isError ? (
        <Alert color="red" title="加载失败" role="alert">
          <Stack gap="xs">
            <Text size="sm">{errorMessage(sources.error, '无法加载接入来源')}</Text>
            <Button variant="light" size="xs" w="fit-content" onClick={() => void sources.refetch()}>重试</Button>
          </Stack>
        </Alert>
      ) : !sources.data.items.length ? (
        <Alert color="gray">暂无接入来源。{isAdmin ? '创建来源后即可获取接入 Token。' : '请联系管理员创建接入来源。'}</Alert>
      ) : (
        <Table.ScrollContainer minWidth={900}>
          <Table striped withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>名称 / 路由</Table.Th>
                <Table.Th>Token 标识</Table.Th>
                <Table.Th>过期时间</Table.Th>
                <Table.Th>最后访问</Table.Th>
                <Table.Th>启用</Table.Th>
                {isAdmin && <Table.Th>操作</Table.Th>}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {sources.data.items.map((source) => {
                const expired = source.expires_at !== null && new Date(source.expires_at).getTime() <= Date.now()
                return (
                  <Table.Tr key={source.id}>
                    <Table.Td>
                      <Text size="sm" fw={500}>{source.name}</Text>
                      <Button component={Link} to={`/channels?source_id=${source.source_id}`} variant="subtle" size="compact-xs">
                        {isAdmin ? '配置来源路由' : '查看来源路由'} #{source.source_id}
                      </Button>
                    </Table.Td>
                    <Table.Td><Code>{source.token_prefix}…</Code></Table.Td>
                    <Table.Td>
                      <Text size="sm">{source.expires_at ? new Date(source.expires_at).toLocaleString() : '永不过期'}</Text>
                      {expired && <Badge color="orange" size="xs">已过期</Badge>}
                    </Table.Td>
                    <Table.Td>{source.last_access_at ? new Date(source.last_access_at).toLocaleString() : '尚未访问'}</Table.Td>
                    <Table.Td>
                      {isAdmin ? (
                        <Switch
                          aria-label={`启用 ${source.name}`}
                          checked={source.enabled}
                          disabled={busy}
                          onChange={(event) => toggleMut.mutate({ id: source.id, value: event.currentTarget.checked })}
                        />
                      ) : (
                        <Badge color={source.enabled ? 'teal' : 'gray'}>{source.enabled ? '启用' : '停用'}</Badge>
                      )}
                    </Table.Td>
                    {isAdmin && (
                      <Table.Td>
                        <Group gap={4}>
                          <Button size="xs" variant="subtle" disabled={busy} onClick={() => openForm(source)}>编辑</Button>
                          <Button
                            size="xs"
                            variant="subtle"
                            disabled={busy}
                            loading={rotateMut.isPending && rotateMut.variables === source.id}
                            onClick={() => {
                              if (window.confirm('重新生成后旧 Token 会立即失效，继续？')) rotateMut.mutate(source.id)
                            }}
                          >重新生成 Token</Button>
                          <Button
                            size="xs"
                            variant="subtle"
                            color="red"
                            disabled={busy}
                            loading={revokeMut.isPending && revokeMut.variables === source.id}
                            onClick={() => {
                              if (window.confirm('撤销该接入凭据？旧 Token 将失效，来源配置和消息历史会保留。')) revokeMut.mutate(source.id)
                            }}
                          >撤销接入</Button>
                        </Group>
                      </Table.Td>
                    )}
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <Stack gap="xs">
        <Title order={4}>提交文字消息</Title>
        <Code block>POST {endpointUrl}{'\n'}Authorization: Bearer YOUR_INGEST_TOKEN{'\n'}Content-Type: application/json</Code>
        <Group gap="xs">
          <Button size="xs" variant="light" onClick={() => void copyText(endpointUrl)}>复制接入地址</Button>
          <Button size="xs" variant="light" onClick={() => void copyText(exampleJson)}>复制 JSON 示例</Button>
          {copyMessage && !secret && <Text size="sm" c="dimmed" role="status">{copyMessage}</Text>}
        </Group>
        <Code block>{exampleJson}</Code>
        <Text c="dimmed" size="sm">
          多个会话请使用不同且稳定的 conversation_id；重试时保持 message_id 和消息内容不变。
          timestamp 可省略，提供时须包含时区。接口只接收文字。收到 503 可使用同一消息重试。
        </Text>
      </Stack>

      <Modal opened={formOpen && isAdmin} onClose={() => !saveMut.isPending && setFormOpen(false)} title={editing ? '编辑接入来源' : '创建接入来源'}>
        <Stack>
          {message && <Alert color="red" role="alert">{message}</Alert>}
          <TextInput label="名称" required maxLength={128} value={name} onChange={(event) => setName(event.currentTarget.value)} />
          <TextInput
            type="datetime-local"
            label="过期时间"
            description="使用本地时区，留空为永不过期"
            value={expiresAt}
            error={!validDate ? '请输入有效时间' : undefined}
            onChange={(event) => setExpiresAt(event.currentTarget.value)}
          />
          <Switch label="启用接入" checked={enabled} onChange={(event) => setEnabled(event.currentTarget.checked)} />
          <Button disabled={!name.trim() || !validDate} loading={saveMut.isPending} onClick={() => saveMut.mutate()}>
            {editing ? '保存' : '创建并生成 Token'}
          </Button>
        </Stack>
      </Modal>

      <Modal opened={secret !== null} onClose={() => { setSecret(null); setCopyMessage(null) }} title="请立即保存接入 Token" closeOnClickOutside={false}>
        <Stack>
          <Alert color="yellow">该 Token 只显示这一次，关闭后无法再次查看；遗失后请重新生成。</Alert>
          <Code block style={{ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{secret?.token}</Code>
          <Button onClick={() => secret && void copyText(secret.token)}>复制 Token</Button>
          {copyMessage && <Text size="sm" role="status">{copyMessage}</Text>}
          <Button component={Link} to={`/channels?source_id=${secret?.sourceId}`} variant="light" onClick={() => setSecret(null)}>配置来源路由</Button>
        </Stack>
      </Modal>
    </Stack>
  )
}
