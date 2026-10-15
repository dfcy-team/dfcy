"""Bounded, tenant-safe image loading for supplier purchase workbooks."""
from concurrent.futures import ThreadPoolExecutor, wait
from io import BytesIO
import warnings

from django.core.files.storage import default_storage
from PIL import Image, UnidentifiedImageError

from apps.products.views import _download_product_image, _safe_local_product_image_path


MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
THUMBNAIL_SIZE = (320, 320)
MAX_REMOTE_IMAGES = 1000
REMOTE_WORKERS = 8
REMOTE_DEADLINE_SECONDS = 20


def _read_image(image_url, tenant_id):
    if not image_url:
        return None
    value = str(image_url)
    if value.startswith("/"):
        relative = _safe_local_product_image_path(value, tenant_id)
    else:
        relative, _, _ = _download_product_image(value, tenant_id)
    with default_storage.open(relative, "rb") as source:
        content = source.read(MAX_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片文件必须在 1 字节到 5 MB 之间。")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(content)) as image:
            if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("图片尺寸过大。")
            image.load()
            image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=True)
            return output.getvalue()


def load_product_images(snapshot, tenant_id):
    """Return ``{sku_id: {body: bytes|None, status: str}}`` for snapshot lines.

    Remote URLs are fetched concurrently with a hard batch cap and deadline.
    Local files are validated against the current tenant before storage access.
    """
    records = {}
    url_to_skus = {}
    for line in snapshot.get("lines", []):
        sku_id = line.get("sku_id")
        details = line.get("product_details") or {}
        image_url = details.get("image_url")
        if not image_url:
            records[sku_id] = {"body": None, "status": "missing"}
        else:
            url_to_skus.setdefault(str(image_url), []).append(sku_id)

    local_urls = {url for url in url_to_skus if url.startswith("/")}
    for url in local_urls:
        try:
            body = _read_image(url, tenant_id)
            result = {"body": body, "status": "available"}
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            result = {"body": None, "status": "failed"}
        for sku_id in url_to_skus[url]:
            records[sku_id] = result

    remote_urls = [url for url in url_to_skus if url not in local_urls]
    accepted = remote_urls[:MAX_REMOTE_IMAGES]
    for url in remote_urls[MAX_REMOTE_IMAGES:]:
        for sku_id in url_to_skus[url]:
            records[sku_id] = {"body": None, "status": "limit"}

    executor = ThreadPoolExecutor(max_workers=REMOTE_WORKERS, thread_name_prefix="supplier-image")
    futures = {executor.submit(_read_image, url, tenant_id): url for url in accepted}
    completed, pending = wait(futures, timeout=REMOTE_DEADLINE_SECONDS)
    for future in completed:
        url = futures[future]
        try:
            result = {"body": future.result(), "status": "available"}
        except Exception:
            result = {"body": None, "status": "failed"}
        for sku_id in url_to_skus[url]:
            records[sku_id] = result
    for future in pending:
        future.cancel()
        url = futures[future]
        for sku_id in url_to_skus[url]:
            records[sku_id] = {"body": None, "status": "timeout"}
    executor.shutdown(wait=False, cancel_futures=True)
    return records
