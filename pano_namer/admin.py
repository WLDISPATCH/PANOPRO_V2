from __future__ import annotations

import importlib
import importlib.util
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from pano_namer.config import AppConfig
from pano_namer.security import hash_password

ADMIN_BASE_URL = "/admin"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sqlite_url(db_path: object) -> str:
    return f"sqlite:///{str(db_path)}"


def _admin_dependencies_available() -> bool:
    return all(
        importlib.util.find_spec(module_name) is not None
        for module_name in ("sqladmin", "sqlalchemy", "wtforms")
    )


def install_admin(app: FastAPI, cfg: AppConfig) -> None:
    """Install the private SQLAdmin backend portal.

    PANO PRO still uses the raw sqlite3 database layer for application code.
    This compatibility layer maps only the tables that need SQLAdmin support.
    """
    if not _admin_dependencies_available():
        app.state.admin_enabled = False

        @app.get(ADMIN_BASE_URL, include_in_schema=False)
        @app.get(f"{ADMIN_BASE_URL}/", include_in_schema=False)
        async def admin_dependencies_missing() -> HTMLResponse:
            return HTMLResponse(
                "SQLAdmin dependencies are not installed. Run `pip install -r requirements.txt` to enable /admin.",
                status_code=503,
            )

        return

    sqlalchemy = importlib.import_module("sqlalchemy")
    sqlalchemy_orm = importlib.import_module("sqlalchemy.orm")
    sqladmin = importlib.import_module("sqladmin")
    wtforms = importlib.import_module("wtforms")

    Base = sqlalchemy_orm.declarative_base()

    class User(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "users"

        id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
        username = sqlalchemy.Column(sqlalchemy.String, nullable=False, unique=True)
        email = sqlalchemy.Column(sqlalchemy.String)
        display_name = sqlalchemy.Column(sqlalchemy.String)
        password_hash = sqlalchemy.Column(sqlalchemy.String, nullable=False)
        is_active = sqlalchemy.Column(sqlalchemy.Integer, nullable=False, default=1)
        is_admin = sqlalchemy.Column(sqlalchemy.Integer, nullable=False, default=0)
        created_at = sqlalchemy.Column(sqlalchemy.String, nullable=False)
        updated_at = sqlalchemy.Column(sqlalchemy.String, nullable=False)

        def __str__(self) -> str:
            return self.username

    class UserAdmin(sqladmin.ModelView, model=User):  # type: ignore[misc]
        name = "User"
        name_plural = "Users"
        icon = "fa-solid fa-users"
        column_list = [
            User.id,
            User.username,
            User.email,
            User.display_name,
            User.is_active,
            User.is_admin,
            User.created_at,
            User.updated_at,
        ]
        column_searchable_list = [User.username, User.email, User.display_name]
        column_sortable_list = [User.id, User.username, User.email, User.created_at, User.updated_at]
        column_details_exclude_list = [User.password_hash]
        form_columns = [
            User.username,
            User.email,
            User.display_name,
            "password",
            User.is_active,
            User.is_admin,
        ]
        form_extra_fields = {"password": wtforms.PasswordField("Password")}

        async def on_model_change(self, data: dict, model: object, is_created: bool, request: object) -> None:
            now = _utc_now()
            password = str(data.pop("password", "") or "")
            if password:
                model.password_hash = hash_password(password)
            elif is_created:
                raise ValueError("Password is required when creating a user.")

            if is_created:
                model.created_at = now
            model.updated_at = now

    engine = sqlalchemy.create_engine(
        _sqlite_url(cfg.db_path.resolve().as_posix()),
        connect_args={"check_same_thread": False},
    )
    admin = sqladmin.Admin(app, engine, base_url=ADMIN_BASE_URL, title="PANO PRO Admin")
    admin.add_view(UserAdmin)
    app.state.admin_enabled = True
    app.state.admin_engine = engine
