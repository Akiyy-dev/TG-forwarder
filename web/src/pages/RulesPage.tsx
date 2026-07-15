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
import {
  HAS_MEDIA_PATTERN_OPTIONS,
  RULE_ACTION_OPTIONS,
  RULE_TYPE_OPTIONS,
  ruleActionLabel,
  ruleTypeLabel,
} from '../utils/labels'

export function RulesPage() {
  const { data: user } = useMe()
  const isAdmin = user?.role === 'super_admin'
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [opened, setOpened] = useState(false)
  const [testOpen, setTestOpen] = useState(false)
  const [testRuleId, setTestRuleId] = useState<number | null>(null)
  const [testSample, setTestSample] = useState('')
  const [testMediaType, setTestMediaType] = useState('text')
  const [testResult, setTestResult] = useState<string | null>(null)
  const [form, setForm] = useState<RuleWrite>({
    name: '',
    pattern: '',
    rule_type: 'keyword',
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

  const isHasMedia = form.rule_type === 'has_media'

  const createMut = useMutation({
    mutationFn: () =>
      createRule({
        ...form,
        pattern: isHasMedia ? form.pattern || 'has' : form.pattern,
      }),
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
            关键词 / 正则 / 媒体判断规则的增删改查与测试
          </Text>
        </div>
        <Button
          onClick={() => {
            setForm({
              name: '',
              pattern: '',
              rule_type: 'keyword',
              action: 'flag',
              priority: 100,
              enabled: true,
              replacement: '',
            })
            setOpened(true)
          }}
        >
          新建规则
        </Button>
      </Group>

      <TextInput
        placeholder="搜索名称或匹配模式"
        value={q}
        onChange={(e) => setQ(e.currentTarget.value)}
        w={320}
      />
      {error && <Text c="red">{error}</Text>}

      <Table striped withTableBorder highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>名称</Table.Th>
            <Table.Th>类型</Table.Th>
            <Table.Th>匹配模式</Table.Th>
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
                <Badge variant="outline">{ruleTypeLabel(rule.rule_type)}</Badge>
              </Table.Td>
              <Table.Td>
                <Text size="sm" ff="monospace">
                  {rule.rule_type === 'has_media'
                    ? rule.pattern === 'none'
                      ? '无媒体'
                      : '有媒体'
                    : rule.pattern}
                </Text>
              </Table.Td>
              <Table.Td>
                <Badge variant="light">{ruleActionLabel(rule.action)}</Badge>
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
                        rule_type: rule.rule_type,
                        action: rule.action,
                        replacement: rule.replacement,
                        priority: rule.priority,
                        enabled: rule.enabled,
                      })
                      setTestRuleId(rule.id)
                      setTestSample('')
                      setTestMediaType('photo')
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
          <Select
            label="类型"
            data={RULE_TYPE_OPTIONS}
            value={form.rule_type ?? 'keyword'}
            onChange={(v) => {
              const ruleType = v ?? 'keyword'
              setForm({
                ...form,
                rule_type: ruleType,
                pattern: ruleType === 'has_media' ? 'has' : form.pattern,
              })
            }}
          />
          {isHasMedia ? (
            <Select
              label="媒体条件"
              data={HAS_MEDIA_PATTERN_OPTIONS}
              value={form.pattern || 'has'}
              onChange={(v) => setForm({ ...form, pattern: v ?? 'has' })}
            />
          ) : (
            <TextInput
              label="匹配模式"
              value={form.pattern}
              onChange={(e) => setForm({ ...form, pattern: e.currentTarget.value })}
              required
            />
          )}
          <Select
            label="动作"
            data={RULE_ACTION_OPTIONS}
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
          <Select
            label="样例媒体类型"
            data={[
              { value: 'text', label: '文本' },
              { value: 'photo', label: '图片' },
              { value: 'video', label: '视频' },
              { value: 'album', label: '相册' },
              { value: 'sticker', label: '贴纸' },
            ]}
            value={testMediaType}
            onChange={(v) => setTestMediaType(v ?? 'text')}
          />
          <Button
            onClick={() => {
              void testRule(testRuleId, testSample, form, testMediaType)
                .then((res) =>
                  setTestResult(
                    `是否命中=${res.matched ? '是' : '否'}\n最终文本=${res.final_text}\n命中详情=${JSON.stringify(res.hits)}`,
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
