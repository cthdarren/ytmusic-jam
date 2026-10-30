# Lyrics in the Tab Title Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **First step when executing:** copy this file to `docs/superpowers/plans/2026-10-30-lyrics-in-title.md` and commit it with Task 1.

**Goal:** While a song plays, the `/host` tab's title shows the line being sung, so waybar shows it: `{{title}}  -  {{artist}}  |  {{lyric line}}`. An env var turns this off.

**Architecture:** The backend gets a new `GET /api/lyrics/{video_id}` endpoint. It returns timed lines from YouTube Music (ytmusicapi `get_lyrics(..., timestamps=True)`), or from lrclib.net when YouTube Music has none, and caches the result in memory. `HostPlayer` fetches the lines for the current song. On each `timeupdate` of its `<audio>` it reports the current line to `App`, which builds `document.title` with `pageTitle()`. Guest tabs never render `HostPlayer`, so their title doesn't change.

**Tech Stack:** FastAPI + pydantic, ytmusicapi 1.12.3, urllib (same as `app/spotify.py`), pytest; React + TypeScript, vitest + Testing Library.

**Spec:** the user's request in this session, plus their answers:
- Lyrics show only in the host tab. Guest tabs keep `title - artist`.
- Sources: YouTube Music timed lyrics first, then LRCLIB.
- With a lyric line: `Violeta  -  IZ*ONE  |  some line` (two spaces on each side of `-` and `|`).
- With no line, the title is `Violeta - IZ*ONE` (single spaces, same as today). That covers: paused, before the first line, no synced lyrics found, and lyrics turned off.
- In a gap between lines, keep showing the last line until the next one starts.
- A `JAM_LYRICS` env var turns the feature off. It is on by default.

## Global Constraints

- Title with a line: `` `${title}  -  ${artist}  |  ${line}` ``. With no artist: `` `${title}  |  ${line}` ``.
- Title with no line: unchanged from today (`` `${title} - ${artist}` ``, or `title` alone, or `YT Music Jam` when nothing is playing).
- `JAM_LYRICS`: on unless set to `0`, `false`, `no` or `off` (case-insensitive). When off, `/api/lyrics/...` returns `{"lines": []}` and looks nothing up.
- Only unsynced lyrics found means no lyrics. The title only ever shows timed lines.
- Lyrics never break playback or show an error toast. Any failure means no line.
- `frontend/src/types.ts` mirrors `backend/app/models.py`, so field names must be identical (`start_ms`, `text`, `lines`).
- Tests never touch the network. The real LRCLIB fetcher is swapped out in `backend/tests/conftest.py`, the same way `ytdlp_download` is.

## Review Focus

1. **Lyrics for the old song arriving after a skip.** The new song must never show the previous song's lines. Tested in Task 4 (`ignores lyrics that arrive for a song that is no longer playing`).
2. **YouTube Music or LRCLIB is down.** You get no line, and the failure isn't cached, so the next request tries again. Tested in Task 1 (`test_finder_does_not_cache_failures`).
3. **Song with unknown duration** (`duration_seconds=None`). LRCLIB matching must still accept a result. Tested in Task 1 (`test_lrclib_accepts_any_duration_when_unknown`).
4. **Seeking backwards.** The line follows the playback position, not "the last line shown". Tested in Task 3 (`currentLine` before/between/after cases) and Task 4 (seek back).
5. **Messy LRC.** Metadata tags (`[ar:...]`), blank lines, several timestamps on one line, and out-of-order lines. Tested in Task 1 (`test_parse_lrc_*`).

---

### Task 1: Backend lyrics lookup

**Files:**
- Modify: `backend/app/models.py` (add `LyricLine`, `Lyrics`)
- Modify: `backend/app/ytm.py` (add `YTMClient.get_synced_lyrics`)
- Create: `backend/app/lyrics.py`
- Test: `backend/tests/test_lyrics.py`, `backend/tests/test_ytm.py`

**Interfaces:**
- Produces:
  - `class LyricLine(BaseModel): start_ms: int; text: str`
  - `class Lyrics(BaseModel): lines: list[LyricLine]`
  - `YTMClient.get_synced_lyrics(video_id: str) -> list[LyricLine]`. Blocking. Returns `[]` when there's no lyrics browseId or the lyrics have no timestamps. Raises `UpstreamError` when ytmusicapi raises.
  - `app.lyrics.parse_lrc(text: str) -> list[LyricLine]`
  - `app.lyrics.fetch_lrclib(title: str, artist: str, duration_seconds: int | None) -> list[LyricLine]`. Blocking. Returns `[]` when nothing matches. Raises `UpstreamError` on network or HTTP errors.
  - `class LyricsFinder(ytm, lrclib: Callable[[str, str, int | None], list[LyricLine]], max_cached: int = 200)` with `find(track: Track) -> list[LyricLine]`. Blocking. Never raises.

- [ ] **Step 1: Write the failing tests**

In `test_ytm.py`, extend `FakeYT` with `get_watch_playlist(videoId, limit=...)`, which returns `{"lyrics": browse_id_or_None}`, and `get_lyrics(browseId, timestamps=True)`. The fake returns an object with the real shape. Build it with `ytmusicapi.models.lyrics.LyricLine(text, start_time, end_time, id)` inside a `TimedLyrics`/dict with `hasTimestamps`. Check `ytmusicapi/models/lyrics.py` for the exact constructor.
- `test_synced_lyrics_from_timestamps`: lines `("Hello", 9200)` and `("World", 10680)` → `[LyricLine(start_ms=9200, text="Hello"), LyricLine(start_ms=10680, text="World")]`.
- `test_synced_lyrics_none_without_browse_id`: `lyrics: None` → `[]`. `get_lyrics` is never called.
- `test_synced_lyrics_ignores_unsynced`: `hasTimestamps: False` → `[]`.
- `test_synced_lyrics_wraps_errors`: the fake raises → `UpstreamError`.

In `test_lyrics.py`:
- `test_parse_lrc_basic`: `"[00:12.34] Hello\n[01:02.5]World"` → `[(12340, "Hello"), (62500, "World")]`.
- `test_parse_lrc_skips_tags_and_blank_lines`: `"[ar:X]\n[ti:Y]\n[00:01.00]\n[00:02.00]  Hi  "` → `[(2000, "Hi")]`.
- `test_parse_lrc_multiple_stamps_and_sorting`: `"[00:30.00][00:10.00]Chorus\n[00:20.00]Verse"` → `[(10000,"Chorus"),(20000,"Verse"),(30000,"Chorus")]`.
- `test_lrclib_picks_synced_result_with_close_duration`: monkeypatch `app.lyrics.urllib.request.urlopen` (pattern: `tests/test_spotify.py:130-145`) to return a JSON list. The first item has `syncedLyrics: None`. The second has `duration: 300` (too far from 200). The third has `duration: 201.4` and LRC text. Expect the third's lines. Also assert the request URL hits `https://lrclib.net/api/search` with `track_name` and `artist_name` params.
- `test_lrclib_accepts_any_duration_when_unknown`: `duration_seconds=None` → the first synced result is used.
- `test_lrclib_uses_first_artist`: `artist="A, B"` → the request's `artist_name=A`.
- `test_lrclib_errors_raise_upstream`: urlopen raises `OSError` → `UpstreamError`.
- `test_finder_prefers_ytm`: a fake ytm returns lines → the result is those lines, and the lrclib fake is not called.
- `test_finder_falls_back_to_lrclib`: ytm returns `[]` → the lrclib fake is called with `(title, artist, duration_seconds)`, and its lines are returned.
- `test_finder_falls_back_when_ytm_errors`: ytm raises `UpstreamError` → lrclib's lines are returned.
- `test_finder_caches_results`: calling `find` twice for the same video id → each source is called once. A "nothing found" `[]` result is cached too.
- `test_finder_does_not_cache_failures`: lrclib raises `UpstreamError` and ytm returns `[]` → `find` returns `[]`. Make lrclib succeed and call `find` again → lines are returned.

- [ ] **Step 2: Run the tests to check they fail**

Run: `cd backend && uv run pytest tests/test_lyrics.py tests/test_ytm.py -q`
Expected: FAIL (ImportError for `app.lyrics`, AttributeError for `get_synced_lyrics`).

- [ ] **Step 3: Implement**

- `get_synced_lyrics`: call `self.yt.get_watch_playlist(videoId=video_id, limit=1)` and read the `"lyrics"` key. If there's a browseId, call `self.yt.get_lyrics(browse_id, timestamps=True)`. When `hasTimestamps` is true, map each line to `LyricLine(start_ms=l.start_time, text=l.text.strip())` and drop empty texts. Wrap ytmusicapi exceptions in `UpstreamError`, like `search` does.
- `parse_lrc`: regex `\[(\d+):(\d+(?:\.\d+)?)\]`. Collect all leading stamps on a line, then the text is the rest, stripped. Skip lines with no stamps (this also drops metadata tags like `[ar:..]`) and lines with empty text. Sort by `start_ms`.
- `fetch_lrclib`: `GET https://lrclib.net/api/search?track_name=…&artist_name=…` with header `User-Agent: YT Music Jam (self-hosted)`, `timeout=10`. Map errors the same way `fetch_spotify_track` does in `app/spotify.py:79-92`, except a 404 means `[]`. Pick the first item with a truthy `syncedLyrics` and, when the duration is known, `abs(item["duration"] - duration_seconds) <= 3`. Return `parse_lrc` of it.
- `LyricsFinder.find`: `ytm.get_synced_lyrics`, then `lrclib(...)` if that came back empty. Catch `UpstreamError` from each source and log it at `info`. Cache by `video_id` in an `OrderedDict` with LRU eviction at `max_cached`, but only when neither source raised.

- [ ] **Step 4: Run the tests to check they pass**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-10-30-lyrics-in-title.md backend/app/models.py backend/app/ytm.py backend/app/lyrics.py backend/tests/test_lyrics.py backend/tests/test_ytm.py
git commit -m "feat(backend): look up timed lyrics from YouTube Music, then LRCLIB"
```

---

### Task 2: Lyrics endpoint and the `JAM_LYRICS` switch

**Files:**
- Modify: `backend/app/settings.py` (`lyrics: bool = True`, read from `JAM_LYRICS`)
- Modify: `backend/app/main.py` (import `LyricsFinder, fetch_lrclib`; build `LyricsFinder(ytm, lrclib=fetch_lrclib)` in `create_app`; add the route on the `api` router)
- Modify: `backend/tests/conftest.py`: `FakeYTM.get_synced_lyrics` returns `[LyricLine(start_ms=1000, text=f"la {video_id}")]`, except `"nolyrics000"` returns `[]`. Add an autouse fixture that monkeypatches `app.main.fetch_lrclib` with a fake returning `[]`, which records its calls.
- Modify: `.env.example`, `README.md` (a short "Lyrics in the tab title" section near "Playing music")
- Test: `backend/tests/test_api.py`, plus a settings test next to any existing `from_env` tests (`grep -rn from_env backend/tests`)

**Interfaces:**
- Consumes: `LyricsFinder.find`, `Lyrics`, `LyricLine` (Task 1).
- Produces: `GET /api/lyrics/{video_id}` → `{"lines": [{"start_ms": int, "text": str}, ...]}`. Needs a session (it's on the `api` router). Returns 400 if `video_id` fails `VIDEO_ID_RE`, and 404 `"That song isn't in the jam"` if no played, now-playing or queued item has that video id.

- [ ] **Step 1: Write the failing tests**
- `test_lyrics_for_song_in_jam`: add `ID` via link, GET `/api/lyrics/{ID}` → 200, `{"lines": [{"start_ms": 1000, "text": f"la {ID}"}]}`.
- `test_lyrics_unknown_song_404` and `test_lyrics_bad_id_400`.
- `test_lyrics_needs_login`: `anon_client` → 401.
- `test_lyrics_off`: build an app with `settings.lyrics = False` → `{"lines": []}`, and `FakeYTM` records no lyrics calls.
- `test_lyrics_setting_from_env`: `JAM_LYRICS` unset → `True`. `"false"`, `"0"`, `"OFF"` → `False`. `"true"` → `True`.

- [ ] **Step 2: Run them to check they fail**

Run: `cd backend && uv run pytest tests/test_api.py -q -k lyrics`
Expected: FAIL (404 for the unknown route / no `lyrics` attribute).

- [ ] **Step 3: Implement**

The route finds the `Track` in `room.snapshot()` (played + now_playing + queue). Then it returns `Lyrics(lines=await run_in_threadpool(finder.find, track))`, or `Lyrics(lines=[])` when `settings.lyrics` is off. In `.env.example`, add:

```
# Show the line being sung in the host tab's title (e.g. for waybar). Set to false to turn off.
JAM_LYRICS=true
```

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**: `feat(backend): /api/lyrics endpoint, JAM_LYRICS to turn it off`

---

### Task 3: Frontend lyric helpers and title format

**Files:**
- Modify: `frontend/src/types.ts` (add `LyricLine { start_ms: number; text: string }` and `Lyrics { lines: LyricLine[] }`)
- Modify: `frontend/src/api.ts` (`export const getLyrics = (videoId: string) => request<Lyrics>(`/api/lyrics/${videoId}`)`)
- Create: `frontend/src/lyrics.ts`, `frontend/src/lyrics.test.ts`
- Modify: `frontend/src/pageTitle.ts`, `frontend/src/pageTitle.test.ts`

**Interfaces:**
- Produces:
  - `currentLine(lines: LyricLine[], positionMs: number): string | null` returns the text of the last line with `start_ms <= positionMs`, or `null` before the first line or when there are no lines. Lines arrive sorted.
  - `pageTitle(nowPlaying: QueueItem | null, lyric?: string | null): string`
  - `getLyrics(videoId: string): Promise<Lyrics>`

- [ ] **Step 1: Write the failing tests**

`lyrics.test.ts`, with lines `[{start_ms:5000,text:'A'},{start_ms:8000,text:'B'}]`:
- `currentLine(lines, 4999)` → `null`
- `currentLine(lines, 5000)` → `'A'`
- `currentLine(lines, 7999)` → `'A'` (a gap keeps the last line)
- `currentLine(lines, 60000)` → `'B'`
- `currentLine([], 1000)` → `null`

`pageTitle.test.ts`, keeping the existing three tests unchanged, plus:
- `pageTitle(item('비올레타 Violeta','IZ*ONE'), '꿈을 꾸는 듯해')` → `'비올레타 Violeta  -  IZ*ONE  |  꿈을 꾸는 듯해'`
- `pageTitle(item('Some Video',''), 'la la')` → `'Some Video  |  la la'`
- `pageTitle(item('X','Y'), null)` and `pageTitle(item('X','Y'), '')` → `'X - Y'`
- `pageTitle(null, 'stray')` → `'YT Music Jam'`

- [ ] **Step 2: Run them to check they fail**: `cd frontend && npm test -- lyrics pageTitle`. Expected: FAIL.

- [ ] **Step 3: Implement** `currentLine` and the `lyric` parameter. Update the `pageTitle` doc comment to describe both formats.

- [ ] **Step 4: Run them to check they pass**: `cd frontend && npm test`. Expected: all pass.

- [ ] **Step 5: Commit**: `feat(frontend): lyric line helpers and "title  -  artist  |  line" format`

---

### Task 4: Host tab follows the lyrics

**Files:**
- Modify: `frontend/src/components/HostPlayer.tsx`
- Modify: `frontend/src/App.tsx` (`const [lyric, setLyric] = useState<string | null>(null)`; `pageTitle(state?.now_playing ?? null, isHost ? lyric : null)`; `<HostPlayer ... onLyric={setLyric} />`)
- Create: `frontend/src/components/HostPlayer.test.tsx`

**Interfaces:**
- Consumes: `getLyrics`, `currentLine`, `pageTitle(item, lyric)` (Task 3).
- Produces: a new `HostPlayer` prop, `onLyric: (line: string | null) => void`.

- [ ] **Step 1: Write the failing tests** (`HostPlayer.test.tsx`)

Stub `fetch` with `vi.stubGlobal` (pattern: `api.test.ts:21-33`). It answers `/api/lyrics/<id>` with lines `[{start_ms:1000,text:'first'},{start_ms:5000,text:'second'}]`. Render `<HostPlayer state={...now_playing item, is_playing:true} onError={vi.fn()} onLyric={onLyric} />` and don't tap "Start jam" (jsdom can't `play()`). Get the `<audio>` with `container.querySelector('audio')`. Set position and pause state with `Object.defineProperty(audio, 'currentTime' | 'paused', { value, configurable: true })`, then `fireEvent.timeUpdate(audio)` / `fireEvent.pause(audio)`. Wait for the lyrics fetch with `waitFor`.
- `reports the line being sung`: paused=false, t=6s → `onLyric` last called with `'second'`.
- `follows a seek back`: then t=2s → `'first'`.
- `reports no line while paused`: `fireEvent.pause` → `null`. A `timeUpdate` while `paused=true` → `null`.
- `reports no line before the first line`: t=0.5s → `null`.
- `ignores lyrics that arrive for a song that is no longer playing`: make the fetch for song A hang. Rerender with song B, whose fetch returns `[]`. Then resolve A's fetch with lines. A `timeUpdate` at t=6s → `null`.

- [ ] **Step 2: Run them to check they fail**: `cd frontend && npm test -- HostPlayer`. Expected: FAIL (`onLyric` never called).

- [ ] **Step 3: Implement in `HostPlayer`**

- Keep `lyricsRef = useRef<{ videoId: string; lines: LyricLine[] } | null>(null)`.
- Add an effect on `videoId` that calls `onLyric(null)`, clears `lyricsRef`, and, if `videoId`, calls `getLyrics(videoId)`. On success it stores `{videoId, lines}`, unless the effect was cleaned up (use a `cancelled` flag). Failures are ignored.
- Add an `onTimeUpdate` handler on `<audio>`: `onLyric(audio.paused || lyricsRef.current?.videoId !== stateRef.current?.now_playing?.track.video_id ? null : currentLine(lyricsRef.current.lines, audio.currentTime * 1000))`.
- In the existing `onPause` handler, also call `onLyric(null)`.
- `App`'s `setLyric` is stable, and React skips re-renders when the string is unchanged, so `timeupdate` (about 4 times a second) needs no extra de-duplication.

- [ ] **Step 4: Verify**

Run: `cd frontend && npm test && npm run lint && npm run build`
Expected: all tests pass, no lint errors, and the build succeeds (the tsc type check covers the `App` wiring).

- [ ] **Step 5: Commit**: `feat(frontend): host tab title follows the song's lyrics`

---

## End-to-end verification

1. `cd backend && uv run pytest -q`, then `cd frontend && npm test && npm run lint && npm run build`. Everything should pass.
2. Run the backend and frontend dev servers (README "Development"). Log in, open `/host`, tap Start jam, and queue a well-known song (e.g. search "Violeta IZ*ONE"). Once singing starts, the tab title should read `비올레타 Violeta  -  IZ*ONE  |  <line>` and change line by line. Pause, and it should become `비올레타 Violeta - IZ*ONE`. Seek back, and the earlier line returns.
3. Open `/` in another tab. Its title stays `title - artist`.
4. Restart the backend with `JAM_LYRICS=false`. The host title stays `title - artist` while playing, and `curl -b <cookie> /api/lyrics/<id>` returns `{"lines":[]}`.
