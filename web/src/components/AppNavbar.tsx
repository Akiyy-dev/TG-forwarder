import { NavLink, Stack, Text } from '@mantine/core'
import { Link, useLocation } from 'react-router-dom'

const items = [
  { label: '仪表盘', to: '/dashboard' },
  { label: '审核队列', to: '/reviews' },
  { label: '消息历史', to: '/history' },
  { label: '规则管理', to: '/rules' },
  { label: '频道管理', to: '/channels' },
  { label: '对外 API', to: '/api-endpoints' },
  { label: '设置', to: '/settings/basic' },
  { label: '系统状态', to: '/system' },
  { label: '系统日志', to: '/logs' },
]

const settingChildren = [
  { label: '基础', to: '/settings/basic' },
  { label: '监听与队列', to: '/settings/listener' },
  { label: '规则与处理器', to: '/settings/processors' },
  { label: '审核', to: '/settings/review' },
  { label: '历史落盘', to: '/settings/history' },
  { label: 'Web', to: '/settings/web' },
]

export function AppNavbar() {
  const location = useLocation()
  const inSettings = location.pathname.startsWith('/settings')

  return (
    <Stack gap="xs" p="md" className="app-navbar">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600} className="nav-section-label">
        导航
      </Text>
      {items.map((item) => (
        <NavLink
          key={item.to}
          component={Link}
          to={item.to}
          label={item.label}
          active={
            item.to.startsWith('/settings')
              ? inSettings
              : location.pathname.startsWith(item.to)
          }
          className="nav-link-item"
        />
      ))}
      {inSettings && (
        <Stack gap={4} pl="sm" mt={4}>
          {settingChildren.map((child) => (
            <NavLink
              key={child.to}
              component={Link}
              to={child.to}
              label={child.label}
              active={location.pathname === child.to}
              variant="subtle"
            />
          ))}
        </Stack>
      )}
    </Stack>
  )
}
