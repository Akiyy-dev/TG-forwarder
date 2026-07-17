import {
  Badge,
  Button,
  Group,
  Modal,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listChannels } from '../api/channels'
import { type HistoryItem, listHistory } from '../api/history'
import { SourceBackendBadge } from '../components/SourceBackendBadge'
import { messageStatusLabel } from '../utils/labels'
import { sourceBackendLabel } from '../utils/sourceBackend'

const STATUS_OPTIONS = [
  'received',
  'processing',
  'pending_review',
  'pending_publish',
  'publishing',
  'published',
  'filtered',
  'failed',
  'retrying',
].map((value) => ({ value, label: messageStatusLabel(value) }))

function dateTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : '-'
}

export function HistoryPage() {
  const [page, setPage] = useState(1)
  const [sourceId, setSourceId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [detail, setDetail] = useState<HistoryItem | null>(null)
  const sources = useQuery({
    queryKey: ['channels', 'history-filter'],
    queryFn: () => listChannels({ page: 1, page_size: 100 }),
  })
  const history = useQuery({
    queryKey: ['history', page, sourceId, status],
    queryFn: () =>
      listHistory({
        page,
        page_size: 20,
        source_id: sourceId ? Number(sourceId) : undefined,
        status: status ?? undefined,
      }),
  })

  return (
    <Stack gap="md" className="page-enter">
      <div>
        <Title order={2}>消息历史</Title>
        <Text c="dimmed" size="sm">
          数据库中的完整处理记录，包含自动发布、规则决定、审核、过滤和失败消息
        </Text>
      </div>
      <Group align="end">
        <Select
          label="来源频道"
          placeholder="全部来源"
          clearable
          searchable
          w={280}
          value={sourceId}
          data={(sources.data?.items ?? []).map((source) => ({
            value: String(source.id),
            label: `${sourceBackendLabel(source.source_backend)} · ${source.title || source.username || source.chat_id}`,
          }))}
          onChange={(value) => {
            setSourceId(value)
            setPage(1)
          }}
        />
        <Select
          label="状态"
          placeholder="全部状态"
          clearable
          w={180}
          value={status}
          data={STATUS_OPTIONS}
          onChange={(value) => {
            setStatus(value)
            setPage(1)
          }}
        />
      </Group>

      <Table striped withTableBorder highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>来源</Table.Th>
            <Table.Th>消息 ID</Table.Th>
            <Table.Th>状态</Table.Th>
            <Table.Th>处理后内容</Table.Th>
            <Table.Th>投递</Table.Th>
            <Table.Th>更新时间</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(history.data?.items ?? []).map((item) => (
            <Table.Tr key={item.id}>
              <Table.Td>
                <Group gap={6} wrap="nowrap">
                  <SourceBackendBadge backend={item.source_backend} />
                  <Text size="sm">{item.source_title || item.source_chat_id}</Text>
                </Group>
              </Table.Td>
              <Table.Td>{item.source_message_id}</Table.Td>
              <Table.Td>
                <Badge variant="light" color={item.status === 'failed' ? 'red' : undefined}>
                  {messageStatusLabel(item.status)}
                </Badge>
              </Table.Td>
              <Table.Td maw={420}>
                <Text size="sm" lineClamp={2}>
                  {item.text || (item.media_type !== 'text' ? `[${item.media_type}]` : '-')}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="xs">
                  TG {item.target_message_ids.length} / API {item.api_delivery_count}
                </Text>
              </Table.Td>
              <Table.Td>{dateTime(item.updated_at)}</Table.Td>
              <Table.Td>
                <Button size="xs" variant="subtle" onClick={() => setDetail(item)}>
                  查看
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
          {!history.isLoading && (history.data?.items.length ?? 0) === 0 && (
            <Table.Tr>
              <Table.Td colSpan={7}>
                <Text c="dimmed">暂无历史记录</Text>
              </Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>
      {(history.data?.meta.total_pages ?? 0) > 1 && (
        <Pagination
          value={page}
          onChange={setPage}
          total={history.data?.meta.total_pages ?? 1}
        />
      )}

      <Modal opened={detail !== null} onClose={() => setDetail(null)} title="消息详情" size="lg">
        {detail && (
          <Stack gap="xs">
            <Text size="sm">来源：{detail.source_title || detail.source_chat_id}</Text>
            <Text size="sm">状态：{messageStatusLabel(detail.status)}</Text>
            <Text size="sm">接收时间：{dateTime(detail.received_at)}</Text>
            <Text size="sm">发布时间：{dateTime(detail.published_at)}</Text>
            {detail.skip_reason && <Text size="sm">原因：{detail.skip_reason}</Text>}
            {detail.error_message && <Text c="red" size="sm">错误：{detail.error_message}</Text>}
            <Text fw={600} mt="sm">处理后内容</Text>
            <Text style={{ whiteSpace: 'pre-wrap' }}>{detail.text || '-'}</Text>
          </Stack>
        )}
      </Modal>
    </Stack>
  )
}
