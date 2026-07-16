import {
  Badge,
  Button,
  Center,
  Checkbox,
  Group,
  Loader,
  Modal,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { listChannels } from '../api/channels'
import { batchPublish, batchReject, listReviews } from '../api/reviews'
import { SourceBackendBadge } from '../components/SourceBackendBadge'
import { useMe } from '../hooks/useAuth'
import { canWriteReviews } from '../utils/reviewPermissions'
import { mediaTypeLabel } from '../utils/labels'
import { reviewStatusColor, reviewStatusLabel } from '../utils/reviewStatus'
import { sourceBackendLabel } from '../utils/sourceBackend'

const STATUS_ALL = 'all'

const STATUS_OPTIONS = [
  { value: STATUS_ALL, label: '全部状态' },
  { value: 'pending', label: '待审核' },
  { value: 'editing', label: '编辑中' },
  { value: 'approved', label: '已批准' },
  { value: 'failed', label: '失败' },
  { value: 'published', label: '已发布' },
  { value: 'rejected', label: '已拒绝' },
]

export function ReviewsPage() {
  const { data: user } = useMe()
  const writable = canWriteReviews(user?.role)
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<string | null>(STATUS_ALL)
  const [sourceChatId, setSourceChatId] = useState<string | null>('all')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<number[]>([])
  const [confirm, setConfirm] = useState<'publish' | 'reject' | null>(null)

  const channels = useQuery({
    queryKey: ['channels', 'filter'],
    queryFn: () => listChannels({ page: 1, page_size: 100 }),
  })

  const query = useQuery({
    queryKey: ['reviews', page, status, q, sourceChatId],
    queryFn: () =>
      listReviews({
        page,
        page_size: 20,
        status: status && status !== STATUS_ALL ? status : undefined,
        q: q || undefined,
        source_chat_id:
          sourceChatId && sourceChatId !== 'all' ? Number(sourceChatId) : undefined,
      }),
    refetchInterval: 30_000,
  })

  const items = query.data?.items ?? []
  const meta = query.data?.meta
  const revisions = useMemo(
    () => Object.fromEntries(items.map((i) => [String(i.id), i.revision])),
    [items],
  )

  const batchMut = useMutation({
    mutationFn: async (mode: 'publish' | 'reject') => {
      if (mode === 'publish') return batchPublish(selected, revisions)
      return batchReject(selected, revisions)
    },
    onSuccess: () => {
      setSelected([])
      setConfirm(null)
      void qc.invalidateQueries({ queryKey: ['reviews'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  function toggle(id: number, checked: boolean) {
    setSelected((prev) => (checked ? [...new Set([...prev, id])] : prev.filter((x) => x !== id)))
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Title order={2}>审核队列</Title>
          <Text c="dimmed" size="sm">
            列表每 30 秒自动刷新
          </Text>
        </div>
        <Button variant="light" onClick={() => query.refetch()} loading={query.isFetching}>
          刷新
        </Button>
      </Group>

      <Group align="flex-end">
        <Select
          label="状态"
          data={STATUS_OPTIONS}
          value={status}
          onChange={(v) => {
            setStatus(v ?? STATUS_ALL)
            setPage(1)
          }}
          allowDeselect={false}
          w={180}
        />
        <Select
          label="来源频道"
          data={[
            { value: 'all', label: '全部来源' },
            ...(channels.data?.items ?? []).map((c) => ({
              value: String(c.chat_id),
              label: `${sourceBackendLabel(c.source_backend)} · ${c.title || c.username || String(c.chat_id)}`,
            })),
          ]}
          value={sourceChatId}
          onChange={(v) => {
            setSourceChatId(v ?? 'all')
            setPage(1)
          }}
          searchable
          allowDeselect={false}
          w={220}
        />
        <TextInput
          label="搜索文本"
          placeholder="匹配正文文本"
          value={q}
          onChange={(e) => {
            setQ(e.currentTarget.value)
            setPage(1)
          }}
          w={260}
        />
        {writable && selected.length > 0 && (
          <Group>
            <Button color="teal" onClick={() => setConfirm('publish')}>
              批量发布 ({selected.length})
            </Button>
            <Button color="red" variant="light" onClick={() => setConfirm('reject')}>
              批量拒绝
            </Button>
          </Group>
        )}
      </Group>

      {query.error && (
        <Text c="red">
          {query.error instanceof ApiError
            ? `${query.error.message} (${query.error.code})`
            : (query.error as Error).message}
        </Text>
      )}

      {query.isLoading ? (
        <Center py="xl">
          <Loader />
        </Center>
      ) : (
        <Table striped highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              {writable && <Table.Th w={40} />}
              <Table.Th>ID</Table.Th>
              <Table.Th>状态</Table.Th>
              <Table.Th>来源</Table.Th>
              <Table.Th>摘要</Table.Th>
              <Table.Th>媒体</Table.Th>
              <Table.Th>更新</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((row) => (
              <Table.Tr key={row.id}>
                {writable && (
                  <Table.Td>
                    <Checkbox
                      checked={selected.includes(row.id)}
                      onChange={(e) => toggle(row.id, e.currentTarget.checked)}
                      disabled={['published', 'rejected', 'expired'].includes(row.status)}
                    />
                  </Table.Td>
                )}
                <Table.Td>
                  <Text component={Link} to={`/reviews/${row.id}`} c="teal" fw={600}>
                    #{row.id}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge color={reviewStatusColor(row.status)} variant="light">
                    {reviewStatusLabel(row.status)}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    <SourceBackendBadge backend={row.source_backend} size="xs" />
                    <Text
                      size="sm"
                      title={`ID ${row.source_chat_id}`}
                      lineClamp={1}
                    >
                      {row.source_title || String(row.source_chat_id)}
                      <Text span c="dimmed" size="xs">
                        {' '}
                        /{row.source_message_id}
                      </Text>
                    </Text>
                  </Group>
                </Table.Td>
                <Table.Td maw={360}>
                  <Text lineClamp={1} size="sm">
                    {row.final_text || '(空)'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {mediaTypeLabel(row.media_type)} · {row.media_count}
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {row.updated_at ?? '-'}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
            {items.length === 0 && !query.error && (
              <Table.Tr>
                <Table.Td colSpan={writable ? 7 : 6}>
                  <Text c="dimmed">暂无审核任务</Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      )}

      {meta && meta.total_pages > 1 && (
        <Pagination value={page} onChange={setPage} total={meta.total_pages} />
      )}

      <Modal
        opened={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm === 'publish' ? '确认批量发布？' : '确认批量拒绝？'}
      >
        <Stack>
          <Text size="sm">将对 {selected.length} 条任务执行操作。</Text>
          {batchMut.error && (
            <Text c="red" size="sm">
              {(batchMut.error as ApiError).message}
            </Text>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirm(null)}>
              取消
            </Button>
            <Button
              color={confirm === 'publish' ? 'teal' : 'red'}
              loading={batchMut.isPending}
              onClick={() => confirm && batchMut.mutate(confirm)}
            >
              确认
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
