import {
  ActionIcon,
  Badge,
  Group,
  Text,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core'
import { useDashboard } from '../hooks/useDashboard'
import { useLogout, useMe } from '../hooks/useAuth'

export function AppTopbar() {
  const { data: user } = useMe()
  const { data: dash } = useDashboard()
  const logout = useLogout()
  const { colorScheme, setColorScheme } = useMantineColorScheme()

  const paused = dash?.service.publishing_paused
  const pending = dash?.counts.pending_review ?? 0

  return (
    <Group h="100%" px="md" justify="space-between" wrap="nowrap">
      <Group gap="sm">
        <Text fw={700}>TG-forwarder</Text>
        <Badge color={paused ? 'orange' : 'teal'} variant="light">
          {paused ? '发布已暂停' : '运行中'}
        </Badge>
        <Badge color={pending > 0 ? 'yellow' : 'gray'} variant="outline">
          待审核 {pending}
        </Badge>
      </Group>
      <Group gap="sm">
        <Tooltip label={colorScheme === 'dark' ? '切换亮色' : '切换暗色'}>
          <ActionIcon
            variant="subtle"
            onClick={() => setColorScheme(colorScheme === 'dark' ? 'light' : 'dark')}
            aria-label="toggle color scheme"
          >
            <Text size="xs">{colorScheme === 'dark' ? '亮' : '暗'}</Text>
          </ActionIcon>
        </Tooltip>
        <Text size="sm">
          {user?.username}
          <Text span c="dimmed" size="xs">
            {' '}
            · {user?.role}
          </Text>
        </Text>
        <Text
          size="sm"
          c="teal"
          style={{ cursor: 'pointer' }}
          onClick={() => logout.mutate(undefined, { onSuccess: () => (window.location.href = '/login') })}
        >
          退出
        </Text>
      </Group>
    </Group>
  )
}
