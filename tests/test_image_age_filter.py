from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.public_api import images


def test_image_search_forwards_age_rating_to_service(monkeypatch):
    captured = {}

    def fake_search(_db, params):
        captured["age_rating"] = params.age_rating
        return [], 0

    monkeypatch.setattr(images.ImageService, "search_images", fake_search)
    app = FastAPI()
    app.include_router(images.router)

    response = TestClient(app).get("/images/search?age_rating=r18")

    assert response.status_code == 200
    assert captured["age_rating"] == "r18"


def test_image_search_rejects_unknown_age_rating():
    app = FastAPI()
    app.include_router(images.router)

    response = TestClient(app).get("/images/search?age_rating=unknown")

    assert response.status_code == 422


def test_image_management_exposes_age_filter_tabs():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    html = (project_root / "static/index.html").read_text(encoding="utf-8")
    ui_source = (project_root / "static/js/ui.js").read_text(encoding="utf-8")

    assert 'id="search-age-rating"' in html
    assert 'data-age-rating="r18"' in html
    assert "age_rating: document.getElementById('search-age-rating')" in ui_source
    assert "function setAgeRatingFilter(rating, activeButton)" in ui_source
