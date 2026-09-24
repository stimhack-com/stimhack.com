"""Card images that posts loaded from NetrunnerDB's old image paths.

NetrunnerDB moved its card scans to card-images.netrunnerdb.com. Every old
path has the five-digit card code, so each maps to the new URL. The "large"
size is 300x418, the size of the old images.
"""
import re

OLD_CARD_IMAGE = re.compile(
    r"^https?://(?:www\.)?netrunnerdb\.com/(?:web/)?"
    r"(?:bundles/netrunnerdbcards/images/cards/en(?:-large)?/|card_image/(?:/?large/)?)"
    r"(\d{5})\.(?:png|jpg)$"
)
NEW_CARD_IMAGE = "https://card-images.netrunnerdb.com/v2/large/{}.jpg"

# Card type icons from the old NetrunnerDB deck builder. No copy survives, and
# the deck list heading next to each icon already names the type.
TYPE_ICON = re.compile(
    r"""<img\b[^>]*\bsrc=["']https?://(?:www\.)?netrunnerdb\.com/bundles/netrunnerdbbuilder/images/types/[^"']+["'][^>]*>\s?""",
    re.I,
)


def remove_type_icons(html):
    return TYPE_ICON.sub("", html)


def rewrite(url):
    m = OLD_CARD_IMAGE.match(url)
    return NEW_CARD_IMAGE.format(m[1]) if m else url
