import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar'

function renderBar(role: 'owner' | 'guest', isHost = false) {
  const props = { role, nickname: 'Sam', isHost, onInvite: vi.fn(), onLogout: vi.fn() } as const
  render(<TopBar {...props} />)
  return props
}

describe('TopBar', () => {
  it('lets a guest log out after confirming', () => {
    const { onLogout } = renderBar('guest')
    expect(screen.getByText(/jamming as sam/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    const dialog = screen.getByRole('alertdialog')
    expect(within(dialog).getByText(/invite link or QR code/i)).toBeInTheDocument()
    expect(onLogout).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('a guest can cancel logging out', () => {
    const { onLogout } = renderBar('guest')
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onLogout).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('guests do not get host controls', () => {
    renderBar('guest')
    expect(screen.queryByRole('button', { name: 'Invite' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Open player' })).toBeNull()
  })

  it('the host logs out straight away and has host controls', () => {
    const { onLogout, onInvite } = renderBar('owner')
    fireEvent.click(screen.getByRole('button', { name: 'Invite' }))
    expect(onInvite).toHaveBeenCalled()
    expect(screen.getByRole('link', { name: 'Open player' })).toHaveAttribute('href', '/host')
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('hides Open player on the player page', () => {
    renderBar('owner', true)
    expect(screen.queryByRole('link', { name: 'Open player' })).toBeNull()
  })
})
