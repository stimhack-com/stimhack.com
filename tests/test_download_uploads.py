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
        with mock.patch.object(download_uploads, "EXPORT", export):
            self.paths = download_uploads.upload_paths()

    def test_every_featured_image_and_thumbnail_is_downloaded(self):
        self.assertEqual(len(self.named), 3)
        for name, path in self.named.items():
            with self.subTest(name):
                self.assertIn(path, self.paths)


if __name__ == "__main__":
    unittest.main()
