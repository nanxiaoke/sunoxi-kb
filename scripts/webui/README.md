# WebUI Structure

This directory holds WebUI assets that used to be embedded in `scripts/web_ui.py`.

Current layout:

- `templates/index.html` - the Vue/Tailwind single-page UI served by `GET /`.

Compatibility:

- The startup entry point remains `python3 scripts/web_ui.py`.
- Existing systemd, Docker, and packaging scripts can keep using `scripts/web_ui.py`.

Refactor direction:

- Move frontend assets out of the Flask route file first.
- Keep API routes stable while extracting Python route groups into focused modules.
- Keep smoke tests checking both backend source and frontend template source.
