import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { QueueItem } from '../types'
import { QueueDrawer, reorder } from './QueueDrawer'

const item = (id: string, title: string): QueueItem => ({
  id,
  added_by: 'Sam',
  track: { video_id: `${id}xxxxxxxxxx`.slice(0, 11), title, artist: 'Artist', duration_seconds: 200, thumbnail_url: null },
})

describe('reorder', () => {
  it('moves the dragged item to the drop target index', () => {
    expect(reorder(['a', 'b', 'c'], 'c', 'a')).toEqual({ id: 'c', toIndex: 0 })
    expect(reorder(['a', 'b', 'c'], 'a', 'c')).toEqual({ id: 'a', toIndex: 2 })
  })

  it('returns null when dropped on itself or outside the list', () => {
    expect(reorder(['a', 'b'], 'a', 'a')).toBeNull()
    expect(reorder(['a', 'b'], 'a', 'zzz')).toBeNull()
  })
})

type DrawerProps = Parameters<typeof QueueDrawer>[0]

function renderDrawer(overrides: Partial<DrawerProps> = {}) {
  const props: DrawerProps = {
    open: true,
    played: [],
    nowPlaying: null,
    items: [],
    isOwner: false,
    onClose: vi.fn(),
    onRemove: vi.fn(),
    onMove: vi.fn(),
    onPlay: vi.fn(),
    onClear: vi.fn(),
    ...overrides,
  }
  render(<QueueDrawer {...props} />)
  return props
}

const titles = () =>
  screen.getAllByRole('listitem').map((row) => row.querySelector('.track-title')?.textContent)

describe('QueueDrawer', () => {
  const night = {
    played: [item('p1', 'P1'), item('p2', 'P2')],
    nowPlaying: item('n', 'N'),
    items: [item('u1', 'U1'), item('u2', 'U2')],
  }

  it('renders the whole night in order', () => {
    renderDrawer(night)
    expect(titles()).toEqual(['P1', 'P2', 'N', 'U1', 'U2'])
    const current = screen.getAllByRole('listitem')[2]
    expect(current).toHaveAttribute('aria-current', 'true')
    expect(within(current).getByText(/now playing/i)).toBeInTheDocument()
  })

  it('tapping a played song plays it', () => {
    const { onPlay } = renderDrawer(night)
    fireEvent.click(screen.getByRole('button', { name: 'Play P1' }))
    expect(onPlay).toHaveBeenCalledWith('p1')
  })

  it('tapping an upcoming song plays it', () => {
    const { onPlay } = renderDrawer(night)
    fireEvent.click(screen.getByRole('button', { name: 'Play U2' }))
    expect(onPlay).toHaveBeenCalledWith('u2')
  })

  it('tapping the now-playing row does nothing', () => {
    renderDrawer(night)
    expect(screen.queryByRole('button', { name: 'Play N' })).toBeNull()
  })

  it('removes an upcoming item by id', () => {
    const { onRemove } = renderDrawer(night)
    fireEvent.click(screen.getByRole('button', { name: 'Remove U1' }))
    expect(onRemove).toHaveBeenCalledWith('u1')
    expect(screen.queryByRole('button', { name: 'Remove P1' })).toBeNull()
  })

  it('scrolls the now-playing row into view on open', () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    renderDrawer(night)
    expect(scroll).toHaveBeenCalledWith({ block: 'center' })
  })

  it('only the owner sees Clear queue', () => {
    renderDrawer(night)
    expect(screen.queryByRole('button', { name: 'Clear queue' })).toBeNull()
    cleanup()
    renderDrawer({ ...night, isOwner: true })
    expect(screen.getByRole('button', { name: 'Clear queue' })).toBeInTheDocument()
  })

  it('Clear asks for confirmation', () => {
    const { onClear } = renderDrawer({ ...night, isOwner: true })
    fireEvent.click(screen.getByRole('button', { name: 'Clear queue' }))
    const dialog = screen.getByRole('alertdialog')
    expect(within(dialog).getByText('Clear the whole queue?')).toBeInTheDocument()
    expect(
      within(dialog).getByText("This removes every song from tonight's list, including the one playing now. This can't be undone."),
    ).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(onClear).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Clear queue' }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear everything' }))
    expect(onClear).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('shows the empty message when the night is empty', () => {
    renderDrawer({ isOwner: true })
    expect(screen.getByText(/queue is empty/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear queue' })).toBeNull()
  })
})
