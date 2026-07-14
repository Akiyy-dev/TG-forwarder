import { NavLink, Stack, Text } from '@mantine/core'
import { Link, useLocation } from 'react-router-dom'

const items = [
  { label: '仪表盘', to: '/dashboard', enabled: true },
  { label: '审核队列', to: '/reviews', enabled: true },
  { label: '规则管理', to: '/rules', enabled: true },
  { label: '频道管理', to: '/channels', enabled: true },
  { label: '系统状态', to: '/system', enabled: false },
]

export function AppNavbar() {
  const location = useLocation()

  return (
    <Stack gap="xs" p="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        导航
      </Text>
      {items.map((item) =>
        item.enabled ? (
          <NavLink
            key={item.to}
            component={Link}
            to={item.to}
            label={item.label}
            active={location.pathname.startsWith(item.to)}
          />
        ) : (
          <NavLink
            key={item.to}
            label={item.label}
            disabled
            description="即将推出"
          />
        ),
      )}
    </Stack>
  )
}
