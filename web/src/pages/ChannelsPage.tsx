import {
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  MultiSelect,
  Select,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import {
  addFromAccount,
  checkTargetPermissions,
  createChannel,
  createTarget,
  deleteChannel,
  listAccountChannels,
  listChannels,
  listTargets,
  patchChannel,
  patchTarget,
  refreshChannels,
  sendTargetTestMessage,
  setChannelTargets,
  setTargetSources,
} from '../api/channels'
import { SourceBackendBadge } from '../components/SourceBackendBadge'
import { useMe } from '../hooks/useAuth'
import {
  PUBLISH_MODE_OPTIONS,
  permissionStatusLabel,
  publishModeLabel,
} from '../utils/labels'
import { sourceBackendLabel } from '../utils/sourceBackend'

function accessLabel(status: string) {
  if (status === 'ok') return '可达'
  if (status === 'missing') return '不可达'
  return '未知'
}

export function ChannelsPage() {
  const { data: user } = useMe()
  const isAdmin = user?.role === 'super_admin'
  const qc = useQueryClient()
  const [sourceOpen, setSourceOpen] = useState(false)
  const [targetOpen, setTargetOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [chatId, setChatId] = useState('')
  const [title, setTitle] = useState('')
  const [mode, setMode] = useState('review')
  const [msg, setMsg] = useState<string | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [asSource, setAsSource] = useState(true)
  const [asTarget, setAsTarget] = useState(false)

  const sources = useQuery({
    queryKey: ['channels'],
    queryFn: () => listChannels({ page: 1, page_size: 100 }),
  })
  const targets = useQuery({
    queryKey: ['targets'],
    queryFn: () => listTargets(),
  })
  const account = useQuery({
    queryKey: ['account-channels'],
    queryFn: () => listAccountChannels(),
    enabled: accountOpen,
  })

  const targetOptions = useMemo(
    () =>
      (targets.data?.items ?? []).map((t) => ({
        value: String(t.id),
        label: t.title || t.username || String(t.chat_id),
      })),
    [targets.data],
  )
  const sourceOptions = useMemo(
    () =>
      (sources.data?.items ?? []).map((s) => ({
        value: String(s.id),
        label: `${sourceBackendLabel(s.source_backend)} · ${s.title || s.username || String(s.chat_id)}`,
      })),
    [sources.data],
  )

  const createSourceMut = useMutation({
    mutationFn: () =>
      createChannel({
        chat_id: Number(chatId),
        title: title || undefined,
        publish_mode: mode,
      }),
    onSuccess: async () => {
      setSourceOpen(false)
      setChatId('')
      setTitle('')
      await qc.invalidateQueries({ queryKey: ['channels'] })
    },
    onError: (err) => setMsg(err instanceof ApiError ? err.message : '创建失败'),
  })

  const createTargetMut = useMutation({
    mutationFn: () =>
      createTarget({
        chat_id: Number(chatId),
        title: title || undefined,
      }),
    onSuccess: async () => {
      setTargetOpen(false)
      setChatId('')
      setTitle('')
      await qc.invalidateQueries({ queryKey: ['targets'] })
    },
    onError: (err) => setMsg(err instanceof ApiError ? err.message : '创建失败'),
  })

  const refreshMut = useMutation({
    mutationFn: () => refreshChannels(),
    onSuccess: async (res) => {
      setMsg(`刷新完成：YAML ${String(res.yaml_upserted)}，访问状态更新 ${String(res.access_updated)}`)
      await qc.invalidateQueries({ queryKey: ['channels'] })
      await qc.invalidateQueries({ queryKey: ['targets'] })
    },
    onError: (err) => setMsg(err instanceof ApiError ? err.message : '刷新失败'),
  })

  const addAccountMut = useMutation({
    mutationFn: () =>
      addFromAccount({
        chat_ids: picked.map(Number),
        as_source: asSource,
        as_target: asTarget,
        publish_mode: mode,
      }),
    onSuccess: async (res) => {
      setAccountOpen(false)
      setPicked([])
      setMsg(
        `已添加：来源 ${res.created_sources.length}，目标 ${res.created_targets.length}`,
      )
      await qc.invalidateQueries({ queryKey: ['channels'] })
      await qc.invalidateQueries({ queryKey: ['targets'] })
    },
    onError: (err) => setMsg(err instanceof ApiError ? err.message : '添加失败'),
  })

  return (
    <Stack gap="md" className="page-enter">
      <Group justify="space-between">
        <div>
          <Title order={2}>频道管理</Title>
          <Text c="dimmed" size="sm">
            多对多绑定、账户可达检测与 YAML 刷新
          </Text>
        </div>
        {isAdmin && (
          <Group>
            <Button variant="light" loading={refreshMut.isPending} onClick={() => refreshMut.mutate()}>
              刷新
            </Button>
            <Button variant="default" onClick={() => setAccountOpen(true)}>
              从账户添加
            </Button>
          </Group>
        )}
      </Group>
      {msg && (
        <Text c="dimmed" size="sm">
          {msg}
        </Text>
      )}

      <Tabs defaultValue="sources">
        <Tabs.List>
          <Tabs.Tab value="sources">来源频道</Tabs.Tab>
          <Tabs.Tab value="targets">目标频道</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="sources" pt="md">
          <Stack>
            {isAdmin && (
              <Button w={160} onClick={() => setSourceOpen(true)}>
                添加来源
              </Button>
            )}
            <Table striped withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>标题</Table.Th>
                  <Table.Th>平台</Table.Th>
                  <Table.Th>聊天 ID</Table.Th>
                  <Table.Th>可达</Table.Th>
                  <Table.Th>发布模式</Table.Th>
                  <Table.Th>目标</Table.Th>
                  <Table.Th>启用</Table.Th>
                  {isAdmin && <Table.Th>操作</Table.Th>}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(sources.data?.items ?? []).map((ch) => (
                  <Table.Tr key={ch.id}>
                    <Table.Td>{ch.title || ch.username || '-'}</Table.Td>
                    <Table.Td>
                      <SourceBackendBadge backend={ch.source_backend} />
                    </Table.Td>
                    <Table.Td>{ch.chat_id}</Table.Td>
                    <Table.Td>
                      {ch.source_backend === 'safew' ? (
                        <Badge color="gray" variant="light">
                          不适用
                        </Badge>
                      ) : (
                        <Badge
                          color={ch.access_status === 'ok' ? 'teal' : 'orange'}
                          variant="light"
                        >
                          {accessLabel(ch.access_status)}
                        </Badge>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {isAdmin ? (
                        <Select
                          data={PUBLISH_MODE_OPTIONS}
                          value={ch.publish_mode}
                          w={160}
                          onChange={(v) => {
                            if (!v) return
                            void patchChannel(ch.id, { publish_mode: v }).then(() =>
                              qc.invalidateQueries({ queryKey: ['channels'] }),
                            )
                          }}
                        />
                      ) : (
                        <Badge variant="light">{publishModeLabel(ch.publish_mode)}</Badge>
                      )}
                    </Table.Td>
                    <Table.Td style={{ minWidth: 220 }}>
                      {isAdmin ? (
                        <MultiSelect
                          data={targetOptions}
                          value={(ch.target_ids ?? []).map(String)}
                          placeholder="绑定目标"
                          searchable
                          onChange={(vals) => {
                            void setChannelTargets(
                              ch.id,
                              vals.map(Number),
                            )
                              .then(() => {
                                void qc.invalidateQueries({ queryKey: ['channels'] })
                                void qc.invalidateQueries({ queryKey: ['targets'] })
                              })
                              .catch((err: unknown) =>
                                setMsg(err instanceof ApiError ? err.message : '绑定失败'),
                              )
                          }}
                        />
                      ) : (
                        <Text size="sm">{(ch.target_ids ?? []).join(', ') || '-'}</Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {isAdmin ? (
                        <Tooltip
                          label={
                            ch.source_backend === 'telegram' && ch.access_status === 'missing'
                              ? 'Telegram 已确认不可达，无法启用'
                              : '切换启用'
                          }
                        >
                          <Switch
                            checked={ch.enabled}
                            disabled={
                              ch.source_backend === 'telegram' &&
                              ch.access_status === 'missing' &&
                              !ch.enabled
                            }
                            onChange={(e) =>
                              void patchChannel(ch.id, {
                                enabled: e.currentTarget.checked,
                              })
                                .then(() => qc.invalidateQueries({ queryKey: ['channels'] }))
                                .catch((err: unknown) =>
                                  setMsg(err instanceof ApiError ? err.message : '更新失败'),
                                )
                            }
                          />
                        </Tooltip>
                      ) : (
                        <Badge color={ch.enabled ? 'teal' : 'gray'}>
                          {ch.enabled ? '启用' : '停用'}
                        </Badge>
                      )}
                    </Table.Td>
                    {isAdmin && (
                      <Table.Td>
                        <Button
                          size="xs"
                          color="red"
                          variant="subtle"
                          onClick={() => {
                            if (window.confirm('删除该来源频道？')) {
                              void deleteChannel(ch.id).then(() =>
                                qc.invalidateQueries({ queryKey: ['channels'] }),
                              )
                            }
                          }}
                        >
                          删除
                        </Button>
                      </Table.Td>
                    )}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="targets" pt="md">
          <Stack>
            {isAdmin && (
              <Button w={160} onClick={() => setTargetOpen(true)}>
                添加目标
              </Button>
            )}
            <Table striped withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>标题</Table.Th>
                  <Table.Th>聊天 ID</Table.Th>
                  <Table.Th>可达</Table.Th>
                  <Table.Th>来源绑定</Table.Th>
                  <Table.Th>权限</Table.Th>
                  <Table.Th>启用</Table.Th>
                  {isAdmin && <Table.Th>操作</Table.Th>}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(targets.data?.items ?? []).map((t) => (
                  <Table.Tr key={t.id}>
                    <Table.Td>{t.title || t.username || '-'}</Table.Td>
                    <Table.Td>{t.chat_id}</Table.Td>
                    <Table.Td>
                      <Badge color={t.access_status === 'ok' ? 'teal' : 'orange'} variant="light">
                        {accessLabel(t.access_status)}
                      </Badge>
                    </Table.Td>
                    <Table.Td style={{ minWidth: 220 }}>
                      {isAdmin ? (
                        <MultiSelect
                          data={sourceOptions}
                          value={(t.source_ids ?? []).map(String)}
                          placeholder="绑定来源"
                          searchable
                          onChange={(vals) => {
                            void setTargetSources(t.id, vals.map(Number))
                              .then(() => {
                                void qc.invalidateQueries({ queryKey: ['channels'] })
                                void qc.invalidateQueries({ queryKey: ['targets'] })
                              })
                              .catch((err: unknown) =>
                                setMsg(err instanceof ApiError ? err.message : '绑定失败'),
                              )
                          }}
                        />
                      ) : (
                        <Text size="sm">{(t.source_ids ?? []).join(', ') || '-'}</Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Badge
                        color={
                          t.permission_status === 'ok'
                            ? 'teal'
                            : t.permission_status === 'unknown'
                              ? 'gray'
                              : 'red'
                        }
                      >
                        {permissionStatusLabel(t.permission_status)}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      {isAdmin ? (
                        <Switch
                          checked={t.enabled}
                          disabled={t.access_status === 'missing' && !t.enabled}
                          onChange={(e) =>
                            void patchTarget(t.id, { enabled: e.currentTarget.checked })
                              .then(() => qc.invalidateQueries({ queryKey: ['targets'] }))
                              .catch((err: unknown) =>
                                setMsg(err instanceof ApiError ? err.message : '更新失败'),
                              )
                          }
                        />
                      ) : (
                        t.enabled ? '是' : '否'
                      )}
                    </Table.Td>
                    {isAdmin && (
                      <Table.Td>
                        <Group gap={6}>
                          <Button
                            size="xs"
                            variant="light"
                            onClick={() =>
                              void checkTargetPermissions(t.id)
                                .then(() => qc.invalidateQueries({ queryKey: ['targets'] }))
                                .catch((err: unknown) =>
                                  setMsg(err instanceof ApiError ? err.message : '检测失败'),
                                )
                            }
                          >
                            检测权限
                          </Button>
                          <Button
                            size="xs"
                            variant="default"
                            onClick={() =>
                              void sendTargetTestMessage(t.id, 'TG-forwarder 测试消息')
                                .then((res) => setMsg(`测试消息已发送：${JSON.stringify(res)}`))
                                .catch((err: unknown) =>
                                  setMsg(err instanceof ApiError ? err.message : '发送失败'),
                                )
                            }
                          >
                            测试消息
                          </Button>
                        </Group>
                      </Table.Td>
                    )}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Stack>
        </Tabs.Panel>
      </Tabs>

      <Modal opened={sourceOpen} onClose={() => setSourceOpen(false)} title="添加来源频道">
        <Stack>
          <TextInput
            label="聊天 ID"
            value={chatId}
            onChange={(e) => setChatId(e.currentTarget.value)}
          />
          <TextInput label="标题" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
          <Select
            label="发布模式"
            data={PUBLISH_MODE_OPTIONS}
            value={mode}
            onChange={(v) => setMode(v ?? 'review')}
          />
          <Button loading={createSourceMut.isPending} onClick={() => createSourceMut.mutate()}>
            创建
          </Button>
        </Stack>
      </Modal>

      <Modal opened={targetOpen} onClose={() => setTargetOpen(false)} title="添加目标频道">
        <Stack>
          <TextInput
            label="聊天 ID"
            value={chatId}
            onChange={(e) => setChatId(e.currentTarget.value)}
          />
          <TextInput label="标题" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
          <Button loading={createTargetMut.isPending} onClick={() => createTargetMut.mutate()}>
            创建
          </Button>
        </Stack>
      </Modal>

      <Modal
        opened={accountOpen}
        onClose={() => setAccountOpen(false)}
        title="从账户添加频道"
        size="lg"
      >
        <Stack>
          <Group>
            <Checkbox
              label="添加为来源"
              checked={asSource}
              onChange={(e) => setAsSource(e.currentTarget.checked)}
            />
            <Checkbox
              label="添加为目标"
              checked={asTarget}
              onChange={(e) => setAsTarget(e.currentTarget.checked)}
            />
            <Select
              label="发布模式"
              data={PUBLISH_MODE_OPTIONS}
              value={mode}
              w={160}
              onChange={(v) => setMode(v ?? 'review')}
            />
          </Group>
          <MultiSelect
            label="账户频道"
            data={(account.data?.items ?? []).map((c) => ({
              value: String(c.chat_id),
              label: `${c.title || c.username || c.chat_id}${c.accessible ? '' : ' (不可读)'}`,
            }))}
            value={picked}
            onChange={setPicked}
            searchable
            nothingFoundMessage={account.isLoading ? '加载中…' : '无可用频道'}
          />
          <Button
            disabled={!picked.length || (!asSource && !asTarget)}
            loading={addAccountMut.isPending}
            onClick={() => addAccountMut.mutate()}
          >
            一键添加
          </Button>
        </Stack>
      </Modal>
    </Stack>
  )
}
