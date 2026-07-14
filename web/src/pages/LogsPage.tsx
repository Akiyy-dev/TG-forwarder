import { Pagination, Stack, Table, Tabs, Text, Title } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  listProcessingLogs,
  listReviewActionLogs,
  listRuleExecutionLogs,
} from '../api/system'

export function LogsPage() {
  const [tab, setTab] = useState<string | null>('review')
  const [page, setPage] = useState(1)

  const review = useQuery({
    queryKey: ['logs', 'review', page],
    queryFn: () => listReviewActionLogs(page),
    enabled: tab === 'review',
  })
  const processing = useQuery({
    queryKey: ['logs', 'processing', page],
    queryFn: () => listProcessingLogs(page),
    enabled: tab === 'processing',
  })
  const rules = useQuery({
    queryKey: ['logs', 'rules', page],
    queryFn: () => listRuleExecutionLogs(page),
    enabled: tab === 'rules',
  })

  const active =
    tab === 'processing' ? processing : tab === 'rules' ? rules : review

  return (
    <Stack gap="md">
      <div>
        <Title order={2}>系统日志</Title>
        <Text c="dimmed" size="sm">
          审核动作 / 处理链路 / 规则命中（只读）
        </Text>
      </div>

      <Tabs
        value={tab}
        onChange={(v) => {
          setTab(v)
          setPage(1)
        }}
      >
        <Tabs.List>
          <Tabs.Tab value="review">审核动作</Tabs.Tab>
          <Tabs.Tab value="processing">处理日志</Tabs.Tab>
          <Tabs.Tab value="rules">规则命中</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="review" pt="md">
          <LogTable
            columns={['id', 'review_task_id', 'action', 'old_status', 'new_status', 'created_at']}
            rows={(review.data?.items ?? []) as Array<Record<string, unknown>>}
          />
        </Tabs.Panel>
        <Tabs.Panel value="processing" pt="md">
          <LogTable
            columns={[
              'id',
              'message_record_id',
              'processor_name',
              'status',
              'duration_ms',
              'created_at',
            ]}
            rows={(processing.data?.items ?? []) as Array<Record<string, unknown>>}
          />
        </Tabs.Panel>
        <Tabs.Panel value="rules" pt="md">
          <LogTable
            columns={['id', 'rule_name', 'action', 'matched_text', 'review_task_id', 'created_at']}
            rows={(rules.data?.items ?? []) as Array<Record<string, unknown>>}
          />
        </Tabs.Panel>
      </Tabs>

      {(active.data?.meta.total_pages ?? 0) > 1 && (
        <Pagination
          value={page}
          onChange={setPage}
          total={active.data?.meta.total_pages ?? 1}
        />
      )}
    </Stack>
  )
}

function LogTable({
  columns,
  rows,
}: {
  columns: string[]
  rows: Array<Record<string, unknown>>
}) {
  return (
    <Table striped withTableBorder highlightOnHover>
      <Table.Thead>
        <Table.Tr>
          {columns.map((c) => (
            <Table.Th key={c}>{c}</Table.Th>
          ))}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((row, idx) => (
          <Table.Tr key={idx}>
            {columns.map((c) => (
              <Table.Td key={c}>
                <Text size="xs">{formatCell(row[c])}</Text>
              </Table.Td>
            ))}
          </Table.Tr>
        ))}
        {rows.length === 0 && (
          <Table.Tr>
            <Table.Td colSpan={columns.length}>
              <Text c="dimmed">暂无日志</Text>
            </Table.Td>
          </Table.Tr>
        )}
      </Table.Tbody>
    </Table>
  )
}

function formatCell(value: unknown): string {
  if (value == null) return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
