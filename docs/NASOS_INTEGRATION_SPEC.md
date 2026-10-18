# Spec: add Samedia to nasOS as an App Store add-on

**Audience:** a coding agent working in the nasOS repo (`github.com/rttgnck/nasOS`).
**Goal:** a nasOS user can install **Samedia Media Server** from the App Store with one click, open its
admin page from nasOS, and connect the Samedia Samsung TV app to it. The TV app and the server already
exist in the Samedia repo; this spec covers only the nasOS-side changes.

---

## 1. Background

### 1.1 What Samedia is

| Part | Where | Summary |
|---|---|---|
| TV app | `Samedia/tv/` | Tizen web app for Samsung TVs (Cover Flow library, AVPlay player, PGS/VTT subtitles) |
| Server | `Samedia/server/` | Python/FastAPI + ffmpeg in Docker. Scans media, serves files, converts DTS/TrueHD audio to E-AC3 on the fly (video is never re-encoded unless unavoidable) |
| Image | `ghcr.io/rttgnck/samedia-server:latest` | Multi-arch (arm64 + amd64), built by `Samedia/.github/workflows/server-image.yml` |

Container contract (do not change these from the nasOS side):

| Item | Value |
|---|---|
| Port | `8097/tcp`, used by both the HTTP API and the admin web UI at `/` |
| Config volume | `/config` (SQLite DB, artwork/subtitle cache, secret). The entrypoint chowns it to `PUID:PGID` (default `1000:1000`), so the host folder may be created by Docker as root |
| Media | Read-only bind mounts. The scan roots come from `SAMEDIA_MEDIA_ROOTS`, a colon-separated list of in-container paths |
| Health | `GET /healthz` → `{"ok": true}`. `GET /api/v1/info` → `{"app":"samedia", "name", "version", "api", "pin_required"}` |
| Env | `SAMEDIA_MEDIA_ROOTS`, `SAMEDIA_SERVER_NAME`, `SAMEDIA_PIN`, `SAMEDIA_TMDB_KEY`, `PUID`, `PGID` (all optional) |

The TV app finds the server by scanning its /24 subnet for `:8097/api/v1/info`, or the user types the NAS IP.

### 1.2 How nasOS add-ons work today

nasOS has no plugin system. "Add-ons" are entries in the Docker **App Store** catalog:

- `backend/app/services/docker_service.py`: `APP_CATALOG` (a list of dicts) and `install_app(app_id)`,
  which runs `docker pull` and then `docker run -d --name <id> --restart unless-stopped -p host:container -v ... <image>`.
  It supports only `ports` and `volumes`. There is no env, no labels, and no web-UI link.
- `backend/app/api/docker.py`: `GET /api/docker/catalog`, `POST /api/docker/install/{app_id}`, and the container actions.
- `frontend/src/apps/DockerManager/DockerManager.tsx`: the `CatalogView` grid with an Install button, and the `ContainersView`.
- Storage locations: shares under `/srv/nasos/shares` (default "Storage" share), and hot-plugged disks auto-mounted under `/mnt/<label>`.
- Firewall: `system/scripts/first-boot.sh` sets `ufw default deny incoming` and allows only 22/80/443/8080/SMB.

---

## 2. Required changes

### 2.1 Extend the catalog schema (backend)

File: `backend/app/services/docker_service.py`

Add these **optional** keys to catalog entries. Existing entries must keep working unchanged.

| Key | Type | Meaning |
|---|---|---|
| `env` | `dict[str, str]` | Passed as `-e KEY=VALUE` |
| `web_ui` | `{"port": int, "path": str}` | The app's own web page, for an "Open" button |
| `firewall_ports` | `list[str]` e.g. `["8097/tcp"]` | Ports to allow in ufw on install |
| `post_install` | `str` | Short message shown after a successful install |
| `long_description` | `str` | Optional longer text for the store card / details |

Refactor the `docker run` argument building into a **pure function** so it can be unit tested:

```python
def build_run_cmd(app: dict) -> list[str]:
    cmd = ["docker", "run", "-d", "--name", app["id"], "--restart", "unless-stopped",
           "--label", f"nasos.app={app['id']}"]
    if app.get("web_ui"):
        cmd += ["--label", f"nasos.webui.port={app['web_ui']['port']}",
                "--label", f"nasos.webui.path={app['web_ui'].get('path', '/')}"]
    for container_port, host_port in app["ports"].items():
        proto = container_port.split("/")[1] if "/" in container_port else "tcp"
        cmd += ["-p", f"{host_port}:{container_port.split('/')[0]}/{proto}"]
    for vol in app.get("volumes", []):
        cmd += ["-v", vol]
    for key, value in app.get("env", {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd.append(app["image"])
    return cmd
```

`install_app` then becomes: validate the id (keep the existing regex and catalog-membership checks), run
`docker pull`, run `build_run_cmd(app)`, then `_open_firewall(app.get("firewall_ports", []))`, and return
`{"ok": True, "app": app_id, "web_ui": _web_ui_url(app), "post_install": app.get("post_install")}`.
Keep the macOS mock branch: append a mock container that includes `labels`/`web_ui` so the UI can be developed without a Pi.

Note that the existing code maps ports as `-p host:containerport` and drops the protocol. Keeping `/tcp` or `/udp` is
backward compatible, and it also fixes Pi-hole's `53/udp`, which today is published as TCP.

**Firewall helper.** The backend runs as the `nasos` user, so check `system/configs/sudoers-nasos` for an
allowed `ufw` invocation and follow the same pattern other services use. If `ufw allow` isn't
permitted, add a narrowly scoped sudoers line (`nasos ALL=(root) NOPASSWD: /usr/sbin/ufw allow [0-9]*/tcp`)
in both `system/configs/sudoers-nasos` and `image-builder/.../files/configs/sudoers-nasos`, and make sure
`system/scripts/sudoers-repair.sh` still validates it. Validate every port string against
`^\d{1,5}/(tcp|udp)$` before calling ufw. A firewall failure must **not** fail the install: log it and
add a warning to the response.

> Docker-published ports usually bypass ufw through Docker's own iptables chain, so the TV may connect
> even without the rule. Add the rule anyway so the configuration is explicit and survives
> `iptables=false` setups.

### 2.2 Add the Samedia catalog entry

```python
{
    "id": "samedia",
    "name": "Samedia Media Server",
    "category": "Media",
    "description": "Stream your movies & shows to the Samedia Samsung TV app — direct play, Kodi .nfo support, DTS/TrueHD audio conversion",
    "icon": "🍿",
    "image": "ghcr.io/rttgnck/samedia-server:latest",
    "ports": {"8097/tcp": 8097},
    "volumes": [
        "/opt/nasos/config/samedia:/config",
        "/srv/nasos/shares:/media/shares:ro",
        "/mnt:/media/disks:ro,rslave",
    ],
    "env": {
        "SAMEDIA_MEDIA_ROOTS": "/media/shares:/media/disks",
        "SAMEDIA_SERVER_NAME": "nasOS",
        "PUID": "1000",
        "PGID": "1000",
    },
    "web_ui": {"port": 8097, "path": "/"},
    "firewall_ports": ["8097/tcp"],
    "post_install": "Open the Samedia admin page to choose media folders, then install the Samedia app on your Samsung TV.",
},
```

Notes:

- `rslave` on `/mnt` is required. Without it, disks hot-plugged after the container starts are invisible
  inside it (`disk-hotplug.sh` mounts new disks under `/mnt/<label>`).
- Mount media **read-only**. Samedia never writes next to media; its caches live in `/config`.
- `SAMEDIA_SERVER_NAME`: if you can, use the NAS hostname (`socket.gethostname()`) at install time instead
  of a fixed string. Make `env` values support a `{hostname}` placeholder and expand it in `build_run_cmd`.
- `PUID`/`PGID`: if nasOS media files aren't world-readable, set these to the uid/gid that owns the
  shares. Check `share_service._ensure_share_dir` for the owner it applies. If the shares are group-readable by
  a `nasos`/`users` group, pass that gid as `PGID`.

### 2.3 "Open" buttons and post-install message (frontend)

File: `frontend/src/apps/DockerManager/DockerManager.tsx`

1. Extend the TS types:
   ```ts
   interface CatalogApp { /* existing */ web_ui?: { port: number; path: string }; post_install?: string; long_description?: string }
   interface Container  { /* existing */ web_ui?: string }   // absolute URL, filled by the backend
   ```
2. **Catalog card:** if the app is already installed (a container whose name is `app.id` exists), show
   **Open** instead of **Install**. Opening uses `http://${window.location.hostname}:${port}${path}`. The
   nasOS UI can be reached by IP, hostname or `.local`, so derive the host from the current location
   rather than from the backend.
3. **After install:** show `post_install` in the success notification and offer an **Open** action.
4. **Containers list:** for containers with a `nasos.webui.port` label, show an **Open** icon button
   (lucide `ExternalLink`). Backend: in `get_containers()`, add `{{json .Labels}}` to the format string, parse it,
   and set `web_ui` to `"{port}{path}"` (just the port and path; the frontend adds the host).
5. On the **local display** (Electron kiosk), open the URL in a new nasOS window using the existing
   window manager (an iframe-based "Web" window like MediaViewer) rather than `window.open`. In a remote
   browser, `window.open(url, '_blank')` is fine. Check how `electron/main.js` handles `window.open`
   and follow that pattern.

### 2.4 Avahi / mDNS advertisement (small, recommended)

Advertise `_samedia._tcp` so future clients (and the nasOS menubar app) can discover the server without
a subnet scan. Add this to `system/configs/avahi-service.template` *only while the app is installed*:
on install/remove, write or delete `/etc/avahi/services/samedia.service`:

```xml
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">Samedia on %h</name>
  <service>
    <type>_samedia._tcp</type>
    <port>8097</port>
    <txt-record>path=/api/v1/info</txt-record>
  </service>
</service-group>
```

Writing `/etc/avahi/services` needs root, so use the existing `share-helper.sh`-style sudo helper pattern.
This is optional. If it adds sudoers surface you're unsure about, skip it and say so in the PR.

### 2.5 Uninstall cleanup

When the user removes the `samedia` container (`container_action(..., "remove")`):

- Remove the mDNS service file, if you added one.
- **Leave `/opt/nasos/config/samedia` in place**: it holds watch history. Mention this in the UI ("Settings are kept").
- Leave the ufw rule in place. Removing a port that another app may share is riskier than leaving it.

Check while you're there: `container_action` runs `docker remove <id>`. Confirm that the Docker CLI
version in the image builder supports `docker remove`. If not, map `"remove"` to `docker rm -f`.

### 2.6 Pre-existing bug to fix (it blocks the "Open" button)

`get_containers()` on Linux returns `ports` as Docker's display **string** (`"0.0.0.0:8097->8097/tcp"`),
but `ContainersView` treats it as `Record<string, number>` (`Object.entries(c.ports)`), so it renders
character pairs. Parse the string into the same `{"8097/tcp": 8097}` shape the mock data uses:

```python
def _parse_ports(raw: str) -> dict[str, int]:
    out = {}
    for part in filter(None, (p.strip() for p in raw.split(","))):
        if "->" in part:
            host, cont = part.split("->")
            host_port = host.rsplit(":", 1)[-1]
            if host_port.isdigit():
                out[cont] = int(host_port)
    return out
```

---

## 3. Tests

Add `backend/tests/test_docker_catalog.py`:

1. Every catalog entry has `id`, `name`, `category`, `image`, `ports`, `volumes`, and its `id` matches `_VALID_APP_ID`.
2. `build_run_cmd(samedia)` contains, in order: `-p 8097:8097/tcp`; each volume verbatim, including
   `/mnt:/media/disks:ro,rslave`; `-e SAMEDIA_MEDIA_ROOTS=/media/shares:/media/disks`; the image last.
3. `build_run_cmd(pihole)` publishes `53:53/tcp`, which proves that protocol handling didn't regress.
4. `_parse_ports("0.0.0.0:8097->8097/tcp, :::8097->8097/tcp")` → `{"8097/tcp": 8097}`.
5. The firewall port validator rejects `"8097; rm -rf /"` and `"99999/tcp"`.
6. Mock-mode `install_app("samedia")` returns `ok` and includes `web_ui`.

Frontend: if `src/__tests__` has a pattern for component tests, add one for the Install → Open switch.
Otherwise a store-level test is enough.

Run the existing suites: `cd backend && pytest`, `cd frontend && npm test`.

---

## 4. Acceptance criteria

On a Pi 5 running nasOS:

- [ ] The App Store → Media tab shows **Samedia Media Server** with its icon and description.
- [ ] **Install** pulls the arm64 image and starts the container: `docker ps` shows `samedia`, healthy within 60 s.
- [ ] `curl http://<pi>:8097/api/v1/info` returns `"app":"samedia"` from another machine on the LAN.
- [ ] The card now shows **Open**, which loads the Samedia admin page. It lists `/media/shares` and
      `/media/disks` as reachable and starts the first scan automatically.
- [ ] A USB disk plugged in **after** the install appears under `/media/disks/<label>` inside the container
      (`docker exec samedia ls /media/disks`) and is picked up by **Scan library now**.
- [ ] The TV app's **Search again** finds the server, connects, and browses the library.
- [ ] Removing the container keeps `/opt/nasos/config/samedia`. Reinstalling restores watch history.
- [ ] Existing catalog apps still install exactly as before, apart from the explicit `/tcp` on ports.
- [ ] Dev mode on macOS: the catalog shows Samedia, mock install works, and the Open button renders.

---

## 5. Out of scope / don't do

- Don't vendor Samedia server code into nasOS. Consume the published image only.
- Don't add hardware transcoding or GPU device mappings. The Pi 5 has no H.264/HEVC encoder, and Samedia
  is deliberately designed around direct play plus audio-only conversion.
- Don't expose port 8097 beyond the LAN (no UPnP/port forwarding).
- Don't change the Samedia container contract (§1.1). If something there blocks you, write it up for the
  Samedia repo instead.

## 6. Hand-off checklist for the PR description

- The schema additions, with a short example.
- Sudoers changes (exact lines), or "none".
- Screenshots of the store card (Install and Open states) and the Containers list with the Open button.
- How you verified the `rslave` hot-plug behaviour, or "not verified on hardware".
