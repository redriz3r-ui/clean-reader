from __future__ import annotations

import ipaddress
import io
import os
import re
import socket
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import bleach
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from markdownify import markdownify
from pydantic import BaseModel, Field
from readability import Document

BASE_DIR = Path(__file__).resolve().parent
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_DOWNLOAD_IMAGES = 10
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ZIP_BYTES = 50 * 1024 * 1024
USER_AGENT = "LocalReader/1.0 (+personal reading tool)"
DOWNLOAD_ALLOWED_HOSTS = {
    host.strip().lower()
    for host in os.getenv("CLEAN_READER_DOWNLOAD_HOSTS", "").split(",")
    if host.strip()
}
DOWNLOAD_BLOCKED_HOSTS = {"film-grab.com", "www.film-grab.com"}
IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

ALLOWED_TAGS = {
    "a", "article", "aside", "blockquote", "br", "code", "div", "em",
    "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "i", "img", "li", "main", "ol", "p", "pre", "section", "span",
    "strong", "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title", "width", "height", "loading"],
    "div": ["class"],
    "figure": ["class"],
    "section": ["class"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

app = FastAPI(title="Clean Reader", version="1.0.0")


class ReadRequest(BaseModel):
    url: str


class Article(BaseModel):
    url: str
    title: str
    byline: str | None = None
    html: str
    text: str
    markdown: str
    content_type: str = "article"
    image_count: int = 0
    images: list[str] = Field(default_factory=list)
    downloads_allowed: bool = False


class DownloadRequest(BaseModel):
    urls: list[str]
    title: str = "images"
    rights_confirmed: bool = False


def _validate_public_url(raw_url: str) -> str:
    try:
        parsed = urlparse(raw_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        if parsed.username or parsed.password:
            raise ValueError
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except (ValueError, socket.gaierror, UnicodeError) as exc:
        raise HTTPException(400, "Enter a valid public http:// or https:// URL.") from exc

    for *_, sockaddr in addresses:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise HTTPException(400, "Local and private-network URLs are not allowed.")
    return raw_url.strip()


def _download_host_allowed(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname in DOWNLOAD_ALLOWED_HOSTS and hostname not in DOWNLOAD_BLOCKED_HOSTS


async def _fetch(url: str) -> tuple[str, str]:
    current = _validate_public_url(url)
    timeout = httpx.Timeout(15.0, connect=7.0)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(502, "The site returned an invalid redirect.")
                        current = _validate_public_url(urljoin(current, location))
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if "html" not in content_type and "xhtml" not in content_type:
                        raise HTTPException(415, "That URL did not return an HTML page.")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise HTTPException(413, "The page is larger than the 5 MB limit.")
                        chunks.append(chunk)
                    encoding = response.encoding or "utf-8"
                    return b"".join(chunks).decode(encoding, errors="replace"), str(response.url)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    raise HTTPException(
                        429,
                        "This site is rate-limiting requests. Wait a while and try again; "
                        "the reader will not bypass the site's protection.",
                    ) from exc
                raise HTTPException(502, f"The site returned HTTP {exc.response.status_code}.") from exc
            except httpx.RequestError as exc:
                raise HTTPException(502, "The page could not be reached.") from exc
    raise HTTPException(502, "The site redirected too many times.")


def _image_source(image) -> str | None:
    """Return the best lazy-loaded or regular source exposed by an image tag."""
    for attr in ("data-src", "data-lazy-src", "data-original", "data-orig-file", "src"):
        value = image.get(attr)
        if value and not value.startswith("data:"):
            return value.strip()
    srcset = image.get("data-srcset") or image.get("srcset")
    if srcset:
        candidates = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
        return candidates[-1] if candidates else None
    return None


def _looks_like_content_image(image, source: str) -> bool:
    haystack = " ".join(
        [source, image.get("class", [""])[0] if image.get("class") else "", image.get("alt", "")]
    ).lower()
    if any(word in haystack for word in ("logo", "avatar", "emoji", "icon", "spinner", "badge", "pixel")):
        return False
    try:
        width = int(str(image.get("width", "0")).replace("px", ""))
        height = int(str(image.get("height", "0")).replace("px", ""))
        if width and height and (width < 240 or height < 140):
            return False
    except ValueError:
        pass
    return True


def _gallery_images(original: BeautifulSoup, final_url: str) -> list[dict[str, str]]:
    """Find likely gallery images without downloading or probing image URLs."""
    scope = (
        original.select_one("article")
        or original.select_one("main")
        or original.select_one(".entry-content, .post-content, .article-content, .content")
        or original.body
        or original
    )
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for image in scope.find_all("img"):
        source = _image_source(image)
        if not source or not _looks_like_content_image(image, source):
            continue
        source = urljoin(final_url, source)
        if urlparse(source).scheme not in {"http", "https"} or source in seen:
            continue
        seen.add(source)
        parent_link = image.find_parent("a", href=True)
        link = urljoin(final_url, parent_link["href"]) if parent_link else source
        if urlparse(link).scheme not in {"http", "https"}:
            link = source
        results.append({"src": source, "href": link, "alt": image.get("alt", "").strip()})
    return results


def _extract(source_html: str, final_url: str) -> Article:
    original = BeautifulSoup(source_html, "html.parser")
    document = Document(source_html)
    title = BeautifulSoup(document.title(), "html.parser").get_text(" ", strip=True) or "Untitled"
    content = document.summary(html_partial=True)
    soup = BeautifulSoup(content, "html.parser")

    promotional_pattern = re.compile(
        r"subscribe|newsletter|paywall|membership|sharedaddy|jp-relatedposts|more-from",
        re.IGNORECASE,
    )
    for tag in soup.find_all(True):
        if tag.attrs is None:  # A parent promotional block was already removed.
            continue
        marker = " ".join([tag.get("id", ""), *tag.get("class", [])])
        if marker and promotional_pattern.search(marker):
            tag.decompose()
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if heading.get_text(" ", strip=True).lower().startswith("discover more from"):
            sibling = heading.find_next_sibling()
            heading.decompose()
            # WordPress may strip the promo wrapper before Readability sees it.
            # Remove only the adjacent promo paragraphs and stop at real content.
            for _ in range(3):
                if sibling is None or sibling.name not in {"p", "a"}:
                    break
                next_sibling = sibling.find_next_sibling()
                sibling.decompose()
                sibling = next_sibling

    gallery = _gallery_images(original, final_url)
    readable_sources = {
        urljoin(final_url, source)
        for image in soup.find_all("img")
        if (source := _image_source(image))
    }
    # Readability is text-focused and often drops image-only galleries. When a
    # page clearly contains a gallery, append only the images missing from its
    # extracted article rather than replacing useful titles and descriptions.
    missing_gallery = [image for image in gallery if image["src"] not in readable_sources]
    if len(gallery) >= 3 and missing_gallery:
        section = soup.new_tag("section", attrs={"class": "image-gallery"})
        for item in missing_gallery:
            figure = soup.new_tag("figure", attrs={"class": "gallery-item"})
            link = soup.new_tag("a", href=item["href"], title="Open original image")
            image = soup.new_tag("img", src=item["src"], alt=item["alt"], loading="lazy")
            link.append(image)
            figure.append(link)
            section.append(figure)
        soup.append(section)

    for tag in soup.find_all(["script", "style", "form", "button", "iframe", "object", "embed"]):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in ("href", "src"):
            if tag.get(attr):
                tag[attr] = urljoin(final_url, tag[attr])
        if tag.name == "img":
            source = _image_source(tag)
            if source:
                tag["src"] = urljoin(final_url, source)
            tag["loading"] = "lazy"

    clean_html = bleach.clean(
        str(soup), tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES,
        protocols={"http", "https", "mailto"}, strip=True,
    )
    clean_soup = BeautifulSoup(clean_html, "html.parser")
    text = clean_soup.get_text("\n", strip=True)
    md = markdownify(clean_html, heading_style="ATX", bullets="-").strip()

    author = original.find("meta", attrs={"name": lambda value: value and value.lower() == "author"})
    byline = author.get("content", "").strip() if author else None
    image_count = len(clean_soup.find_all("img"))
    return Article(
        url=final_url,
        title=title,
        byline=byline or None,
        html=clean_html,
        text=text,
        markdown=md,
        content_type="gallery" if len(gallery) >= 3 else "article",
        image_count=image_count,
        images=[urljoin(final_url, image.get("src")) for image in clean_soup.find_all("img") if image.get("src")],
        downloads_allowed=bool(gallery) and all(_download_host_allowed(image["src"]) for image in gallery),
    )


async def _fetch_allowed_image(client: httpx.AsyncClient, raw_url: str) -> tuple[bytes, str, str]:
    current = _validate_public_url(raw_url)
    if not _download_host_allowed(current):
        raise HTTPException(403, "Image downloads are not enabled for this source.")
    for _ in range(MAX_REDIRECTS + 1):
        try:
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise HTTPException(502, "An image returned an invalid redirect.")
                    current = _validate_public_url(urljoin(current, location))
                    if not _download_host_allowed(current):
                        raise HTTPException(403, "An image redirected to a source that is not allowed.")
                    continue
                response.raise_for_status()
                media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                extension = IMAGE_TYPES.get(media_type)
                if not extension:
                    raise HTTPException(415, f"Unsupported image type: {media_type or 'unknown'}.")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise HTTPException(413, "An image exceeds the 10 MB limit.")
                    chunks.append(chunk)
                return b"".join(chunks), extension, current
        except httpx.HTTPStatusError as exc:
            raise HTTPException(502, f"An image returned HTTP {exc.response.status_code}.") from exc
        except httpx.RequestError as exc:
            raise HTTPException(502, "An image could not be reached.") from exc
    raise HTTPException(502, "An image redirected too many times.")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/read", response_model=Article)
async def read_page(request: ReadRequest) -> Article:
    source_html, final_url = await _fetch(request.url)
    return _extract(source_html, final_url)


@app.post("/api/download-images")
async def download_images(request: DownloadRequest) -> StreamingResponse:
    if not request.rights_confirmed:
        raise HTTPException(400, "Confirm that you have permission to download these images.")
    urls = list(dict.fromkeys(request.urls))
    if not urls or len(urls) > MAX_DOWNLOAD_IMAGES:
        raise HTTPException(400, f"Select between 1 and {MAX_DOWNLOAD_IMAGES} images.")
    if not all(_download_host_allowed(url) for url in urls):
        raise HTTPException(403, "Downloads are not enabled for one or more selected sources.")

    archive = io.BytesIO()
    sources: list[str] = []
    total = 0
    timeout = httpx.Timeout(20.0, connect=7.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "image/*"},
        follow_redirects=False,
    ) as client:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for number, url in enumerate(urls, start=1):
                content, extension, final_url = await _fetch_allowed_image(client, url)
                total += len(content)
                if total > MAX_ZIP_BYTES:
                    raise HTTPException(413, "The selected images exceed the 50 MB total limit.")
                bundle.writestr(f"image-{number:02d}{extension}", content)
                sources.append(f"image-{number:02d}{extension}\t{final_url}")
            bundle.writestr("SOURCES.txt", "Source images\n\n" + "\n".join(sources) + "\n")

    archive.seek(0)
    safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "-", request.title).strip("-") or "images"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.zip"'},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
