import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import { InviteDialog } from './InviteDialog'

vi.mock('qrcode', () => ({ default: { toCanvas: vi.fn().mockResolvedValue(undefined) } }))
vi.mock('../api', () => ({ getJoinUrl: vi.fn(), resetJoinUrl: vi.fn() }))

describe('InviteDialog', () => {
  beforeEach(() => vi.mocked(api.getJoinUrl).mockReset())

  it('offers an Add on Telegram link when the bot is running', async () => {
    vi.mocked(api.getJoinUrl).mockResolvedValue({
      url: 'http://192.168.66.66:8000/join/abc',
      telegram_url: 'https://t.me/jam_bot?start=abc',
    })
    render(<InviteDialog onClose={() => {}} onError={() => {}} />)
    const link = await screen.findByRole('link', { name: /add on telegram/i })
    expect(link).toHaveAttribute('href', 'https://t.me/jam_bot?start=abc')
  })

  it('has no Telegram link without the bot', async () => {
    vi.mocked(api.getJoinUrl).mockResolvedValue({ url: 'http://192.168.66.66:8000/join/abc' })
    render(<InviteDialog onClose={() => {}} onError={() => {}} />)
    expect(await screen.findByDisplayValue('http://192.168.66.66:8000/join/abc')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /add on telegram/i })).toBeNull()
  })
})
