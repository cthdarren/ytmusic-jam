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
import { useEffect, useRef, useState } from 'react'
import type { QueueItem } from '../types'
import { ConfirmDialog } from './ConfirmDialog'
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
  /** Songs already played tonight, oldest first. */
  played: QueueItem[]
  nowPlaying: QueueItem | null
  /** Upcoming songs; the only part that can be dragged or removed. */
  items: QueueItem[]
  isOwner: boolean
  onClose: () => void
  onRemove: (id: string) => void
  onMove: (id: string, toIndex: number) => void
  onPlay: (id: string) => void
  onClear: () => void
}

/** The whole night as one list: played songs, the current one, then the sortable upcoming queue. */
export function QueueDrawer({ open, played, nowPlaying, items, isOwner, onClose, onRemove, onMove, onPlay, onClear }: Props) {
  // Show a dropped item in its new spot immediately; it's dropped once a new `items` broadcast arrives.
  const [pending, setPending] = useState<{ basis: QueueItem[]; order: string[] } | null>(null)
  const [confirmingClear, setConfirmingClear] = useState(false)
  // The row to open on: the current song, or the last one played once the night has finished.
  const anchorRef = useRef<HTMLLIElement>(null)

  // Long nights: open on that row rather than the first song of the evening.
  useEffect(() => {
    if (open) anchorRef.current?.scrollIntoView?.({ block: 'center' })
  }, [open])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 120, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  if (!open) return null

  const byId = new Map(items.map((i) => [i.id, i]))
  const order = pending?.basis === items ? pending.order : items.map((i) => i.id)
  const ids = order.filter((id) => byId.has(id))
  const nightEmpty = played.length === 0 && nowPlaying === null && items.length === 0

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over) return
    const move = reorder(ids, String(active.id), String(over.id))
    if (!move) return
    setPending({ basis: items, order: arrayMove(ids, ids.indexOf(move.id), move.toIndex) })
    onMove(move.id, move.toIndex)
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <section className="drawer" role="dialog" aria-label="Queue" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-header">
          <h2>Tonight</h2>
          <span className="muted small">{items.length} up next</span>
          {isOwner && !nightEmpty ? (
            <button className="danger small-btn" onClick={() => setConfirmingClear(true)}>
              Clear queue
            </button>
          ) : null}
          <button className="icon-btn" onClick={onClose} aria-label="Close queue">✕</button>
        </header>
        {nightEmpty ? (
          <p className="empty">The queue is empty. Search for a song or paste a link to add one.</p>
        ) : (
          <ul className="queue-list">
            {played.map((item, index) => (
              <li
                key={item.id}
                ref={nowPlaying === null && index === played.length - 1 ? anchorRef : undefined}
                className="queue-row played"
              >
                <PlayButton item={item} onPlay={onPlay} />
              </li>
            ))}
            {nowPlaying ? (
              <li ref={anchorRef} className="queue-row current" aria-current="true">
                <TrackInfo track={nowPlaying.track} addedBy={nowPlaying.added_by} />
                <span className="badge">Now playing</span>
              </li>
            ) : null}
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext items={ids} strategy={verticalListSortingStrategy}>
                {ids.map((id) => (
                  <SortableRow key={id} item={byId.get(id)!} onRemove={onRemove} onPlay={onPlay} />
                ))}
              </SortableContext>
            </DndContext>
          </ul>
        )}
      </section>
      {confirmingClear ? (
        <ConfirmDialog
          title="Clear the whole queue?"
          message="This removes every song from tonight's list, including the one playing now. This can't be undone."
          confirmLabel="Clear everything"
          onCancel={() => setConfirmingClear(false)}
          onConfirm={() => {
            setConfirmingClear(false)
            onClear()
          }}
        />
      ) : null}
    </div>
  )
}

/** The tappable track area: jumps playback to this song. */
function PlayButton({ item, onPlay }: { item: QueueItem; onPlay: (id: string) => void }) {
  return (
    <button className="play-target" aria-label={`Play ${item.track.title}`} onClick={() => onPlay(item.id)}>
      <TrackInfo track={item.track} addedBy={item.added_by} />
    </button>
  )
}

function SortableRow({ item, onRemove, onPlay }: { item: QueueItem; onRemove: (id: string) => void; onPlay: (id: string) => void }) {
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
      <PlayButton item={item} onPlay={onPlay} />
      <button className="icon-btn" aria-label={`Remove ${item.track.title}`} onClick={() => onRemove(item.id)}>
        ✕
      </button>
    </li>
  )
}
