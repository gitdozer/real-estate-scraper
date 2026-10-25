"""Impronte percettive delle foto (spec §6.4).

Le immagini non vengono salvate: se ne tiene solo l'impronta (64 bit, 16 caratteri
esadecimali). Due foto uguali ridimensionate o ricompresse hanno impronte vicine
(distanza di Hamming bassa): serve in fase 2 per riconoscere le ripubblicazioni.
"""

import io

import imagehash
from PIL import Image, UnidentifiedImageError


def hash_image(content: bytes) -> tuple[str, str] | None:
    """Restituisce (phash, dhash) in esadecimale, oppure None se i bytes non sono un'immagine."""
    try:
        with Image.open(io.BytesIO(content)) as img:
            img = img.convert("RGB")
            return str(imagehash.phash(img, hash_size=8)), str(imagehash.dhash(img, hash_size=8))
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def hamming(a: str, b: str) -> int:
    """Numero di bit diversi tra due impronte esadecimali."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")
