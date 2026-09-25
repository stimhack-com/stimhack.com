"""Tests for the upload list in migration/download_uploads.py.

Run: python3 -m unittest discover tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "migration"))
import convert  # noqa: E402
import download_uploads  # noqa: E402

UPLOADS = "https://stimhack.com/wp-content/uploads/2020/01/"


def image(id, post, name):
    return {
        "id": id, "post": post, "mime_type": "image/jpeg", "source_url": f"{UPLOADS}{name}.jpg",
        "media_details": {"sizes": {"medium": {"source_url": f"{UPLOADS}{name}-300x200.jpg"}}},
    }


def post(id, slug, featured_media):
    return {
        "id": id, "slug": slug, "link": f"https://stimhack.com/{slug}/", "format": "standard",
        "guid": {"rendered": f"https://stimhack.com/?p={id}"},
        "title": {"rendered": slug}, "content": {"rendered": "<p>No images.</p>"},
        "excerpt": {"rendered": "<p>No images.</p>"},
        "date": "2020-01-02T10:00:00", "date_gmt": "2020-01-02T18:00:00",
        "modified": "2020-01-02T10:00:00", "modified_gmt": "2020-01-02T18:00:00",
        "author": 1, "categories": [1], "tags": [], "featured_media": featured_media,
    }


class FrontMatterImages(unittest.TestCase):
    """Convert a two post export and check the downloader collects every image the posts name."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / ".export"
        export.mkdir()
        (root / "tests").mkdir()
        export_files = {
            # One post with a featured image, one with only an image uploaded to it.
            "posts": [post(10, "featured", 100), post(11, "attached", 0)],
            "media": [image(100, 10, "cover"), image(101, 11, "inline")],
            "pages": [], "comments": [], "tags": [],
            "categories": [{"id": 1, "slug": "news", "name": "News", "link": "https://stimhack.com/category/news/", "count": 2}],
            "users": [{"id": 1, "slug": "writer", "name": "Writer", "link": "https://stimhack.com/author/writer/", "avatar_urls": {}}],
        }
        for name, items in export_files.items():
            (export / f"{name}.json").write_text(json.dumps(items))
        with mock.patch.multiple(convert, ROOT=root, EXPORT=export, CONTENT=root / "content"), \
                mock.patch.object(convert.wayback, "POSTS", {}):
            convert.main()
        self.named = {}
        for f in (root / "content" / "posts").rglob("*.html"):
            front = yaml.safe_load(f.read_text().split("---\n")[1])
            for key in ("featured_image", "thumbnail"):
                if key in front:
                    self.named[f"{front['slug']} {key}"] = front[key]
        with mock.patch.multiple(download_uploads, ROOT=root, EXPORT=export, STATIC=root / "static"):
            self.paths = download_uploads.upload_paths()

    def test_every_featured_image_and_thumbnail_is_downloaded(self):
        self.assertEqual(len(self.named), 3)
        for name, path in self.named.items():
            with self.subTest(name):
                self.assertIn(path, self.paths)


# Files of the site that reference uploads the export does not have, such as
# a post a contributor wrote or a post deleted from WordPress.
SITE_FILES = {
    "content/posts/2026/new.md": (
        "---\nthumbnail: /wp-content/uploads/2026/01/thumb.jpg\n---\n"
        "![](/wp-content/uploads/2026/01/markdown.png)\n"
        '<img src="https://stimhack.com/wp-content/uploads/2026/01/absolute.png"'
        ' srcset="/wp-content/uploads/2026/01/one.png, //www.stimhack.com/wp-content/uploads/2026/01/two.png 2x">\n'
        '<a href="http://stimhack.com/wp-content/uploads/2026/01/Will-O%E2%80%99-the%20Wisp.png?w=300#top">x</a>\n'
        # Uploads of other sites are not uploads of this site.
        '<img src="http://other.example/wp-content/uploads/2026/01/other-host.png">\n'
        '<img src="/images/archive/other.example/wp-content/uploads/2026/01/archived.png">\n'
    ),
    "data/decks.yaml": 'image: "/wp-content/uploads/2026/01/data.png"\n',
    "hugo.toml": '[params]\n  headerImage = "/wp-content/uploads/2026/01/header.png"\n',
    "config/staging/hugo.toml": 'favicon = "/wp-content/uploads/2026/01/staging.ico"\n',
    "assets/css/site.css": "body { background: url(/wp-content/uploads/2026/01/background.jpg); }\n",
    "layouts/_partials/logo.html": '<img src="https://stimhack.com/wp-content/uploads/2026/01/logo.png">\n',
}
REFERENCED = {
    "2026/01/thumb.jpg", "2026/01/markdown.png", "2026/01/absolute.png", "2026/01/one.png",
    "2026/01/two.png", "2026/01/Will-O’-the Wisp.png", "2026/01/data.png", "2026/01/header.png",
    "2026/01/staging.ico", "2026/01/background.jpg", "2026/01/logo.png",
}
UNREFERENCED = {"2026/01/other-host.png", "2026/01/archived.png", "2026/01/unused.png"}


class UploadsTheSiteReferences(unittest.TestCase):
    """Run the downloader on a site whose files reference uploads that the export does not have."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        export = root / ".export"
        export.mkdir()
        (export / "media.json").write_text(json.dumps([image(100, 10, "cover")]))
        (export / "posts.json").write_text("[]")
        (export / "pages.json").write_text("[]")
        for name, text in SITE_FILES.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        self.uploads = root / "static" / "wp-content" / "uploads"
        for name in REFERENCED | UNREFERENCED | {"2020/01/cover.jpg"}:
            (self.uploads / name).parent.mkdir(parents=True, exist_ok=True)
            (self.uploads / name).write_bytes(b"image")
        patch = mock.patch.multiple(download_uploads, ROOT=root, EXPORT=export, STATIC=root / "static")
        patch.start()
        self.addCleanup(patch.stop)

    def test_referenced_uploads_stay_in_static(self):
        download_uploads.move_unused(download_uploads.upload_paths())
        unused = self.root / ".export" / "unused-uploads"
        moved = {f.relative_to(unused).as_posix() for f in unused.rglob("*") if f.is_file()}
        self.assertEqual(moved, UNREFERENCED)

    def test_referenced_uploads_are_downloaded(self):
        paths = set(download_uploads.upload_paths())
        self.assertEqual(
            {name for name in REFERENCED if f"/wp-content/uploads/{name}" not in paths}, set()
        )


if __name__ == "__main__":
    unittest.main()
