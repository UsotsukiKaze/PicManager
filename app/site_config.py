"""Editable configuration for the public personal homepage."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .config import settings


class SiteProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    url: HttpUrl
    label: str = Field(default="打开", min_length=1, max_length=24)


class SiteAppearance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accent: str = Field(default="#a7c7ff", pattern=r"^#[0-9a-fA-F]{6}$")
    accent_secondary: str = Field(default="#d7b6ff", pattern=r"^#[0-9a-fA-F]{6}$")


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(default="UsotsukiKaze", min_length=1, max_length=60)
    welcome: str = Field(default="欢迎来到", max_length=40)
    subtitle: str = Field(default="A quiet corner for code and ideas", max_length=120)
    pixel_text: str = Field(default="随风而行", max_length=24)
    introduction: str = Field(default="", max_length=600)
    skills: list[str] = Field(default_factory=list, max_length=20)
    projects: list[SiteProject] = Field(default_factory=list, max_length=12)
    github_url: HttpUrl = "https://github.com/UsotsukiKaze"
    avatar_url: HttpUrl | None = None
    appearance: SiteAppearance = Field(default_factory=SiteAppearance)


DEFAULT_SITE_CONFIG = SiteConfig(
    introduction=(
        "我是 UsotsukiKaze。这里是我的个人中转站，用来集中展示正在维护的项目、"
        "常用入口和公开资料。最近主要在开发 PicManager。"
    ),
    skills=["Python", "FastAPI", "JavaScript", "CSS", "SQLite", "Git"],
    projects=[
        SiteProject(
            title="PicManager",
            description="面向图片收藏、标签整理与快速检索的图片管理工具。",
            url="https://pic.usotsuki-kaze.com",
            label="进入项目",
        ),
        SiteProject(
            title="GitHub",
            description="查看我的开源项目、代码与近期开发动态。",
            url="https://github.com/UsotsukiKaze",
            label="查看主页",
        ),
    ],
)

_WRITE_LOCK = Lock()


def _config_path() -> Path:
    path = Path(settings.SITE_CONTENT_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_site_config() -> SiteConfig:
    path = _config_path()
    if not path.is_file():
        save_site_config(DEFAULT_SITE_CONFIG)
        return DEFAULT_SITE_CONFIG.model_copy(deep=True)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SiteConfig.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return DEFAULT_SITE_CONFIG.model_copy(deep=True)


def save_site_config(config: SiteConfig) -> None:
    path = _config_path()
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = config.model_dump(mode="json")
    with _WRITE_LOCK:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
