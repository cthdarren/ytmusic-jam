import { fireEvent, render, screen, within } from '@testing-library/react'
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

describe('QueueDrawer', () => {
  const items = [item('a', 'First'), item('b', 'Second'), item('c', 'Third')]

  it('renders the queue in order', () => {
    render(<QueueDrawer open items={items} onClose={() => {}} onRemove={() => {}} onMove={() => {}} />)
    const rows = screen.getAllByRole('listitem')
    expect(rows.map((r) => within(r).getByText(/First|Second|Third/).textContent)).toEqual(['First', 'Second', 'Third'])
  })

  it('removes an item by id', () => {
    const onRemove = vi.fn()
    render(<QueueDrawer open items={items} onClose={() => {}} onRemove={onRemove} onMove={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Remove Second' }))
    expect(onRemove).toHaveBeenCalledWith('b')
  })

  it('shows an empty message', () => {
    render(<QueueDrawer open items={[]} onClose={() => {}} onRemove={() => {}} onMove={() => {}} />)
    expect(screen.getByText(/queue is empty/i)).toBeInTheDocument()
  })
})
