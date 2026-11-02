"""Perceptual fingerprints of the photos (spec §6.4).

The images are not saved: only their fingerprint is kept (64 bits, 16 hex
characters). The same photo resized or recompressed gets a nearby fingerprint
(low Hamming distance): phase 2 uses this to recognize relisted properties.
"""

import io

import imagehash
from PIL import Image, UnidentifiedImageError


def hash_image(content: bytes) -> tuple[str, str] | None:
    """Returns (phash, dhash) as hex, or None if the bytes are not an image."""
    try:
        with Image.open(io.BytesIO(content)) as img:
            img = img.convert("RGB")
            return str(imagehash.phash(img, hash_size=8)), str(imagehash.dhash(img, hash_size=8))
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def hamming(a: str, b: str) -> int:
    """Number of differing bits between two hex fingerprints."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")
