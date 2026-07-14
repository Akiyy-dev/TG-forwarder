import {
  Badge,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError } from '../api/client'
import {
  createRule,
  deleteRule,
  duplicateRule,
  listRules,
  patchRule,
  testRule,
  type RuleWrite,
} from '../api/rules'
import { useMe } from '../hooks/useAuth'

const ACTIONS = ['flag', 'reject', 'require_review', 'replace', 'remove', 'add_tag']

export function RulesPage() {
  const { data: user } = useMe()
  const isAdmin = user?.role === 'super_admin'
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [opened, setOpened] = useState(false)
  const [testOpen, setTestOpen] = useState(false)
  const [testRuleId, setTestRuleId] = useState<number | null>(null)
  const [testSample, setTestSample] = useState('')
  const [testResult, setTestResult] = useState<string | null>(null)
  const [form, setForm] = useState<RuleWrite>({
    name: '',
    pattern: '',
    action: 'flag',
    priority: 100,
    enabled: true,
    replacement: '',
  })
  const [error, setError] = useState<string | null>(null)

  const query = useQuery({
    queryKey: ['rules', q],
    queryFn: () => listRules({ page: 1, page_size: 100, q: q || undefined }),
    enabled: isAdmin,
  })

  const createMut = useMutation({
    mutationFn: () => createRule(form),
    onSuccess: async () => {
      setOpened(false)
      await qc.invalidateQueries({ queryKey: ['rules'] })
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : '创建失败'),
  })

  if (!isAdmin) {
    return (
      <Stack>
        <Title order={2}>规则管理</Title>
        <Text c="dimmed">仅超级管理员可管理规则。</Text>
      </Stack>
    )
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Title order={2}>规则管理</Title>
          <Text c="dimmed" size="sm">
            关键词 / 正则规则 CRUD 与测试
          </Text>
        </div>
        <Button onClick={() => setOpened(true)}>新建规则</Button>
      </Group>

      <TextInput
        placeholder="搜索名称或 pattern"
        value={q}
        onChange={(e) => setQ(e.currentTarget.value)}
        w={320}
      />
      {error && <Text c="red">{error}</Text>}

      <Table striped withTableBorder highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>名称</Table.Th>
            <Table.Th>Pattern</Table.Th>
            <Table.Th>动作</Table.Th>
            <Table.Th>优先级</Table.Th>
            <Table.Th>命中</Table.Th>
            <Table.Th>启用</Table.Th>
            <Table.Th>操作</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(query.data?.items ?? []).map((rule) => (
            <Table.Tr key={rule.id}>
              <Table.Td>{rule.name}</Table.Td>
              <Table.Td>
                <Text size="sm" ff="monospace">
                  {rule.pattern}
                </Text>
              </Table.Td>
              <Table.Td>
                <Badge variant="light">{rule.action}</Badge>
              </Table.Td>
              <Table.Td>{rule.priority}</Table.Td>
              <Table.Td>{rule.hit_count}</Table.Td>
              <Table.Td>
                <Switch
                  checked={rule.enabled}
                  onChange={(e) =>
                    void patchRule(rule.id, { enabled: e.currentTarget.checked }).then(() =>
                      qc.invalidateQueries({ queryKey: ['rules'] }),
                    )
                  }
                />
              </Table.Td>
              <Table.Td>
                <Group gap={6}>
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => {
                      setForm({
                        name: rule.name,
                        pattern: rule.pattern,
                        action: rule.action,
                        replacement: rule.replacement,
                        priority: rule.priority,
                        enabled: rule.enabled,
                      })
                      setTestRuleId(rule.id)
                      setTestSample('')
                      setTestResult(null)
                      setTestOpen(true)
                    }}
                  >
                    测试
                  </Button>
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() =>
                      void duplicateRule(rule.id).then(() =>
                        qc.invalidateQueries({ queryKey: ['rules'] }),
                      )
                    }
                  >
                    复制
                  </Button>
                  <Button
                    size="xs"
                    color="red"
                    variant="subtle"
                    onClick={() => {
                      if (window.confirm(`删除规则 ${rule.name}?`)) {
                        void deleteRule(rule.id).then(() =>
                          qc.invalidateQueries({ queryKey: ['rules'] }),
                        )
                      }
                    }}
                  >
                    删除
                  </Button>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      <Modal opened={opened} onClose={() => setOpened(false)} title="新建规则">
        <Stack>
          <TextInput
            label="名称"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
            required
          />
          <TextInput
            label="Pattern"
            value={form.pattern}
            onChange={(e) => setForm({ ...form, pattern: e.currentTarget.value })}
            required
          />
          <Select
            label="动作"
            data={ACTIONS}
            value={form.action}
            onChange={(v) => setForm({ ...form, action: v ?? 'flag' })}
          />
          {(form.action === 'replace' || form.action === 'add_tag') && (
            <TextInput
              label="替换 / 标签"
              value={form.replacement ?? ''}
              onChange={(e) => setForm({ ...form, replacement: e.currentTarget.value })}
            />
          )}
          <TextInput
            label="优先级"
            type="number"
            value={String(form.priority ?? 100)}
            onChange={(e) => setForm({ ...form, priority: Number(e.currentTarget.value) })}
          />
          <Button loading={createMut.isPending} onClick={() => createMut.mutate()}>
            创建
          </Button>
        </Stack>
      </Modal>

      <Modal opened={testOpen} onClose={() => setTestOpen(false)} title="规则测试">
        <Stack>
          <Textarea
            label="样例文本"
            value={testSample}
            onChange={(e) => setTestSample(e.currentTarget.value)}
            minRows={4}
          />
          <Button
            onClick={() => {
              void testRule(testRuleId, testSample, form)
                .then((res) =>
                  setTestResult(
                    `matched=${res.matched}\nfinal_text=${res.final_text}\nhits=${JSON.stringify(res.hits)}`,
                  ),
                )
                .catch((err: unknown) =>
                  setTestResult(err instanceof ApiError ? err.message : '测试失败'),
                )
            }}
          >
            运行测试
          </Button>
          {testResult && (
            <Text ff="monospace" size="sm" style={{ whiteSpace: 'pre-wrap' }}>
              {testResult}
            </Text>
          )}
        </Stack>
      </Modal>
    </Stack>
  )
}
