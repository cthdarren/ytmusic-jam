import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useEffect, useState } from 'react'
import type { QueueItem } from '../types'
import { TrackInfo } from './TrackInfo'

/** Turn a drag from `activeId` onto `overId` into a move request, or null if nothing moves. */
export function reorder(ids: string[], activeId: string, overId: string): { id: string; toIndex: number } | null {
  if (activeId === overId) return null
  const toIndex = ids.indexOf(overId)
  if (toIndex === -1 || !ids.includes(activeId)) return null
  return { id: activeId, toIndex }
}

interface Props {
  open: boolean
  items: QueueItem[]
  onClose: () => void
  onRemove: (id: string) => void
  onMove: (id: string, toIndex: number) => void
}

export function QueueDrawer({ open, items, onClose, onRemove, onMove }: Props) {
  // Show a dropped item in its new spot immediately; the next broadcast replaces this.
  const [pendingOrder, setPendingOrder] = useState<string[] | null>(null)
  useEffect(() => setPendingOrder(null), [items])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 120, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  if (!open) return null

  const byId = new Map(items.map((i) => [i.id, i]))
  const ids = (pendingOrder ?? items.map((i) => i.id)).filter((id) => byId.has(id))

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over) return
    const move = reorder(ids, String(active.id), String(over.id))
    if (!move) return
    setPendingOrder(arrayMove(ids, ids.indexOf(move.id), move.toIndex))
    onMove(move.id, move.toIndex)
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <section className="drawer" role="dialog" aria-label="Queue" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-header">
          <h2>Up next</h2>
          <span className="muted">{items.length} {items.length === 1 ? 'song' : 'songs'}</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close queue">✕</button>
        </header>
        {items.length === 0 ? (
          <p className="empty">The queue is empty. Search for a song or paste a link to add one.</p>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext items={ids} strategy={verticalListSortingStrategy}>
              <ul className="queue-list">
                {ids.map((id) => (
                  <SortableRow key={id} item={byId.get(id)!} onRemove={onRemove} />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
        )}
      </section>
    </div>
  )
}

function SortableRow({ item, onRemove }: { item: QueueItem; onRemove: (id: string) => void }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: item.id,
  })
  return (
    <li
      ref={setNodeRef}
      className={`queue-row${isDragging ? ' dragging' : ''}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <button
        ref={setActivatorNodeRef}
        className="drag-handle"
        aria-label={`Drag ${item.track.title}`}
        {...attributes}
        {...listeners}
      >
        ⠿
      </button>
      <TrackInfo track={item.track} addedBy={item.added_by} />
      <button className="icon-btn" aria-label={`Remove ${item.track.title}`} onClick={() => onRemove(item.id)}>
        ✕
      </button>
    </li>
  )
}
