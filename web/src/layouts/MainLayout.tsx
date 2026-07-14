import { AppShell, Burger } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { Outlet } from 'react-router-dom'
import { AppNavbar } from '../components/AppNavbar'
import { AppTopbar } from '../components/AppTopbar'

export function MainLayout() {
  const [opened, { toggle }] = useDisclosure()

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <GroupHeader opened={opened} toggle={toggle} />
      </AppShell.Header>
      <AppShell.Navbar>
        <AppNavbar />
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}

function GroupHeader({ opened, toggle }: { opened: boolean; toggle: () => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', height: '100%' }}>
      <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" ml="md" />
      <div style={{ flex: 1 }}>
        <AppTopbar />
      </div>
    </div>
  )
}
