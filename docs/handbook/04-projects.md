# 4. Projects and backups

[Handbook](README.md) · Previous: [Providers](03-providers.md) · Next: [First video](05-first-video.md)

Use one project per coherent story or production. A fresh database creates a default project automatically; you do not need to preload assets.

## Create or open a project

1. Click the project name or **Projects** near the top of the sidebar.
2. Enter a name and optional description and create the project.
3. Creation makes the project active and opens Studio. Choose **Create video** for the guided path.
4. To return to earlier work, use **Open** on its project card.

The active project is server-wide. Avoid switching projects while a generation operation is running, and avoid working in different projects in separate tabs at the same time. Background services repeatedly consult the active project; the audit tracks this isolation risk.

The sidebar may retain an old project name after switching because it loads that value only on mount. Refresh the page and confirm the active project before creating content.

## Export and import

Use **Export** on a project card to download a ZIP containing project rows and referenced media. Keep a copy before large edits. Use **Import** to select an exported ZIP. Import creates a new inactive project; use Open to work on it. This is project portability, not a complete installation backup with all global credentials and settings.

Deleting a project removes its database records and keeps underlying files. The active project cannot be deleted; open another first. Kept files alone do not reconstruct the deleted relationships. Export first if you may need the project again.

## Back up the installation

1. Let active work finish and stop the API.
2. Copy `db.sqlite` and the entire `storage/` folder to a dated backup directory.
3. Save `.env` separately in private storage if you need to restore configuration.
4. Keep global settings and credentials private: the database may contain provider keys.
5. Restore database and storage from the same backup, then restart from the same repository layout.

If you changed `DATABASE_URL` or `STORAGE_ROOT`, back up the configured locations. Use the default storage layout for now: the frontend's media URL conversion assumes a path containing `storage/`.
