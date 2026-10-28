# YT Music Jam

A self-hosted jam for YouTube Music. One device plays the music, and everyone else
uses their phone to search, paste links and shuffle the shared queue around.

- **Search** YouTube Music for songs or videos and tap **+** to queue them.
- **Paste a link** (`music.youtube.com`, `youtube.com`, `youtu.be`, shorts) into the
  same box to add it straight to the queue.
- **Queue** button: see what's up next, drag to reorder, ✕ to remove.
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

`./data` holds the current invite token so invite links survive restarts. The queue
itself lives in memory and is cleared when the container restarts.

To update after pulling changes: `docker compose up -d --build`.

## Playing music

Open **Open player** (`/host`) on the device connected to your speakers and press
**Start jam**. Only that page makes sound; every other page is a remote control.

**No ads:** the player is YouTube's own embed, so YouTube Premium applies when that
browser is signed into your Premium Google account. Use Chrome: browsers that block
third-party cookies (Safari, Brave, Firefox strict mode) hide your sign-in from the
embed and you'll get ads.

Some videos have embedding turned off by the uploader. The player skips those
automatically.

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
