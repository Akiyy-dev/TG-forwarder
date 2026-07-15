import { Alert, Badge, Button, Card, Group, SimpleGrid, Stack, Text, Title } from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError } from '../api/client'
import {
  fetchSystemStatus,
  pausePublishing,
  recoverPending,
  resumePublishing,
} from '../api/system'
import { useMe } from '../hooks/useAuth'
import { useStatusEvents } from '../hooks/useStatusEvents'
import { messageStatusLabel } from '../utils/labels'

export function SystemPage() {
  const { data: user } = useMe()
  const isAdmin = user?.role === 'super_admin'
  const qc = useQueryClient()
  const live = useStatusEvents(true)
  const [msg, setMsg] = useState<string | null>(null)

  const status = useQuery({
    queryKey: ['system'],
    queryFn: fetchSystemStatus,
    refetchInterval: 15_000,
  })

  const pauseMut = useMutation({
    mutationFn: pausePublishing,
    onSuccess: async () => {
      setMsg('已暂停发布')
      await qc.invalidateQueries({ queryKey: ['system'] })
      await qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (err) => setMsg(err instanceof ApiError ? err.message : '操作失败'),
  })
  const resumeMut = useMutation({
    mutationFn: resumePublishing,
    onSuccess: async (data) => {
      setMsg(`已恢复发布，重新入队 ${data.requeued} 条`)
      await qc.invalidateQueries({ queryKey: ['system'] })
      await qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (err) => setMsg(err instanceof ApiError ? err.message : '操作失败'),
  })
  const recoverMut = useMutation({
    mutationFn: recoverPending,
    onSuccess: async (data) => {
      setMsg(`已重试入队 ${data.requeued} 条`)
      await qc.invalidateQueries({ queryKey: ['system'] })
    },
    onError: (err) => setMsg(err instanceof ApiError ? err.message : '操作失败'),
  })

  const data = status.data
  const paused = live?.publishing_paused ?? data?.publishing_paused

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Title order={2}>系统状态</Title>
          <Text c="dimmed" size="sm">
            实时状态推送与发布控制
          </Text>
        </div>
        <Badge color={paused ? 'orange' : 'teal'} variant="light">
          {paused ? '已暂停' : '运行中'}
        </Badge>
      </Group>

      {msg && (
        <Alert withCloseButton onClose={() => setMsg(null)}>
          {msg}
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        <Card withBorder>
          <Text size="xs" c="dimmed">
            队列
          </Text>
          <Text fw={700} fz={24}>
            {live?.queue_size ?? data?.queue_size ?? '-'}
          </Text>
        </Card>
        <Card withBorder>
          <Text size="xs" c="dimmed">
            待审核
          </Text>
          <Text fw={700} fz={24}>
            {live?.pending_review ?? '-'}
          </Text>
        </Card>
        <Card withBorder>
          <Text size="xs" c="dimmed">
            监听器 / Bot
          </Text>
          <Text fw={700}>
            {data?.listener_running ? '监听器正常' : '监听器离线'} ·{' '}
            {data?.bot_available ? 'Bot 正常' : 'Bot 离线'}
          </Text>
        </Card>
        <Card withBorder>
          <Text size="xs" c="dimmed">
            最近错误
          </Text>
          <Text size="sm">{data?.last_error || '无'}</Text>
        </Card>
      </SimpleGrid>

      {isAdmin ? (
        <Group>
          <Button color="orange" loading={pauseMut.isPending} onClick={() => pauseMut.mutate()}>
            暂停发布
          </Button>
          <Button color="teal" loading={resumeMut.isPending} onClick={() => resumeMut.mutate()}>
            恢复并重入队
          </Button>
          <Button variant="light" loading={recoverMut.isPending} onClick={() => recoverMut.mutate()}>
            仅重入队
          </Button>
        </Group>
      ) : (
        <Text c="dimmed">查看中；暂停/恢复需超级管理员。</Text>
      )}

      <Card withBorder>
        <Title order={5} mb="sm">
          消息状态计数
        </Title>
        <Group gap="sm">
          {Object.entries(data?.message_stats ?? {}).map(([k, v]) => (
            <Badge key={k} variant="outline">
              {messageStatusLabel(k)}: {v}
            </Badge>
          ))}
          {Object.keys(data?.message_stats ?? {}).length === 0 && (
            <Text c="dimmed" size="sm">
              暂无数据
            </Text>
          )}
        </Group>
      </Card>
    </Stack>
  )
}
