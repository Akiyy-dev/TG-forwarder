import {
  Badge,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError } from '../api/client'
import {
  checkTargetPermissions,
  createChannel,
  createTarget,
  deleteChannel,
  listChannels,
  listTargets,
  patchChannel,
  sendTargetTestMessage,
} from '../api/channels'
import { useMe } from '../hooks/useAuth'

const MODES = [
  { value: 'review', label: '全部审核' },
  { value: 'auto', label: '自动发布' },
  { value: 'rule_based', label: '规则决定' },
  { value: 'paused', label: '暂停发布' },
]

export function ChannelsPage() {
  const { data: user } = useMe()
  const isAdmin = user?.role === 'super_admin'
  const qc = useQueryClient()
  const [sourceOpen, setSourceOpen] = useState(false)
  const [targetOpen, setTargetOpen] = useState(false)
  const [chatId, setChatId] = useState('')
  const [title, setTitle] = useState('')
  const [mode, setMode] = useState('review')
  const [msg, setMsg] = useState<string | null>(null)

  const sources = useQuery({
    queryKey: ['channels'],
    queryFn: () => listChannels({ page: 1, page_size: 100 }),
  })
  const targets = useQuery({
    queryKey: ['targets'],
    queryFn: () => listTargets(),
  })

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

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Title order={2}>频道管理</Title>
          <Text c="dimmed" size="sm">
            来源发布模式与目标频道权限
          </Text>
        </div>
      </Group>
      {msg && (
        <Text c="red" size="sm">
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
                  <Table.Th>Chat ID</Table.Th>
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
                    <Table.Td>{ch.chat_id}</Table.Td>
                    <Table.Td>
                      {isAdmin ? (
                        <Select
                          data={MODES}
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
                        <Badge variant="light">{ch.publish_mode}</Badge>
                      )}
                    </Table.Td>
                    <Table.Td>{ch.target_channel_id ?? '-'}</Table.Td>
                    <Table.Td>
                      {isAdmin ? (
                        <Switch
                          checked={ch.enabled}
                          onChange={(e) =>
                            void patchChannel(ch.id, { enabled: e.currentTarget.checked }).then(
                              () => qc.invalidateQueries({ queryKey: ['channels'] }),
                            )
                          }
                        />
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
                  <Table.Th>Chat ID</Table.Th>
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
                      <Badge
                        color={
                          t.permission_status === 'ok'
                            ? 'teal'
                            : t.permission_status === 'unknown'
                              ? 'gray'
                              : 'red'
                        }
                      >
                        {t.permission_status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{t.enabled ? '是' : '否'}</Table.Td>
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
                              void sendTargetTestMessage(t.id, 'TG-forwarder test message')
                                .then((res) => setMsg(`测试消息已发送: ${JSON.stringify(res)}`))
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
          <TextInput label="Chat ID" value={chatId} onChange={(e) => setChatId(e.currentTarget.value)} />
          <TextInput label="标题" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
          <Select label="发布模式" data={MODES} value={mode} onChange={(v) => setMode(v ?? 'review')} />
          <Button loading={createSourceMut.isPending} onClick={() => createSourceMut.mutate()}>
            创建
          </Button>
        </Stack>
      </Modal>

      <Modal opened={targetOpen} onClose={() => setTargetOpen(false)} title="添加目标频道">
        <Stack>
          <TextInput label="Chat ID" value={chatId} onChange={(e) => setChatId(e.currentTarget.value)} />
          <TextInput label="标题" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
          <Button loading={createTargetMut.isPending} onClick={() => createTargetMut.mutate()}>
            创建
          </Button>
        </Stack>
      </Modal>
    </Stack>
  )
}
