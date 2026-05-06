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
    _solve_blockpuzzle_offset,
)


GZ_ATTACHMENT_URL = (
    "https://ywtb.gzggzy.cn/EpointWebBuilder/pages/webbuildermis/attach/downloadztbattach?"
    "attachGuid=568108d4-62ef-4407-83dc-a35d11c5f0f2&appUrlFlag=f2025tp"
    "&siteGuid=7eb5f7f1-9041-43ad-8e13-8fcb82ea831a"
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


if __name__ == "__main__":
    unittest.main()
