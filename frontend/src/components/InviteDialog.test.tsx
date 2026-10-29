import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import { InviteDialog } from './InviteDialog'

vi.mock('qrcode', () => ({ default: { toCanvas: vi.fn().mockResolvedValue(undefined) } }))
vi.mock('../api', () => ({ getJoinUrl: vi.fn(), resetJoinUrl: vi.fn() }))

describe('InviteDialog', () => {
  beforeEach(() => vi.mocked(api.getJoinUrl).mockReset())

  it('lets the host switch the QR and link to the Telegram bot for friends to scan', async () => {
    vi.mocked(api.getJoinUrl).mockResolvedValue({
      url: 'http://192.168.66.66:8000/join/abc',
      telegram_url: 'https://t.me/jam_bot?start=abc',
    })
    render(<InviteDialog onClose={() => {}} onError={() => {}} />)
    expect(await screen.findByDisplayValue('http://192.168.66.66:8000/join/abc')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Telegram' }))
    expect(screen.getByDisplayValue('https://t.me/jam_bot?start=abc')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open in telegram/i })).toHaveAttribute('href', 'https://t.me/jam_bot?start=abc')
    fireEvent.click(screen.getByRole('tab', { name: 'Web' }))
    expect(screen.getByDisplayValue('http://192.168.66.66:8000/join/abc')).toBeInTheDocument()
  })

  it('has no Telegram link without the bot', async () => {
    vi.mocked(api.getJoinUrl).mockResolvedValue({ url: 'http://192.168.66.66:8000/join/abc' })
    render(<InviteDialog onClose={() => {}} onError={() => {}} />)
    expect(await screen.findByDisplayValue('http://192.168.66.66:8000/join/abc')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Telegram' })).toBeNull()
    expect(screen.queryByRole('link', { name: /open in telegram/i })).toBeNull()
  })
})
