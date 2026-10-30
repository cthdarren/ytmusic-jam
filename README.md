# YT Music Jam

A self-hosted jam for YouTube Music. One device plays the music, and everyone else
uses their phone to search, paste links and shuffle the shared queue around.

- **Search** YouTube Music for songs or videos and tap **+** to queue them.
- **Paste a link** (`music.youtube.com`, `youtube.com`, `youtu.be`, shorts) into the
  same box to add it straight to the queue. **Spotify song links** work too: the app
  finds the same song on YouTube Music (matching title, artist and length) and the
  confirmation names the song it picked. Albums and playlists aren't supported.
- The browser tab title shows the song playing as `title - artist`, so desktop
  widgets (e.g. waybar) can display it.
- **Queue** button: the whole night in one list, with played songs dimmed above the
  one playing now. Tap any song to jump to it; playback carries on down the list from
  there. Drag any song (played, playing or upcoming) to reorder the night: the song
  playing keeps playing, songs above it count as played and songs below it come up
  next. ✕ removes a song (skip the one playing instead).
- **Clear queue** (host only): wipes the night's list after a confirmation. The list
  is saved in `./data`, so it survives restarts (it comes back paused) and only this
  button clears it.
- **Invite** (host only): shows a QR code and link. Friends who open it join without
  a password. **Reset link** makes a new one and kicks everyone who used the old one.

## Run it

```sh
cp .env.example .env
# edit .env: set JAM_PASSWORD, and JAM_SECRET from `openssl rand -hex 32`
docker compose up -d --build
```

Open `http://<server-ip>:8000` (e.g. `http://192.168.66.66:8000`, or the server's
Tailscale address) and sign in with the username and password from `.env`.

`./data` holds the invite token and tonight's song list, so both survive restarts.
After a restart the music comes back paused; press play to carry on.

To update after pulling changes: `docker compose up -d --build`.

## Playing music

Open **Open player** (`/host`) on the device connected to your speakers and press
**Start jam**. Only that page makes sound; every other page is a remote control.

The server fetches each song's audio with [yt-dlp](https://github.com/yt-dlp/yt-dlp)
and the player page plays it. Only audio is downloaded, so it uses far less bandwidth
than video and there are no ads. Songs that labels block from playing outside
YouTube (common with official "Topic" audio tracks) work too. The current and next
upcoming songs (20 by default, `JAM_PRELOAD_SONGS`) are downloaded ahead of time so
skips and jumps start straight away. The song playing and the next one always
download first, on their own; the rest follow 4 at a time (`JAM_PRELOAD_WORKERS`).
When someone skips or taps a song, other downloads pause until the new playing and
next songs are ready, then resume where they left off. YouTube paces downloads
(roughly 10–15 s per song), so right after adding a batch of songs (or restarting)
give it a minute or two; the queue marks songs that are ready to play instantly. The first song after a quiet
spell can take a few seconds to start.

### Use your YouTube Premium account (recommended)

Without cookies the server fetches songs anonymously, which works but gets standard
quality (~128 kbps). With your account's cookies it plays as you: Premium's higher
quality audio (~256 kbps) and anything only your account can play.

1. Open a **private/incognito window**, sign in at <https://music.youtube.com>.
2. Export cookies for youtube.com with a "cookies.txt" export extension (for example
   *Get cookies.txt LOCALLY*), in Netscape format.
3. Save the file on the server as `./data/cookies.txt`, then **close the private
   window** without signing out (signing out invalidates the cookies).

No restart is needed. When the cookies eventually expire, repeat these steps. Treat
the file like a password: anyone with it can use your YouTube account.

Fetching audio this way is not how YouTube intends its content to be used and runs
under your account. Accounts being flagged for it are rare, but it is your call.

### When songs stop playing

YouTube changes things often and yt-dlp catches up within days. Rebuilding the image
installs the newest yt-dlp:

```sh
docker compose build --no-cache && docker compose up -d
```

Downloaded songs are short-term: they live in `./data/audio-cache` (500 MB by
default, set `JAM_AUDIO_CACHE_MB`), the least recently played are deleted first,
anything unused for a day is deleted, and **Clear queue** empties it.

### Lyrics in the tab title

While a song plays, the player page's tab title shows the line being sung, e.g.
`Violeta  -  IZ*ONE  |  <current line>`, so a status bar like waybar can show it.
Paused, or with no timed lyrics for the song, it's just `Violeta - IZ*ONE`. Lyrics come
from YouTube Music, or from [LRCLIB](https://lrclib.net) when YouTube Music has no
timed ones. Set `JAM_LYRICS=false` to turn this off.

## Telegram bot (optional)

Friends can queue songs by sending a YouTube or Spotify link to a Telegram bot (on a
phone: Share → Telegram → the bot, straight from the YouTube or Spotify app).

1. In Telegram, message **@BotFather**, send `/newbot` and follow the steps.
2. Put the token it gives you in `.env` as `JAM_TELEGRAM_TOKEN=…`, then
   `docker compose up -d`. The bot only makes outgoing connections, so nothing needs
   to be opened on your router.
3. Friends join with the invite: open **Invite**, switch it to **Telegram** and let
   them scan the QR code (it opens the bot in Telegram), or they can send the bot the
   invite link. After that, any link they send is queued and the bot replies with the
   song it added.

In group chats use `/add <link>`, or turn off the bot's privacy mode in @BotFather
(`/setprivacy`) so it sees links posted normally. **Reset link** signs Telegram users
out too; they rejoin with the new invite.

## Security notes

- Anyone with the invite link can control the queue. Reset it to revoke access.
- Five wrong passwords from one device locks login for that device for a minute.
- The app is plain HTTP, which is fine on your LAN or Tailscale. If you expose it to
  the internet, put it behind an HTTPS reverse proxy (forward WebSocket upgrades on
  `/ws`) and set `JAM_COOKIE_SECURE=true`.

## Development

```sh
# backend (http://localhost:8000)
cd backend
JAM_USERNAME=me JAM_PASSWORD=pw JAM_SECRET=dev JAM_DATA_DIR=./data \
  uv run uvicorn --factory app.main:create_app --reload --host 0.0.0.0
uv run pytest

# frontend (http://localhost:5173, proxies /api, /join and /ws to the backend)
cd frontend
npm install
npm run dev -- --host
npm test
```
