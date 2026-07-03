from __future__ import annotations

import asyncio
import io
import json
import shutil
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from pano_namer.config import AppConfig
from pano_namer.main import create_app
from pano_namer.services.site_insight_preview import PreviewResult

TEST_TMP_ROOT = Path(".test_tmp")


def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for name, data in files.items():
            package.writestr(name, data)
    return buffer.getvalue()


async def asgi_request(
    app,
    method: str,
    path: str,
    *,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
):
    query_string = b""
    request_path = path
    if "?" in path:
        request_path, query = path.split("?", 1)
        query_string = query.encode()

    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": request_path,
        "raw_path": request_path.encode(),
        "query_string": query_string,
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "root_path": "",
    }
    messages = []
    sent_body = False

    async def receive():
        nonlocal sent_body
        if sent_body:
            return {"type": "http.disconnect"}
        sent_body = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    response_headers = {}
    for key, value in start["headers"]:
        response_headers.setdefault(key.decode(), []).append(value.decode())
    return start["status"], response_headers, response_body


class SiteInsightUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.base_dir = (TEST_TMP_ROOT / self.id().split(".")[-1]).resolve()
        self.app_data_dir = self.base_dir / "app-data"
        self.upload_dir = self.base_dir / "site-insight-uploads"
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def create_app(
        self, *, enabled: bool = True, max_mb: int = 250, auth_enabled: bool = False
    ):
        env = {
            "SITE_INSIGHT_ENABLED": "true" if enabled else "false",
            "SITE_INSIGHT_UPLOAD_DIR": str(self.upload_dir),
            "SITE_INSIGHT_MAX_UPLOAD_MB": str(max_mb),
            "PANOPRO_AUTH_ENABLED": "true" if auth_enabled else "false",
            "PANOPRO_AUTH_USERNAME": "owner",
            "PANOPRO_AUTH_PASSWORD": "secret-password",
            "PANOPRO_AUTH_SECRET": "test-signing-secret",
        }
        with patch.dict("os.environ", env, clear=False):
            app = create_app(AppConfig.load(self.app_data_dir))
        return app

    def request(
        self,
        app,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ):
        return asyncio.run(asgi_request(app, method, path, body=body, headers=headers))

    def upload(self, app, filename: str = "model.stl", data: bytes = b"solid model"):
        boundary = "----site-insight-test-boundary"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: model/stl\r\n\r\n"
            ).encode()
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        return self.request(
            app,
            "POST",
            "/api/site-insight/uploads",
            body=body,
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )

    def test_site_insight_disabled_hides_routes(self) -> None:
        app = self.create_app(enabled=False)

        self.assertEqual(self.request(app, "GET", "/site-insight")[0], 404)
        self.assertEqual(self.request(app, "GET", "/api/site-insight/uploads")[0], 404)
        self.assertEqual(
            self.request(
                app,
                "GET",
                "/site-insight/uploads/00000000-0000-0000-0000-000000000000/viewer",
            )[0],
            404,
        )

    def test_uploads_page_includes_view_action(self) -> None:
        app = self.create_app()

        status, headers, body = self.request(app, "GET", "/site-insight/uploads")

        self.assertEqual(status, 200)
        self.assertIn(
            b"/site-insight/uploads/${encodeURIComponent(item.upload_id)}/viewer", body
        )
        self.assertIn(b"View", body)
        self.assertIn(b"Download", body)
        self.assertIn(b"Delete", body)
        self.assertIn(b"method: 'DELETE'", body)

    def test_viewer_route_exists_when_enabled(self) -> None:
        app = self.create_app()
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(app, "model.ply", b"ply data")

        payload = json.loads(body)
        status, headers, body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/viewer"
        )

        self.assertEqual(status, 200)
        self.assertIn(b"SITE-INSIGHT Model Viewer", body)

    def test_raw_model_route_returns_original_file(self) -> None:
        app = self.create_app()
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(app, "model.ply", b"ply data")

        payload = json.loads(body)
        status, headers, body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/raw"
        )

        self.assertEqual(status, 200)
        self.assertEqual(body, b"ply data")

    def test_raw_model_route_404s_for_invalid_or_missing_upload(self) -> None:
        app = self.create_app()

        invalid_status, headers, body = self.request(
            app, "GET", "/site-insight/uploads/not-a-uuid/raw"
        )
        missing_status, headers, body = self.request(
            app, "GET", "/site-insight/uploads/00000000-0000-0000-0000-000000000000/raw"
        )

        self.assertEqual(invalid_status, 404)
        self.assertEqual(missing_status, 404)

    def test_viewer_html_includes_raw_model_url_and_filename(self) -> None:
        app = self.create_app()
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("succeeded", None),
        ):
            upload_status, headers, body = self.upload(
                app, "sample model.glb", b"glb data"
            )

        payload = json.loads(body)
        status, headers, body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/viewer"
        )

        self.assertEqual(status, 200)
        self.assertIn(
            f"/site-insight/uploads/{payload['upload_id']}/raw".encode(), body
        )
        self.assertIn(b"sample model.glb", body)
        self.assertIn(b"succeeded", body)

    def test_allowed_extension_succeeds_and_metadata_is_created_in_uuid_folder(
        self,
    ) -> None:
        app = self.create_app()

        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            status, headers, body = self.upload(app, "part.STL", b"solid model")

        self.assertEqual(status, 200)
        payload = json.loads(body)
        UUID(payload["upload_id"])
        upload_path = self.upload_dir / payload["upload_id"]
        self.assertTrue(upload_path.is_dir())
        self.assertTrue((upload_path / "original.stl").exists())
        metadata_path = upload_path / "metadata.json"
        self.assertTrue(metadata_path.exists())
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["stored_filename"], "original.stl")
        self.assertEqual(metadata["file_extension"], ".stl")
        self.assertEqual(metadata["sha256"], payload["sha256"])
        self.assertNotIn("/var/lib", json.dumps(payload))

    def test_delete_route_removes_upload_folder_and_list_entry(self) -> None:
        app = self.create_app()
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(app, "delete-me.ply", b"ply data")

        self.assertEqual(upload_status, 200)
        payload = json.loads(body)
        upload_path = self.upload_dir / payload["upload_id"]
        self.assertTrue(upload_path.is_dir())

        status, headers, body = self.request(
            app, "DELETE", f"/api/site-insight/uploads/{payload['upload_id']}"
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(body), {"deleted": True, "upload_id": payload["upload_id"]}
        )
        self.assertFalse(upload_path.exists())

        list_status, headers, list_body = self.request(
            app, "GET", "/api/site-insight/uploads"
        )
        self.assertEqual(list_status, 200)
        self.assertEqual(json.loads(list_body), [])

    def test_delete_route_returns_404_for_missing_upload(self) -> None:
        app = self.create_app()
        missing_id = "00000000-0000-0000-0000-000000000000"

        status, headers, body = self.request(
            app, "DELETE", f"/api/site-insight/uploads/{missing_id}"
        )

        self.assertEqual(status, 404)
        self.assertNotIn(str(self.upload_dir).encode(), body)

    def test_delete_route_rejects_invalid_upload_ids(self) -> None:
        app = self.create_app()

        status, headers, body = self.request(
            app, "DELETE", "/api/site-insight/uploads/not-a-uuid"
        )

        self.assertEqual(status, 404)
        self.assertNotIn(str(self.upload_dir).encode(), body)

    def test_delete_route_does_not_delete_outside_upload_root(self) -> None:
        app = self.create_app()
        outside_dir = self.base_dir / "outside-storage"
        outside_dir.mkdir()
        marker = outside_dir / "keep.txt"
        marker.write_text("do not delete", encoding="utf-8")
        symlink_id = str(uuid4())
        (self.upload_dir / symlink_id).symlink_to(outside_dir, target_is_directory=True)

        status, headers, body = self.request(
            app, "DELETE", f"/api/site-insight/uploads/{symlink_id}"
        )

        self.assertEqual(status, 404)
        self.assertTrue(outside_dir.is_dir())
        self.assertTrue(marker.exists())
        self.assertNotIn(str(outside_dir).encode(), body)

    def test_zip_upload_succeeds_and_extracts_package_metadata(self) -> None:
        app = self.create_app()
        package = make_zip(
            {
                "terra/model.obj": b"mtllib model.mtl\no mesh\nv 0 0 0\n",
                "terra/model.mtl": b"newmtl mat\nmap_Kd texture.jpg\n",
                "terra/texture.jpg": b"jpeg data",
            }
        )

        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            status, headers, body = self.upload(app, "terra-package.zip", package)

        self.assertEqual(status, 200)
        payload = json.loads(body)
        upload_path = self.upload_dir / payload["upload_id"]
        self.assertTrue((upload_path / "original.zip").exists())
        self.assertTrue((upload_path / "terra" / "model.obj").exists())
        self.assertEqual(payload["package_type"], "zip")
        self.assertEqual(payload["file_extension"], ".zip")
        self.assertEqual(payload["primary_model"]["path"], "terra/model.obj")
        self.assertEqual(payload["material_file"]["path"], "terra/model.mtl")
        self.assertEqual(payload["package_file_count"], 3)
        self.assertNotIn(str(self.upload_dir), json.dumps(payload))

    def test_zip_path_traversal_is_rejected(self) -> None:
        app = self.create_app()
        package = make_zip({"../evil.obj": b"obj data", "safe/model.obj": b"obj data"})

        status, headers, body = self.upload(app, "bad.zip", package)

        self.assertEqual(status, 400)
        self.assertEqual(list(self.upload_dir.iterdir()), [])
        self.assertFalse((self.upload_dir / "evil.obj").exists())

    def test_obj_mtl_jpg_package_detects_primary_model(self) -> None:
        app = self.create_app()
        package = make_zip(
            {
                "scene/cloud.ply": b"ply data",
                "scene/textured.obj": b"mtllib textured.mtl\no mesh\nv 0 0 0\n",
                "scene/textured.mtl": b"newmtl mat\nmap_Kd albedo.png\n",
                "scene/albedo.png": b"png data",
            }
        )

        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            status, headers, body = self.upload(app, "obj-package.zip", package)

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["primary_model"]["path"], "scene/textured.obj")
        self.assertEqual(payload["primary_model"]["extension"], ".obj")
        self.assertEqual(payload["material_file"]["path"], "scene/textured.mtl")

    def test_zip_with_two_obj_files_records_complete_tile_set(self) -> None:
        app = self.create_app()
        package = make_zip(
            {
                "Block0/Block0.obj": b"mtllib Block0.mtl\no tile0\nv 0 0 0\n",
                "Block0/Block0.mtl": b"newmtl mat0\nmap_Kd Block0.jpg\n",
                "Block0/Block0.jpg": b"jpg0",
                "Block1/Block1.obj": b"mtllib Block1.mtl\no tile1\nv 1 0 0\n",
                "Block1/Block1.mtl": b"newmtl mat1\nmap_Kd Block1.jpg\n",
                "Block1/Block1.jpg": b"jpg1",
            }
        )

        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            status, headers, body = self.upload(app, "terra-tiles.zip", package)

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["package_type"], "zip")
        self.assertEqual(payload["primary_model"]["path"], "Block0/Block0.obj")
        self.assertEqual(
            [item["path"] for item in payload["model_files"]],
            ["Block0/Block0.obj", "Block1/Block1.obj"],
        )
        self.assertEqual(
            [item["material_file"] for item in payload["model_files"]],
            ["Block0/Block0.mtl", "Block1/Block1.mtl"],
        )
        self.assertEqual(payload["model_files"][0]["extension"], ".obj")
        self.assertEqual(
            payload["model_files"][1]["asset_url"],
            f"/site-insight/uploads/{payload['upload_id']}/asset/Block1/Block1.obj",
        )

    def test_zip_with_multiple_obj_files_uses_shared_mtl_when_present(self) -> None:
        app = self.create_app()
        package = make_zip(
            {
                "tiles/Block0.obj": b"mtllib shared.mtl\no tile0\nv 0 0 0\n",
                "tiles/Block1.obj": b"mtllib shared.mtl\no tile1\nv 1 0 0\n",
                "tiles/shared.mtl": b"newmtl mat\nmap_Kd texture.jpg\n",
                "tiles/texture.jpg": b"jpg",
            }
        )

        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            status, headers, body = self.upload(app, "shared-mtl.zip", package)

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(len(payload["model_files"]), 2)
        self.assertEqual(
            {item["material_file"] for item in payload["model_files"]},
            {"tiles/shared.mtl"},
        )

    def test_viewer_html_includes_all_model_files_and_defaults_to_all_tiles(self) -> None:
        app = self.create_app()
        package = make_zip(
            {
                "Block0/Block0.obj": b"mtllib Block0.mtl\n",
                "Block0/Block0.mtl": b"map_Kd Block0.jpg\n",
                "Block0/Block0.jpg": b"jpg0",
                "Block1/Block1.obj": b"mtllib Block1.mtl\n",
                "Block1/Block1.mtl": b"map_Kd Block1.jpg\n",
                "Block1/Block1.jpg": b"jpg1",
            }
        )
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("succeeded", None),
        ):
            upload_status, headers, body = self.upload(
                app, "viewer-tiles.zip", package
            )

        payload = json.loads(body)
        status, headers, body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/viewer"
        )

        self.assertEqual(status, 200)
        self.assertIn(b"Package mode:</strong> Complete tile set", body)
        self.assertIn(b"Detected model tiles:</strong> 2", body)
        self.assertIn(b'"defaultViewMode": "all"', body)
        self.assertIn(b'"path": "Block0/Block0.obj"', body)
        self.assertIn(b'"path": "Block1/Block1.obj"', body)
        self.assertIn(b"loadObjTileSet(modelFiles)", body)
        self.assertIn(b"fitCameraToObject(camera, controls, modelRoot);", body)

    def test_single_obj_zip_still_defaults_to_single_model_view(self) -> None:
        app = self.create_app()
        package = make_zip(
            {
                "model.obj": b"mtllib model.mtl\n",
                "model.mtl": b"map_Kd texture.jpg\n",
                "texture.jpg": b"jpg",
            }
        )
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            status, headers, body = self.upload(app, "single-obj.zip", package)

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(len(payload["model_files"]), 1)

        viewer_status, headers, viewer_body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/viewer"
        )
        self.assertEqual(viewer_status, 200)
        self.assertIn(b'"defaultViewMode": "single"', viewer_body)
        self.assertIn(b"Package mode:</strong> Single model", viewer_body)

    def test_asset_route_serves_allowed_texture_files(self) -> None:
        app = self.create_app()
        package = make_zip(
            {
                "model.obj": b"mtllib model.mtl\n",
                "model.mtl": b"map_Kd texture.jpg\n",
                "texture.jpg": b"jpeg data",
            }
        )
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(
                app, "texture-package.zip", package
            )

        payload = json.loads(body)
        status, headers, body = self.request(
            app,
            "GET",
            f"/site-insight/uploads/{payload['upload_id']}/asset/texture.jpg",
        )

        self.assertEqual(status, 200)
        self.assertEqual(body, b"jpeg data")
        self.assertIn("image/jpeg", headers.get("content-type", [""])[0])

    def test_asset_route_only_serves_files_listed_in_metadata(self) -> None:
        app = self.create_app()
        package = make_zip(
            {
                "model.obj": b"mtllib model.mtl\n",
                "model.mtl": b"map_Kd texture.jpg\n",
                "texture.jpg": b"jpeg data",
            }
        )
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(
                app, "texture-package.zip", package
            )

        payload = json.loads(body)
        metadata_path = self.upload_dir / payload["upload_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["package_files"] = [
            item for item in metadata["package_files"] if item["path"] != "texture.jpg"
        ]
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        status, headers, body = self.request(
            app,
            "GET",
            f"/site-insight/uploads/{payload['upload_id']}/asset/texture.jpg",
        )

        self.assertEqual(status, 404)

    def test_asset_route_blocks_traversal(self) -> None:
        app = self.create_app()
        package = make_zip({"model.obj": b"obj data", "texture.jpg": b"jpeg data"})
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(
                app, "texture-package.zip", package
            )

        payload = json.loads(body)
        status, headers, body = self.request(
            app,
            "GET",
            f"/site-insight/uploads/{payload['upload_id']}/asset/../original.zip",
        )

        self.assertIn(status, {400, 404})

    def test_viewer_html_includes_package_asset_urls(self) -> None:
        app = self.create_app()
        package = make_zip(
            {
                "models/model.obj": b"mtllib model.mtl\n",
                "models/model.mtl": b"map_Kd texture.jpg\n",
                "models/texture.jpg": b"jpeg",
            }
        )
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("succeeded", None),
        ):
            upload_status, headers, body = self.upload(
                app, "viewer-package.zip", package
            )

        payload = json.loads(body)
        status, headers, body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/viewer"
        )

        self.assertEqual(status, 200)
        self.assertIn(
            f"/site-insight/uploads/{payload['upload_id']}/asset/models/model.obj".encode(),
            body,
        )
        self.assertIn(
            f"/site-insight/uploads/{payload['upload_id']}/asset/models/model.mtl".encode(),
            body,
        )
        self.assertIn(b"MTLLoader", body)

    def test_viewer_html_includes_orientation_control_and_z_up_default(self) -> None:
        app = self.create_app()
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(app, "terra.obj", b"obj data")

        self.assertEqual(upload_status, 200)
        payload = json.loads(body)
        status, headers, body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/viewer"
        )

        self.assertEqual(status, 200)
        self.assertIn(b'<label for="orientation">Orientation</label>', body)
        self.assertIn(
            b'<option value="z-up" selected>Z-up / Survey / Terra</option>', body
        )
        self.assertIn(b'<option value="y-up">Y-up / Three.js</option>', body)
        self.assertIn(b'<option value="x-up">X-up / Experimental</option>', body)
        self.assertIn(b'"defaultOrientation": "z-up"', body)
        self.assertIn(b"If your model appears vertical, switch orientation.", body)

    def test_viewer_javascript_includes_z_up_transform_and_refit(self) -> None:
        app = self.create_app()
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(app, "survey.ply", b"ply data")

        self.assertEqual(upload_status, 200)
        payload = json.loads(body)
        status, headers, body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/viewer"
        )

        self.assertEqual(status, 200)
        self.assertIn(b"root.rotation.set(-Math.PI / 2, 0, 0);", body)
        self.assertIn(b"localStorage.setItem(orientationStorageKey, orientation);", body)
        self.assertIn(b"fitCameraToObject(camera, controls, modelRoot);", body)
        self.assertIn(b"controls.target.copy(center);", body)

    def test_disallowed_extension_fails(self) -> None:
        app = self.create_app()

        status, headers, body = self.upload(app, "notes.txt", b"not a model")

        self.assertEqual(status, 400)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_filename_path_traversal_is_neutralized(self) -> None:
        app = self.create_app()

        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            status, headers, body = self.upload(app, "../../evil.obj", b"obj data")

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["original_filename"], "evil.obj")
        self.assertEqual(payload["stored_filename"], "original.obj")
        self.assertTrue(
            (self.upload_dir / payload["upload_id"] / "original.obj").exists()
        )
        self.assertFalse((self.upload_dir / "evil.obj").exists())

    def test_file_size_limit_is_enforced(self) -> None:
        app = self.create_app(max_mb=1)

        status, headers, body = self.upload(
            app, "too-large.stl", (1024 * 1024 + 1) * b"x"
        )

        self.assertEqual(status, 413)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_missing_f3d_does_not_fail_upload(self) -> None:
        app = self.create_app()

        with patch(
            "pano_namer.services.site_insight_preview.shutil.which", return_value=None
        ):
            status, headers, body = self.upload(app, "model.ply", b"ply data")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["preview_status"], "skipped")

    def test_f3d_failure_does_not_fail_upload(self) -> None:
        app = self.create_app()

        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("failed", "egl failed; osmesa failed"),
        ):
            status, headers, body = self.upload(app, "model.glb", b"glb data")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["preview_status"], "failed")

    def test_preview_route_returns_404_when_no_preview_exists(self) -> None:
        app = self.create_app()
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(app, "model.step", b"step data")

        payload = json.loads(body)
        status, headers, body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/preview.png"
        )

        self.assertEqual(status, 404)

    def test_download_route_returns_original_file(self) -> None:
        app = self.create_app()
        with patch(
            "pano_namer.services.site_insight_uploads.generate_preview",
            return_value=PreviewResult("skipped", "F3D is not installed."),
        ):
            upload_status, headers, body = self.upload(app, "model.3mf", b"3mf data")

        payload = json.loads(body)
        status, headers, body = self.request(
            app, "GET", f"/site-insight/uploads/{payload['upload_id']}/download"
        )

        self.assertEqual(status, 200)
        self.assertEqual(body, b"3mf data")
        self.assertIn("model.3mf", headers.get("content-disposition", [""])[0])

    def test_site_insight_routes_remain_behind_existing_auth_gate(self) -> None:
        app = self.create_app(enabled=True, auth_enabled=True)

        status, headers, body = self.request(app, "GET", "/site-insight")
        raw_status, raw_headers, raw_body = self.request(
            app, "GET", "/site-insight/uploads/00000000-0000-0000-0000-000000000000/raw"
        )
        asset_status, asset_headers, asset_body = self.request(
            app,
            "GET",
            "/site-insight/uploads/00000000-0000-0000-0000-000000000000/asset/texture.jpg",
        )
        delete_status, delete_headers, delete_body = self.request(
            app,
            "DELETE",
            "/api/site-insight/uploads/00000000-0000-0000-0000-000000000000",
        )

        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], ["/login?next=%2Fsite-insight"])
        self.assertEqual(raw_status, 303)
        self.assertEqual(
            raw_headers["location"],
            [
                "/login?next=%2Fsite-insight%2Fuploads%2F00000000-0000-0000-0000-000000000000%2Fraw"
            ],
        )
        self.assertEqual(asset_status, 303)
        self.assertEqual(
            asset_headers["location"],
            [
                "/login?next=%2Fsite-insight%2Fuploads%2F00000000-0000-0000-0000-000000000000%2Fasset%2Ftexture.jpg"
            ],
        )
        self.assertEqual(delete_status, 303)
        self.assertEqual(
            delete_headers["location"],
            [
                "/login?next=%2Fapi%2Fsite-insight%2Fuploads%2F00000000-0000-0000-0000-000000000000"
            ],
        )


if __name__ == "__main__":
    unittest.main()
