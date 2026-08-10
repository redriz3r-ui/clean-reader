from app.main import DOWNLOAD_ALLOWED_HOSTS, _download_host_allowed, _extract


def test_lazy_loaded_gallery_is_preserved():
    images = "".join(
        f'<a href="/full/{number}.jpg"><img data-lazy-src="/stills/{number}.jpg" alt="Still {number}"></a>'
        for number in range(1, 5)
    )
    source = f"""
    <html><head><title>Example Film</title></head><body>
      <article><h1>Example Film</h1><div class="entry-content">{images}</div></article>
    </body></html>
    """

    result = _extract(source, "https://example.com/film/")

    assert result.content_type == "gallery"
    assert result.image_count >= 4
    assert "https://example.com/stills/1.jpg" in result.html
    assert "https://example.com/full/1.jpg" in result.html


def test_small_icons_are_not_treated_as_gallery():
    icons = "".join(
        f'<img src="/icons/icon-{number}.png" width="32" height="32">'
        for number in range(1, 5)
    )
    source = f"<html><head><title>Post</title></head><body><article><p>Text</p>{icons}</article></body></html>"

    result = _extract(source, "https://example.com/post")

    assert result.content_type == "article"


def test_subscription_prompts_are_removed():
    images = "".join(f'<img src="/still-{number}.jpg">' for number in range(1, 4))
    source = f"""
    <html><head><title>Gallery</title></head><body><article>
      <div class="newsletter-subscribe"><h2>Discover more</h2><p>Subscribe now</p></div>
      <div class="entry-content">{images}</div>
    </article></body></html>
    """

    result = _extract(source, "https://example.com/gallery")

    assert "Subscribe now" not in result.html


def test_download_allowlist_and_filmgrab_block():
    DOWNLOAD_ALLOWED_HOSTS.add("images.example.com")
    try:
        assert _download_host_allowed("https://images.example.com/still.jpg")
        assert not _download_host_allowed("https://other.example.com/still.jpg")
        DOWNLOAD_ALLOWED_HOSTS.add("film-grab.com")
        assert not _download_host_allowed("https://film-grab.com/still.jpg")
    finally:
        DOWNLOAD_ALLOWED_HOSTS.discard("images.example.com")
        DOWNLOAD_ALLOWED_HOSTS.discard("film-grab.com")
