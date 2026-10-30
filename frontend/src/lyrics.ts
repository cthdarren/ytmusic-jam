import type { LyricLine } from './types'

/** The line being sung at `positionMs`: the last one to have started (lines are sorted), or null before the first. */
export function currentLine(lines: LyricLine[], positionMs: number): string | null {
  let line: string | null = null
  for (const l of lines) {
    if (l.start_ms > positionMs) break
    line = l.text
  }
  return line
}
