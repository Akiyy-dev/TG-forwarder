import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Image,
  Modal,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  Title,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import {
  approveReview,
  editReview,
  fetchReviewPreview,
  getReview,
  publishReview,
  reapplyRules,
  rejectReview,
  restoreReview,
} from '../api/reviews'
import { useMe } from '../hooks/useAuth'
import {
  canMutateTask,
  canPublishTask,
  canRejectTask,
  canWriteReviews,
} from '../utils/reviewPermissions'
import { reviewStatusColor, reviewStatusLabel } from '../utils/reviewStatus'

export function ReviewDetailPage() {
  const { id } = useParams()
  const taskId = Number(id)
  const { data: user } = useMe()
  const qc = useQueryClient()
  const [draft, setDraft] = useState('')
  const [dirty, setDirty] = useState(false)
  const [confirm, setConfirm] = useState<'publish' | 'reject' | 'reapply-reject' | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  const detail = useQuery({
    queryKey: ['review', taskId],
    queryFn: () => getReview(taskId),
    enabled: Number.isFinite(taskId),
  })
  const preview = useQuery({
    queryKey: ['review-preview', taskId],
    queryFn: () => fetchReviewPreview(taskId),
    enabled: Number.isFinite(taskId),
  })

  const task = detail.data?.task

  useEffect(() => {
    if (task && !dirty) setDraft(task.final_text)
  }, [task, dirty])

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (!dirty) return
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const invalidate = async () => {
    await qc.invalidateQueries({ queryKey: ['review', taskId] })
    await qc.invalidateQueries({ queryKey: ['review-preview', taskId] })
    await qc.invalidateQueries({ queryKey: ['reviews'] })
    await qc.invalidateQueries({ queryKey: ['dashboard'] })
  }

  const wrap = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      setDirty(false)
      setConfirm(null)
      await invalidate()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : '操作失败'
      setError(msg)
      if (err instanceof ApiError && err.status === 409) {
        await invalidate()
        setDirty(false)
      }
    }
  }

  const saveMut = useMutation({
    mutationFn: () => editReview(taskId, draft, task!.revision),
    onSuccess: async () => {
      setDirty(false)
      await invalidate()
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : '保存失败'),
  })

  if (detail.isLoading) return <Text>加载中…</Text>
  if (detail.error || !task) {
    return (
      <Alert color="red" title="无法加载审核任务">
        {(detail.error as Error)?.message ?? '任务不存在'}
      </Alert>
    )
  }

  const writable = canWriteReviews(user?.role)
  const canEdit = canMutateTask(user?.role, task.status)
  const canPub = canPublishTask(user?.role, task.status)
  const canRej = canRejectTask(user?.role, task.status)

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Group gap="sm">
            <Title order={2}>审核 #{task.id}</Title>
            <Badge color={reviewStatusColor(task.status)} variant="light">
              {reviewStatusLabel(task.status)}
            </Badge>
            <Badge variant="outline">rev {task.revision}</Badge>
          </Group>
          <Text c="dimmed" size="sm">
            来源 {task.source_chat_id}/{task.source_message_id}
            {task.target_chat_id ? ` → ${task.target_chat_id}` : ''}
          </Text>
        </div>
        <Button component={Link} to="/reviews" variant="default">
          返回列表
        </Button>
      </Group>

      {error && (
        <Alert color="red" onClose={() => setError(null)} withCloseButton>
          {error}
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="md">
        <Card withBorder padding="md">
          <Title order={5} mb="sm">
            原文
          </Title>
          <Text style={{ whiteSpace: 'pre-wrap' }} size="sm">
            {task.original_text || '(空)'}
          </Text>
          {(task.detected_keywords?.length || 0) > 0 && (
            <Group gap={6} mt="md">
              {task.detected_keywords!.map((k, i) => (
                <Badge key={i} color="orange" variant="light">
                  {String(k)}
                </Badge>
              ))}
            </Group>
          )}
        </Card>

        <Card withBorder padding="md">
          <Group justify="space-between" mb="sm">
            <Title order={5}>编辑区</Title>
            {dirty && (
              <Badge color="orange" variant="dot">
                未保存
              </Badge>
            )}
          </Group>
          <Textarea
            value={draft}
            onChange={(e) => {
              setDraft(e.currentTarget.value)
              setDirty(e.currentTarget.value !== task.final_text)
            }}
            minRows={12}
            autosize
            maxLength={4096}
            disabled={!canEdit}
          />
          <Text size="xs" c="dimmed" mt={4}>
            {draft.length} / 4096
          </Text>
          {writable && canEdit && (
            <Group mt="sm">
              <Button
                onClick={() => saveMut.mutate()}
                loading={saveMut.isPending}
                disabled={!dirty}
              >
                保存编辑
              </Button>
              <Button
                variant="light"
                onClick={() =>
                  void wrap(() =>
                    restoreReview(
                      taskId,
                      task.revision,
                      detail.data!.revisions.find((r) => r.source === 'original')
                        ?.revision_number ?? 1,
                    ),
                  )
                }
              >
                恢复原文
              </Button>
              <Button
                variant="light"
                color="grape"
                onClick={() => {
                  void (async () => {
                    setError(null)
                    try {
                      const res = await reapplyRules(taskId, {
                        expected_revision: task.revision,
                        source: 'original',
                      })
                      if (res.preview?.needs_confirm) {
                        setConfirm('reapply-reject')
                        return
                      }
                      setDirty(false)
                      await invalidate()
                    } catch (err) {
                      setError(err instanceof ApiError ? err.message : '重跑规则失败')
                    }
                  })()
                }}
              >
                重跑规则
              </Button>
            </Group>
          )}
        </Card>

        <Stack>
          <Card withBorder padding="md">
            <Title order={5} mb="sm">
              操作
            </Title>
            {!writable && <Text c="dimmed">当前角色为只读</Text>}
            {writable && (
              <Stack gap="xs">
                <Button
                  variant="light"
                  disabled={!canEdit}
                  onClick={() =>
                    void wrap(() => approveReview(taskId, task.revision, reason || undefined))
                  }
                >
                  批准
                </Button>
                <Button color="teal" disabled={!canPub} onClick={() => setConfirm('publish')}>
                  发布
                </Button>
                <Button color="red" variant="light" disabled={!canRej} onClick={() => setConfirm('reject')}>
                  拒绝
                </Button>
                <Textarea
                  label="原因（可选）"
                  value={reason}
                  onChange={(e) => setReason(e.currentTarget.value)}
                  minRows={2}
                />
              </Stack>
            )}
          </Card>

          <Card withBorder padding="md">
            <Title order={5} mb="sm">
              发布预览
            </Title>
            {preview.data ? (
              <Stack gap="xs">
                <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                  {preview.data.text || '(空)'}
                </Text>
                <Text size="xs" c="dimmed">
                  {preview.data.text_length}/{preview.data.limit}
                  {preview.data.truncated ? ' · 已截断' : ''}
                </Text>
                <SimpleGrid cols={2}>
                  {preview.data.media_items.map((m) =>
                    m.available && m.url ? (
                      <Image key={m.index} src={m.url} alt={m.original_filename ?? ''} radius="sm" />
                    ) : (
                      <Text key={m.index} size="xs" c="dimmed">
                        媒体不可用 #{m.index}
                      </Text>
                    ),
                  )}
                </SimpleGrid>
              </Stack>
            ) : (
              <Text c="dimmed" size="sm">
                加载预览中…
              </Text>
            )}
          </Card>
        </Stack>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder padding="md">
          <Title order={5} mb="sm">
            版本历史
          </Title>
          <Stack gap="xs">
            {(detail.data?.revisions ?? []).map((rev) => (
              <Group key={rev.revision_number} justify="space-between" wrap="nowrap">
                <div>
                  <Text size="sm" fw={600}>
                    r{rev.revision_number} · {rev.source}
                  </Text>
                  <Text size="xs" c="dimmed" lineClamp={1}>
                    {rev.content}
                  </Text>
                </div>
                {canEdit && (
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() =>
                      void wrap(() =>
                        restoreReview(taskId, task.revision, rev.revision_number),
                      )
                    }
                  >
                    恢复
                  </Button>
                )}
              </Group>
            ))}
          </Stack>
        </Card>
        <Card withBorder padding="md">
          <Title order={5} mb="sm">
            操作记录
          </Title>
          <Stack gap={6}>
            {(detail.data?.actions ?? []).map((a, idx) => (
              <Text key={idx} size="xs">
                {a.created_at} · {a.action} · {a.old_status ?? '-'} → {a.new_status ?? '-'}
              </Text>
            ))}
          </Stack>
        </Card>
      </SimpleGrid>

      <Modal
        opened={confirm !== null}
        onClose={() => setConfirm(null)}
        title={
          confirm === 'publish'
            ? '确认发布？'
            : confirm === 'reject'
              ? '确认拒绝？'
              : '规则要求自动拒绝，确认执行？'
        }
      >
        <Stack>
          <Text size="sm">此操作将改变审核状态，请确认。</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirm(null)}>
              取消
            </Button>
            <Button
              color={confirm === 'publish' ? 'teal' : 'red'}
              onClick={() => {
                if (confirm === 'publish') {
                  void wrap(() => publishReview(taskId, task.revision, reason || undefined))
                } else if (confirm === 'reject') {
                  void wrap(() => rejectReview(taskId, task.revision, reason || undefined))
                } else {
                  void wrap(() =>
                    reapplyRules(taskId, {
                      expected_revision: task.revision,
                      source: 'original',
                      confirm_reject: true,
                    }),
                  )
                }
              }}
            >
              确认
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
