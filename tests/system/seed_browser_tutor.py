from __future__ import annotations

from sqlalchemy import update

from learn_platform_api.db.models import Workspace
from learn_platform_api.db.session import SessionLocal

from test_tutor_vertical import _seed_reader_fixture, _wait_for_environment


def main() -> None:
    _wait_for_environment()
    fixture = _seed_reader_fixture()
    with SessionLocal() as db:
        db.execute(
            update(Workspace)
            .where(Workspace.id == fixture["workspace_id"])
            .values(
                name="System Tutor Browser",
                description="Controlled browser smoke fixture",
            )
        )
        db.commit()


if __name__ == "__main__":
    main()
