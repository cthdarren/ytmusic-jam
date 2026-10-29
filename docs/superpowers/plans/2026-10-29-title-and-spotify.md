# Page Title + Spotify Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- The page title shows the current song, so desktop widgets like waybar can read it.
- Pasting a Spotify track link queues the matching YouTube Music song.

**Architecture:**
- **Title:** a pure `pageTitle(nowPlaying)` in the frontend, applied with a `useEffect` in `Jam`.
- **Spotify:**
  - `backend/app/spotify.py` parses Spotify track links and reads `name`, `artists` and `duration` from the public embed page's `__NEXT_DATA__` JSON (no API keys).
  - `best_match()` ranks YouTube Music song results by title similarity, artist match and duration closeness.
  - `POST /api/queue` accepts Spotify links alongside YouTube links.
  - The frontend treats Spotify links as links and toasts the matched song.

**Spec (user):**
- "I want the title of the webpage to reflect the current song … The title of the page can follow this format {{title}} - {{artist}}"
- "I want to be able to paste a spotify link into the search bar as well and youtube will find the equivalent and add it to queue"
- Spike: `https://open.spotify.com/embed/track/4cOdK2wGLETKBW3PvgPWqT` gives `entity.name = "Never Gonna Give You Up"`, `artists = [Rick Astley]`, `duration = 213573` (ms). oEmbed has no artist, and the track page has no meta tags without JS.

## Global Constraints

- Title format: exactly `` `${title} - ${artist}` `` while a song is playing (paused counts). With nothing playing it is `YT Music Jam`.
- Spotify links accepted:
  - `https://open.spotify.com/track/{id}` (with optional `?si=…`)
  - `https://open.spotify.com/intl-xx/track/{id}`
  - `spotify:track:{id}`
  - `{id}` is 22 base62 characters.
- Albums, playlists and episodes get a 400: `"Only Spotify song links are supported (not albums or playlists)"`.
- Errors:
  - Spotify unreachable or the page format changed: 502 `"Couldn't read that Spotify link"`.
  - Track not found: 404.
  - No YouTube match: 404 `"Couldn't find that song on YouTube Music"`.
- Matching:
  - Search query `"{name} {first artist}"`, YouTube Music `songs` filter, 10 results.
  - Score = title similarity + artist similarity − duration penalty (0 within 3 s, growing to 1 at 30 s or more; neutral if a duration is unknown).
  - The best score wins. If every candidate scores below 0.6, there is no match.

## Review Focus

1. **Cover and live versions ranked above the original.** The original must win when its duration matches (`test_prefers_matching_duration_and_artist`).
2. **Featured artists and "(Remastered)" suffixes.** These must not sink the right song (`test_tolerates_feat_and_remaster_suffixes`).
3. **Spotify markup changes.** The user gets a readable 502, not a 500 (`test_parse_embed_page_missing_data_raises_upstream`).

---

### Task 1: Page title (frontend)

- [ ] Tests in `frontend/src/pageTitle.test.ts`: a playing song gives `Title - Artist`, nothing playing gives `YT Music Jam`, an empty artist gives just the title.
- [ ] Implement `pageTitle(nowPlaying: QueueItem | null): string` and apply it in `App.tsx` `Jam` (`useEffect` on the title and artist). The login screen keeps `YT Music Jam`.

### Task 2: Spotify link resolution (backend)

**Files:** create `backend/app/spotify.py` and `backend/tests/test_spotify.py`; modify `backend/app/main.py` and `backend/tests/test_api.py`.

**Interfaces:**
- `parse_spotify(text) -> str | None` returns the track id. `SpotifyNotATrack(ValueError)` is raised for album, playlist and episode links.
- `SpotifyTrack(name: str, artists: list[str], duration_ms: int | None)`
- `parse_embed_page(html) -> SpotifyTrack`, raising `UpstreamError` if the data is missing.
- `fetch_spotify_track(track_id) -> SpotifyTrack`, blocking, using urllib with a browser User-Agent and a 10 s timeout. It raises `LookupError` on a 404 and `UpstreamError` otherwise.
- `best_match(track: SpotifyTrack, candidates: list[Track]) -> Track | None`

- [ ] Tests:
  - `test_parses_spotify_track_links` (variants)
  - `test_rejects_non_track_spotify_links`
  - `test_parse_embed_page`
  - `test_parse_embed_page_missing_data_raises_upstream`
  - `test_prefers_matching_duration_and_artist`
  - `test_tolerates_feat_and_remaster_suffixes`
  - `test_no_good_match_returns_none`
  - API: `test_add_spotify_link_queues_best_match`, `test_add_spotify_album_link_400`, `test_add_spotify_no_match_404`
- [ ] Network smoke: resolve 3 real Spotify tracks end to end.

### Task 3: Frontend accepts Spotify links

- [ ] `isLink` is true for `open.spotify.com/` and `spotify:` links.
- [ ] After a link add, the toast names the added song: `` `Added “${title}” – ${artist}` `` (the last upcoming item, or now playing if the queue was empty).
- [ ] Tests: `isLink` cases and a `describeAdded(state)` pure helper.
- [ ] README: mention Spotify links.
