# Clean Reader

A small local web app that fetches a public article or image gallery, extracts its main content, sanitizes it, and presents a distraction-free reader view. It can also export the result as Markdown or plain text.

It also includes a local moodboard: add image files from your Mac, attach tags and notes, and print or save the board as a PDF without uploading the files to an external service.

## MVP architecture

```text
Browser form → FastAPI endpoint → safe HTTP fetch → Readability extraction
             ← clean JSON       ← HTML sanitizing + text/Markdown conversion
```

- **Frontend:** one dependency-free HTML/CSS/JavaScript page.
- **Backend:** FastAPI and HTTPX, with timeouts, a 5 MB response limit, and private-network URL blocking.
- **Extraction:** `readability-lxml` identifies the main article; a gallery pass preserves regular and lazy-loaded content images; Beautiful Soup normalizes links; Bleach sanitizes the result.
- **Exports:** Markdown and text are generated on the backend and downloaded in the browser.
- **Authorized image export:** Selected-image ZIP downloads are disabled by default and require an explicit source-host allowlist plus a rights confirmation.

## Run on a Mac

Python 3.10 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

To enable selected-image downloads for a site you own or have permission to copy, provide exact image hosts before starting the app:

```bash
export CLEAN_READER_DOWNLOAD_HOSTS="images.example.com,cdn.example.com"
uvicorn app.main:app --reload
```

Downloads remain limited to 10 images, 10 MB per image, and 50 MB total. FilmGrab is intentionally view-only because its stated policy rejects scraping.

### Local moodboards

Choose **Add local images** and select JPEG, PNG, WebP, or GIF files up to 15 MB each. Add tags and notes under each reference. **Print / Save PDF** opens the Mac print dialog, where you can select **Save as PDF**. Local files stay in the browser session; refreshing the page clears the board.

To stop the app, press `Control-C` in the terminal.

## Build the reusable Mac app

The packaged version opens in its own Mac window and starts/stops its private local service automatically. It does not require Terminal after it has been built.

```bash
source .venv/bin/activate
python -m pip install -r requirements-build.txt
./packaging/build_mac_app.sh
```

The build creates:

- `outputs/Clean Reader.app` — double-clickable Mac application.
- `outputs/Clean Reader-mac-arm64.zip` — reusable archive for another Apple Silicon Mac.

This personal build is unsigned. On another Mac, Control-click the app and choose **Open** the first time. Public distribution should use an Apple Developer ID to sign and notarize the application.

## Practical limitations

- Pages whose article content is rendered only by JavaScript may appear empty. A later version could add Playwright as an opt-in fallback, though it is heavier and increases security risk.
- Paywalled, login-only, bot-protected, or unusually structured pages may not work.
- Gallery images remain hosted by the source website. The app displays them but does not download or redistribute the image files.
- Sites may return HTTP 429 when they are busy or rate-limiting automated clients. The app reports this and does not try to evade the restriction.
- The app intentionally accepts only public HTTP(S) pages and checks every redirect. Do not remove these checks if you expose it beyond your own computer.
- This MVP is stateless: it does not save reading history or fetched pages.

## Responsible and legal use

Use this for pages you are permitted to access. Before scraping a site at scale, review its terms of service and `robots.txt`; obey access restrictions, copyright, privacy, and applicable law. Identify your client honestly, rate-limit requests, cache when appropriate, and avoid bypassing paywalls, authentication, CAPTCHAs, or technical controls. `robots.txt` is an important publisher preference, but it is not by itself a grant of legal permission. This MVP performs only one user-requested fetch at a time; production use should add per-domain rate limits and a deliberate robots-policy check.

## Possible next steps

- Save articles in SQLite and add a reading list.
- Add typography controls, dark-mode selection, and estimated reading time.
- Add a robots.txt policy checker and per-domain throttling.
- Add tests with saved HTML fixtures from several article layouts.
