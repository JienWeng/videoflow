# 2. Install from zero

[Handbook](README.md) · Previous: [How it works](01-how-it-works.md) · Next: [Providers](03-providers.md)

You will run two processes: a Python API on port 8000 and the frontend on port 5173. These instructions use the existing VideoFlow repository; do not create a new Svelte project or a `backend` directory.

## 1. Install the prerequisites

| Tool | Requirement | Install |
|---|---|---|
| Git | Download and update the repository | [Official installers](https://git-scm.com/downloads/) |
| uv | Manage Python and Python packages | [Official uv installation](https://docs.astral.sh/uv/getting-started/installation/) |
| Python | Use 3.12 for this setup; uv can install it | Run the command below |
| Node.js and npm | Node 22.12 or later; npm comes with Node | [Official Node download](https://nodejs.org/en/download) |
| FFmpeg | Needed for captions, thumbnails, and QA frame extraction; use a build with libass | [Official download options](https://ffmpeg.org/download.html) |

Open Terminal on macOS/Linux or PowerShell on Windows. After installing tools, open a new terminal so PATH changes take effect. Check:

```sh
git --version
uv --version
node --version
npm --version
ffmpeg -version
```

If a command is not found, finish installing that tool and reopen the terminal. Install Python through uv:

```sh
uv python install 3.12
```

A GPU is not required by the application: AI media generation is remote and the caption service uses CPU transcription. Initial package and speech-model downloads require internet access. Linux was used for this audit; native macOS and Windows installation has not been exercised here.

## 2. Download VideoFlow

Choose a folder where you keep projects, then run:

```sh
git clone https://github.com/JienWeng/videoflow.git
cd videoflow
uv sync --frozen --extra dev --python 3.12
```

The repository root contains `pyproject.toml`, `app`, and `frontend`. Run backend commands from this folder. `uv sync` creates `.venv`; manual activation is unnecessary when using `uv run`.

If you are reviewing this audit snapshot, run `git switch audit/handbook-readiness-2026-09-27` after cloning and before syncing. A normal clone otherwise uses the repository's default branch.

## 3. Create configuration

On macOS/Linux:

```sh
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Use this copy step only on a fresh clone. Preserve an existing `.env` when upgrading. Open `.env` in a text editor. You may leave keys empty to explore the workspace; generation requires configured accounts. Complete [Part 3](03-providers.md) before generating.

Defaults create `db.sqlite` and `storage/` locally. Do not create tables manually. Saved settings in the database may override `.env`; restart the API after changing environment values.

## 4. Start the API

In terminal A, from the repository root:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep the terminal open. Visit [API health](http://localhost:8000/health) and [API reference](http://localhost:8000/docs). A successful health response confirms that the API is up; it does not validate provider credentials or generation.

Developers may add `--reload`, but editing backend files then restarts the server and interrupts running background operations. Omit it during video production.

## 5. Start the frontend

Open terminal B in the repository root:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Visit [Create video](http://localhost:5173/create). The API must remain running. If Vite selects another port because 5173 is occupied, free port 5173 and restart: backend CORS currently permits 5173 and 4173.

For a local production build:

```sh
npm run build
npm run preview -- --host 127.0.0.1
```

The preview normally uses port 4173. This is a local application with no application login boundary; public hosting needs additional design and is not covered by this setup.

## 6. Prepare captions if needed

FFmpeg must include the `ass` filter. Check it with `ffmpeg -filters`. For Chinese captions, put `NotoSansCJKsc-Bold.otf` in `storage/fonts/`. Create that directory before downloading. Obtain the font from the [Noto CJK repository](https://github.com/notofonts/noto-cjk/tree/main/Sans/OTF/SimplifiedChinese).

The first transcription downloads the chosen Whisper model. Start with `tiny` or `base` to reduce download and processing time, then assess recognition quality.

## Stop and restart

Wait for operations to finish, then press Ctrl+C in each terminal. On the next launch, repeat the API and frontend start commands; dependencies only need installing after dependency changes. Render polling has restart reconciliation, while interrupted orchestration operations are marked failed and need manual recovery.

Back up the database and storage together before upgrades. See [Projects](04-projects.md). For startup errors, use [Troubleshooting](11-troubleshooting.md).

## What was checked

The audit started an API against a new temporary SQLite database and fetched the empty-project endpoints successfully. The frontend type check and build passed. A clean OS installation, graphical browser walkthrough, paid generation, and FFmpeg execution were not verified in this session.
