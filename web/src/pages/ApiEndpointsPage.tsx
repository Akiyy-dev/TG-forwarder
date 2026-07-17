import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Modal,
  MultiSelect,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import {
  type ApiEndpoint,
  createApiEndpoint,
  deleteApiEndpoint,
  listApiEndpoints,
  patchApiEndpoint,
  rotateApiEndpointToken,
  setApiEndpointSources,
} from '../api/apiEndpoints'
import { listChannels } from '../api/channels'
import { ApiError } from '../api/client'
import { useMe } from '../hooks/useAuth'
import { sourceBackendLabel } from '../utils/sourceBackend'

function toInputDate(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function toIsoDate(value: string) {
  return value ? new Date(value).toISOString() : null
}

export function ApiEndpointsPage() {
  const { data: user } = useMe()
  const isAdmin = user?.role === 'super_admin'
  const qc = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [edit, setEdit] = useState<ApiEndpoint | null>(null)
  const [name, setName] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [pickedSources, setPickedSources] = useState<string[]>([])
  const [secret, setSecret] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const endpoints = useQuery({ queryKey: ['api-endpoints'], queryFn: listApiEndpoints })
  const sources = useQuery({
    queryKey: ['channels', 'api-options'],
    queryFn: () => listChannels({ page: 1, page_size: 100 }),
  })
  const sourceOptions = useMemo(
    () =>
      (sources.data?.items ?? []).map((source) => ({
        value: String(source.id),
        label: `${sourceBackendLabel(source.source_backend)} · ${source.title || source.username || source.chat_id}`,
      })),
    [sources.data],
  )

  const createMut = useMutation({
    mutationFn: () =>
      createApiEndpoint({
        name,
        expires_at: toIsoDate(expiresAt),
        source_ids: pickedSources.map(Number),
      }),
    onSuccess: async (result) => {
      setCreateOpen(false)
      setSecret(result.token)
      setName('')
      setExpiresAt('')
      setPickedSources([])
      await qc.invalidateQueries({ queryKey: ['api-endpoints'] })
    },
    onError: (error) => setMessage(error instanceof ApiError ? error.message : '创建失败'),
  })

  const saveMut = useMutation({
    mutationFn: () =>
      patchApiEndpoint(edit!.id, { name, expires_at: toIsoDate(expiresAt) }),
    onSuccess: async () => {
      setEdit(null)
      await qc.invalidateQueries({ queryKey: ['api-endpoints'] })
    },
    onError: (error) => setMessage(error instanceof ApiError ? error.message : '保存失败'),
  })

  const beginEdit = (endpoint: ApiEndpoint) => {
    setEdit(endpoint)
    setName(endpoint.name)
    setExpiresAt(toInputDate(endpoint.expires_at))
  }

  const openCreate = () => {
    setName('')
    setExpiresAt('')
    setPickedSources([])
    setCreateOpen(true)
  }

  return (
    <Stack gap="md" className="page-enter">
      <Group justify="space-between">
        <div>
          <Title order={2}>对外 API</Title>
          <Text c="dimmed" size="sm">
            管理带 Token 的消息拉取目标；接口只返回已经完成规则与审核流程的内容
          </Text>
        </div>
        {isAdmin && <Button onClick={openCreate}>创建 API</Button>}
      </Group>
      <Alert color="blue">
        客户端请求 <Code>GET /api/public/v1/messages?cursor=0&amp;limit=50</Code>，并发送
        <Code ml={6}>Authorization: Bearer TOKEN</Code>。保存响应中的 next_cursor 用于下次增量拉取。
      </Alert>
      {message && <Text c="dimmed" size="sm">{message}</Text>}
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>名称</Table.Th>
            <Table.Th>Token 标识</Table.Th>
            <Table.Th>来源频道</Table.Th>
            <Table.Th>过期时间</Table.Th>
            <Table.Th>最后访问</Table.Th>
            <Table.Th>启用</Table.Th>
            {isAdmin && <Table.Th>操作</Table.Th>}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(endpoints.data?.items ?? []).map((endpoint) => (
            <Table.Tr key={endpoint.id}>
              <Table.Td>{endpoint.name}</Table.Td>
              <Table.Td><Code>{endpoint.token_prefix}…</Code></Table.Td>
              <Table.Td style={{ minWidth: 280 }}>
                {isAdmin ? (
                  <MultiSelect
                    data={sourceOptions}
                    value={endpoint.source_ids.map(String)}
                    placeholder="绑定来源"
                    searchable
                    onChange={(values) => {
                      void setApiEndpointSources(endpoint.id, values.map(Number))
                        .then(() => qc.invalidateQueries({ queryKey: ['api-endpoints'] }))
                        .then(() => qc.invalidateQueries({ queryKey: ['channels'] }))
                        .catch((error: unknown) =>
                          setMessage(error instanceof ApiError ? error.message : '绑定失败'),
                        )
                    }}
                  />
                ) : (
                  endpoint.source_ids.join(', ') || '-'
                )}
              </Table.Td>
              <Table.Td>
                {endpoint.expires_at ? new Date(endpoint.expires_at).toLocaleString() : '永不过期'}
              </Table.Td>
              <Table.Td>
                {endpoint.last_access_at ? new Date(endpoint.last_access_at).toLocaleString() : '-'}
              </Table.Td>
              <Table.Td>
                {isAdmin ? (
                  <Switch
                    checked={endpoint.enabled}
                    onChange={(event) => {
                      const enabled = event.currentTarget.checked
                      void patchApiEndpoint(endpoint.id, { enabled }).then(() =>
                        qc.invalidateQueries({ queryKey: ['api-endpoints'] }),
                      ).catch((error: unknown) =>
                        setMessage(error instanceof ApiError ? error.message : '更新失败'),
                      )
                    }}
                  />
                ) : (
                  <Badge color={endpoint.enabled ? 'teal' : 'gray'}>
                    {endpoint.enabled ? '启用' : '停用'}
                  </Badge>
                )}
              </Table.Td>
              {isAdmin && (
                <Table.Td>
                  <Group gap={4}>
                    <Button size="xs" variant="subtle" onClick={() => beginEdit(endpoint)}>编辑</Button>
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={() => {
                        if (!window.confirm('重新生成后旧 Token 会立即失效，继续？')) return
                        void rotateApiEndpointToken(endpoint.id)
                          .then((result) => setSecret(result.token))
                          .then(() => qc.invalidateQueries({ queryKey: ['api-endpoints'] }))
                          .catch((error: unknown) =>
                            setMessage(error instanceof ApiError ? error.message : '重置失败'),
                          )
                      }}
                    >
                      重置 Token
                    </Button>
                    <Button
                      size="xs"
                      color="red"
                      variant="subtle"
                      onClick={() => {
                        if (!window.confirm('删除该 API 及其待拉取记录？')) return
                        void deleteApiEndpoint(endpoint.id)
                          .then(() => qc.invalidateQueries({ queryKey: ['api-endpoints'] }))
                          .then(() => qc.invalidateQueries({ queryKey: ['channels'] }))
                          .catch((error: unknown) =>
                            setMessage(error instanceof ApiError ? error.message : '删除失败'),
                          )
                      }}
                    >
                      删除
                    </Button>
                  </Group>
                </Table.Td>
              )}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      <Modal opened={createOpen} onClose={() => setCreateOpen(false)} title="创建 API 目标">
        <Stack>
          <TextInput label="名称" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <TextInput
            type="datetime-local"
            label="过期时间（留空为永不过期）"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.currentTarget.value)}
          />
          <MultiSelect
            label="可接收的来源频道"
            data={sourceOptions}
            value={pickedSources}
            onChange={setPickedSources}
            searchable
          />
          <Button disabled={!name.trim()} loading={createMut.isPending} onClick={() => createMut.mutate()}>
            创建并生成 Token
          </Button>
        </Stack>
      </Modal>

      <Modal opened={edit !== null} onClose={() => setEdit(null)} title="编辑 API 目标">
        <Stack>
          <TextInput label="名称" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <TextInput
            type="datetime-local"
            label="过期时间（留空为永不过期）"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.currentTarget.value)}
          />
          <Button disabled={!name.trim()} loading={saveMut.isPending} onClick={() => saveMut.mutate()}>
            保存
          </Button>
        </Stack>
      </Modal>

      <Modal opened={secret !== null} onClose={() => setSecret(null)} title="请立即保存 Token">
        <Stack>
          <Alert color="yellow">该 Token 只显示这一次，服务器仅保存哈希值。</Alert>
          <Code block>{secret}</Code>
          <Button onClick={() => secret && navigator.clipboard.writeText(secret)}>复制 Token</Button>
        </Stack>
      </Modal>
    </Stack>
  )
}
