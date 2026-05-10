from __future__ import annotations

import base64
import sys
import unittest
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage2_ingestion.playwright_challenge_resolver import (
    _build_blockpuzzle_track,
    _epoint_attachment_action_url,
    _epoint_jigsaw_captcha_url,
    _filename_from_content_disposition,
    _guangzhou_ywtb_discovery_failure_taxonomy,
    _guangzhou_ywtb_download_discovery_state,
    _guangzhou_ywtb_download_url,
    _guangdong_ygp_download_signature_params,
    _guangdong_ygp_download_url,
    _solve_blockpuzzle_offset,
)


GZ_ATTACHMENT_URL = (
    "https://ywtb.gzggzy.cn/EpointWebBuilder/pages/webbuildermis/attach/downloadztbattach?"
    "attachGuid=568108d4-62ef-4407-83dc-a35d11c5f0f2&appUrlFlag=f2025tp"
    "&siteGuid=7eb5f7f1-9041-43ad-8e13-8fcb82ea831a"
)
GD_YGP_ATTACHMENT_URL = (
    "https://ygp.gdzwfw.gov.cn/ggzy-portal/base/sys-file/download/v3/"
    "e1633e95-9630-48e3-95fb-17e38a18cba0--3C14?1696027"
)
JS_ATTACHMENT_URL = (
    "http://jsggzy.jszwfw.gov.cn/EpointWebBuilder_jsggzy/pages/webbuildermis/attach/"
    "downloadZtbAttach.jspx?attachGuid=js-attach-001&appUrlFlag=js2026"
    "&siteGuid=js-site-001"
)


def _png_base64(image: object) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class PlaywrightChallengeResolverHelperTests(unittest.TestCase):
    def test_epoint_jigsaw_urls_target_same_public_site_context(self) -> None:
        action_url = _epoint_attachment_action_url(
            GZ_ATTACHMENT_URL,
            verification_code="blockpuzzle@captcha@validated",
            verification_guid="blockpuzzle@captcha@validated",
        )

        parsed = urlsplit(action_url)
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "ywtb.gzggzy.cn")
        self.assertTrue(parsed.path.endswith("/ztbAttachDownloadAction.action"))
        self.assertEqual(params["cmd"], ["getContent"])
        self.assertEqual(params["attachGuid"], ["568108d4-62ef-4407-83dc-a35d11c5f0f2"])
        self.assertEqual(params["verificationCode"], ["blockpuzzle@captcha@validated"])
        self.assertEqual(_epoint_jigsaw_captcha_url(GZ_ATTACHMENT_URL), "https://ywtb.gzggzy.cn/EpointWebBuilder/rest/shellcaptcha/initAndCheckCaptcha")

    def test_epoint_jsggzy_jspx_urls_target_builder_variant(self) -> None:
        action_url = _epoint_attachment_action_url(
            JS_ATTACHMENT_URL,
            verification_code="validated",
            verification_guid="validated",
        )

        parsed = urlsplit(action_url)
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.netloc, "jsggzy.jszwfw.gov.cn")
        self.assertTrue(parsed.path.endswith("/EpointWebBuilder_jsggzy/pages/webbuildermis/attach/ztbAttachDownloadAction.action"))
        self.assertEqual(params["attachGuid"], ["js-attach-001"])
        self.assertEqual(
            _epoint_jigsaw_captcha_url(JS_ATTACHMENT_URL),
            "http://jsggzy.jszwfw.gov.cn/EpointWebBuilder_jsggzy/rest/shellcaptcha/initAndCheckCaptcha",
        )

    def test_blockpuzzle_solver_finds_edge_aligned_gap_and_builds_track(self) -> None:
        try:
            from PIL import Image, ImageDraw
        except Exception as exc:  # pragma: no cover - optional dependency
            self.skipTest(f"PIL unavailable: {exc}")

        source_x = 240
        original = Image.new("RGB", (600, 300), "black")
        draw = ImageDraw.Draw(original)
        draw.rectangle((source_x + 10, 120, source_x + 70, 190), outline="white", width=4)

        piece = Image.new("RGBA", (90, 300), (0, 0, 0, 0))
        piece_draw = ImageDraw.Draw(piece)
        piece_draw.rectangle((10, 120, 70, 190), fill=(255, 255, 255, 255))

        solution = _solve_blockpuzzle_offset(_png_base64(original), _png_base64(piece))
        self.assertAlmostEqual(float(solution["offset_x"]), source_x / 600, delta=0.02)

        track = _build_blockpuzzle_track(source_x=int(solution["source_x"]), original_width=600)
        self.assertGreaterEqual(len(track), 30)
        self.assertIn("x", track[-1])
        self.assertIn("y", track[-1])
        self.assertGreater(track[-1]["x"], 0)

    def test_content_disposition_filename_is_sanitized(self) -> None:
        self.assertEqual(
            _filename_from_content_disposition("attachment; filename*=UTF-8''%E8%AF%84%E6%A0%87.pdf"),
            "评标.pdf",
        )
        self.assertEqual(
            _filename_from_content_disposition('attachment; filename="bad/name.pdf"'),
            "bad_name.pdf",
        )

    def test_guangdong_ygp_download_url_and_signature_params_are_parsed(self) -> None:
        self.assertTrue(_guangdong_ygp_download_url(GD_YGP_ATTACHMENT_URL))
        params = _guangdong_ygp_download_signature_params(GD_YGP_ATTACHMENT_URL)
        self.assertEqual(params["version"], "v3")
        self.assertEqual(params["rowGuid"], "e1633e95-9630-48e3-95fb-17e38a18cba0--3C14")
        self.assertEqual(params["flowId"], "1696027")

    def test_guangzhou_download_diagnosis_classifies_endpoint_and_blockers(self) -> None:
        self.assertTrue(_guangzhou_ywtb_download_url(GZ_ATTACHMENT_URL))
        self.assertEqual(
            _guangzhou_ywtb_download_discovery_state(body_text="", html="", candidate_count=1),
            "DOWNLOAD_ENDPOINT_CAPTURED",
        )
        self.assertEqual(
            _guangzhou_ywtb_download_discovery_state(
                body_text="请使用CA证书登录后下载招标文件",
                html="",
                candidate_count=0,
            ),
            "LOGIN_OR_CA_REQUIRED",
        )
        self.assertEqual(
            _guangzhou_ywtb_discovery_failure_taxonomy("NO_PUBLIC_DOWNLOAD_ENDPOINT"),
            ["guangzhou_public_download_endpoint_missing"],
        )


if __name__ == "__main__":
    unittest.main()
