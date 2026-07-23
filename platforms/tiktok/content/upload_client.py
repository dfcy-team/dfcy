# -*- coding: utf-8 -*-
"""TikTok Content Posting API — 视频上传。"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from config import API_BASE
from oauth import get_access_token


def _api_post(
    path: str,
    payload: dict[str, Any],
    access_token: str | None = None,
) -> dict[str, Any]:
    token = access_token or get_access_token()
    url = f"{API_BASE}{path}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
            err = data.get("error") or {}
            msg = err.get("message") or err.get("code") or raw[:500]
        except json.JSONDecodeError:
            msg = f"HTTP {e.code}: {raw[:500]}"
        raise RuntimeError(msg) from e
    data = json.loads(raw)
    if data.get("error", {}).get("code") not in (None, "ok", ""):
        err = data["error"]
        raise RuntimeError(f"{err.get('code')}: {err.get('message')}")
    return data.get("data") or data


def _put_file(upload_url: str, video_path: Path) -> None:
    data = video_path.read_bytes()
    size = len(data)
    if size <= 0:
        raise ValueError("视频文件为空")
    # TikTok 要求 PUT 带 Content-Range，否则返回 HTTP 416
    req = urllib.request.Request(
        upload_url,
        data=data,
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"上传视频失败 HTTP {e.code}: {raw[:300]}") from e


def upload_draft(
    video_path: Path,
    *,
    access_token: str | None = None,
) -> dict[str, Any]:
    """
    上传到 TikTok 收件箱（草稿），用户可在 App 内编辑后发布。
    需要 scope: video.upload
    """
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(str(video_path))
    size = video_path.stat().st_size
    if size <= 0:
        raise ValueError("视频文件为空")
    if size > 500 * 1024 * 1024:
        raise ValueError("视频超过 500MB 限制")

    init = _api_post(
        "/v2/post/publish/inbox/video/init/",
        {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": size,
                "total_chunk_count": 1,
            }
        },
        access_token,
    )
    upload_url = init.get("upload_url")
    publish_id = init.get("publish_id")
    if not upload_url or not publish_id:
        raise RuntimeError(f"初始化上传失败: {init}")

    _put_file(upload_url, video_path)
    return {"mode": "draft", "publish_id": publish_id, "video": video_path.name}


def upload_direct(
    video_path: Path,
    *,
    title: str = "",
    privacy_level: str = "SELF_ONLY",
    disable_comment: bool = False,
    disable_duet: bool = False,
    disable_stitch: bool = False,
    brand_content_toggle: bool = False,
    brand_organic_toggle: bool = False,
    access_token: str | None = None,
) -> dict[str, Any]:
    """
    直接发布到 TikTok（沙盒默认仅自己可见 SELF_ONLY）。
    需要 scope: video.publish
    """
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(str(video_path))
    size = video_path.stat().st_size

    init = _api_post(
        "/v2/post/publish/video/init/",
        {
            "post_info": {
                "title": title or video_path.stem,
                "privacy_level": privacy_level,
                "disable_comment": disable_comment,
                "disable_duet": disable_duet,
                "disable_stitch": disable_stitch,
                "brand_content_toggle": brand_content_toggle,
                "brand_organic_toggle": brand_organic_toggle,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": size,
                "total_chunk_count": 1,
            },
        },
        access_token,
    )
    upload_url = init.get("upload_url")
    publish_id = init.get("publish_id")
    if not upload_url or not publish_id:
        raise RuntimeError(f"初始化直发失败: {init}")

    _put_file(upload_url, video_path)
    return {"mode": "direct", "publish_id": publish_id, "video": video_path.name}


def query_creator_info(access_token: str | None = None) -> dict[str, Any]:
    return _api_post("/v2/post/publish/creator_info/query/", {}, access_token)


def fetch_publish_status(
    publish_id: str,
    *,
    access_token: str | None = None,
) -> dict[str, Any]:
    return _api_post(
        "/v2/post/publish/status/fetch/",
        {"publish_id": publish_id},
        access_token,
    )
