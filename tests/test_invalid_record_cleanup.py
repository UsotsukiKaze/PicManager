from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.services import ImageService


def test_delete_invalid_records_removes_dependent_tracking_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cleanup.db'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        group = models.Group(name="group")
        character = models.Character(name="character", group=group)
        image = models.Image(
            image_id="1111111111",
            file_extension="png",
            file_path=str(tmp_path / "already-missing.png"),
            file_status=ImageService.ARCHIVED,
            characters=[character],
        )
        db.add_all([
            image,
            models.ImageViewCount(image_id=image.image_id, view_count=12),
            models.DuplicatePairDecision(
                pair_key="1111111111:2222222222",
                left_image_id=image.image_id,
                right_image_id="2222222222",
            ),
        ])
        db.commit()

        deleted = ImageService.cleanup_orphaned_records(db, str(tmp_path), mode="delete")

        assert deleted == 1
        assert db.get(models.Image, image.image_id) is None
        assert db.query(models.ImageViewCount).count() == 0
        assert db.query(models.DuplicatePairDecision).count() == 0
        assert character.images == []
