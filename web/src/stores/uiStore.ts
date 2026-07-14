import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UiState {
  navCollapsed: boolean
  setNavCollapsed: (value: boolean) => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      navCollapsed: false,
      setNavCollapsed: (value) => set({ navCollapsed: value }),
    }),
    { name: 'tgfw-ui' },
  ),
)
