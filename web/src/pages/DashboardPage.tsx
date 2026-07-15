import {
  Badge,
  Button,
  Card,
  Group,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { useDashboard } from '../hooks/useDashboard'
import { reviewStatusColor, reviewStatusLabel } from '../utils/reviewStatus'

function StatCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card withBorder padding="md" radius="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text fz={28} fw={700} mt={4}>
        {value}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed" mt={4}>
          {hint}
        </Text>
      )}
    </Card>
  )
}

export function DashboardPage() {
  const { data, isLoading, isFetching, refetch, error } = useDashboard()

  if (error) {
    return <Text c="red">加载仪表盘失败：{(error as Error).message}</Text>
  }

  const service = data?.service
  const counts = data?.counts

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <div>
          <Title order={2}>仪表盘</Title>
          <Text c="dimmed" size="sm">
            只读概览 · 每 30 秒自动刷新
          </Text>
        </div>
        <Button variant="light" onClick={() => refetch()} loading={isFetching || isLoading}>
          刷新
        </Button>
      </Group>

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        <StatCard
          label="服务状态"
          value={service?.publishing_paused ? '已暂停' : '运行中'}
          hint={`启动于 ${service?.started_at ?? '-'}`}
        />
        <StatCard label="队列长度" value={service?.queue_size ?? '-'} />
        <StatCard label="待审核" value={counts?.pending_review ?? '-'} />
        <StatCard
          label="组件"
          value={[
            service?.listener_running ? '监听器正常' : '监听器离线',
            service?.bot_available ? 'Bot 正常' : 'Bot 离线',
          ].join(' · ')}
        />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        <StatCard label="今日接收" value={counts?.today_received ?? '-'} />
        <StatCard label="今日发布" value={counts?.today_published ?? '-'} />
        <StatCard label="今日拒绝" value={counts?.today_rejected ?? '-'} />
        <StatCard label="今日失败" value={counts?.today_failed ?? '-'} />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <StatCard label="来源频道" value={counts?.source_channels ?? '-'} />
        <StatCard label="目标频道" value={counts?.target_channels ?? '-'} />
        <StatCard label="规则数" value={counts?.rules ?? '-'} />
      </SimpleGrid>

      <Card withBorder padding="md" radius="md">
        <Title order={4} mb="sm">
          最近审核
        </Title>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>ID</Table.Th>
              <Table.Th>状态</Table.Th>
              <Table.Th>来源</Table.Th>
              <Table.Th>更新时间</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(data?.recent_reviews ?? []).map((row) => (
              <Table.Tr key={row.id}>
                <Table.Td>{row.id}</Table.Td>
                <Table.Td>
                  <Badge color={reviewStatusColor(row.status)} variant="light">
                    {reviewStatusLabel(row.status)}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  {row.source_chat_id}/{row.source_message_id}
                </Table.Td>
                <Table.Td>{row.updated_at ?? '-'}</Table.Td>
              </Table.Tr>
            ))}
            {(data?.recent_reviews?.length ?? 0) === 0 && (
              <Table.Tr>
                <Table.Td colSpan={4}>
                  <Text c="dimmed">暂无审核任务</Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Card>

      <Card withBorder padding="md" radius="md">
        <Title order={4} mb="sm">
          最近错误
        </Title>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>来源</Table.Th>
              <Table.Th>重试</Table.Th>
              <Table.Th>错误</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(data?.recent_errors ?? []).map((row, idx) => (
              <Table.Tr key={`${row.source_chat_id}-${row.source_message_id}-${idx}`}>
                <Table.Td>
                  {row.source_chat_id}/{row.source_message_id}
                </Table.Td>
                <Table.Td>{row.retry_count}</Table.Td>
                <Table.Td>{row.error ?? '-'}</Table.Td>
              </Table.Tr>
            ))}
            {(data?.recent_errors?.length ?? 0) === 0 && (
              <Table.Tr>
                <Table.Td colSpan={3}>
                  <Text c="dimmed">暂无错误</Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  )
}
