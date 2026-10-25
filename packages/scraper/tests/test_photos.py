import io

from PIL import Image, ImageDraw

from scraper.photos import hash_image, hamming


def picture(kind: str, size=(400, 300)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    w, h = size
    if kind == "stanza":
        d.rectangle([0, int(h * 0.6), w, h], fill=(120, 80, 40))  # pavimento
        d.rectangle([int(w * 0.1), int(h * 0.15), int(w * 0.4), int(h * 0.5)], fill=(90, 160, 220))  # finestra
        d.ellipse([int(w * 0.6), int(h * 0.3), int(w * 0.9), int(h * 0.7)], fill=(30, 30, 30))
    else:
        for i in range(0, w, 40):
            d.rectangle([i, 0, i + 20, h], fill=(200, 30, 30))
        d.polygon([(0, h), (w // 2, 0), (w, h)], fill=(20, 120, 20))
    return img


def jpeg(img: Image.Image, quality=90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def test_hash_is_16_hex_pair():
    ph, dh = hash_image(jpeg(picture("stanza")))
    assert len(ph) == 16 and len(dh) == 16 and int(ph, 16) >= 0 and int(dh, 16) >= 0


def test_resized_recompressed_image_is_close():
    a, _ = hash_image(jpeg(picture("stanza")))
    small = picture("stanza").resize((200, 150))
    b, _ = hash_image(jpeg(small, quality=60))
    assert hamming(a, b) <= 6


def test_different_image_is_far():
    a, _ = hash_image(jpeg(picture("stanza")))
    b, _ = hash_image(jpeg(picture("altro")))
    assert hamming(a, b) > 10


def test_invalid_bytes_return_none():
    assert hash_image(b"non e' un'immagine") is None
    assert hash_image(b"") is None
