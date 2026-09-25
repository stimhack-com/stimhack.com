"""Read the front matter of the content files under a directory.

A post folder of a new post also has the images and other files of the post,
which are not content files and can be binary. convert.py and the tests read
only the files that start with a YAML front matter block.
"""
import yaml


def content_files(root):
    """Return (path, front matter) for each file under root that starts with a YAML front matter block.

    The paths are in sorted order. A file that starts with "---" and a Windows
    line end is a content file too: read_text() opens the file with the default
    newline=None, which changes "\\r\\n" to "\\n" (Path.read_text in the
    Python 3.12 pathlib.py, and open() in python3 -c "help(open)").
    """
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.read_bytes().startswith((b"---\n", b"---\r\n")):
            found.append((path, yaml.safe_load(path.read_text().split("---\n")[1]) or {}))
    return found
