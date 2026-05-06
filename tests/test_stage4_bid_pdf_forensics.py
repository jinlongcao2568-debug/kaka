from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.bid_pdf_forensics import (
    IMAGE_HEAVY_BID_FILE,
    MIXED_TEXT_IMAGE_BID_FILE,
    OBSERVED_REPEATED_STAMP_IMAGE,
    TEXT_LAYER_PRESENT,
    build_forensics_markdown,
    classify_image_heavy_bid_file,
    detect_red_stamp_candidates,
    hamming_hex,
    visual_hashes,
)


class Stage4BidPdfForensicsTests(unittest.TestCase):
    def test_red_stamp_candidate_detected(self) -> None:
        image = Image.new("RGB", (320, 320), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((90, 90, 230, 230), outline=(205, 0, 0), width=8)
        draw.line((120, 160, 200, 160), fill=(205, 0, 0), width=5)
        draw.line((160, 120, 160, 200), fill=(205, 0, 0), width=5)

        candidates = detect_red_stamp_candidates(image, page_no=1, company="测试公司")

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["page_no"], 1)
        self.assertIn("dhash", candidates[0])
        self.assertIn("phash", candidates[0])

    def test_small_red_text_noise_not_stamp_candidate(self) -> None:
        image = Image.new("RGB", (320, 320), "white")
        draw = ImageDraw.Draw(image)
        for index in range(12):
            x = 20 + index * 22
            draw.rectangle((x, 80, x + 8, 88), fill=(220, 0, 0))

        candidates = detect_red_stamp_candidates(image, page_no=1, company="测试公司")

        self.assertEqual(candidates, [])

    def test_no_red_page_has_no_stamp_candidate(self) -> None:
        image = Image.new("RGB", (320, 320), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 80, 220, 220), outline=(0, 0, 0), width=3)

        candidates = detect_red_stamp_candidates(image, page_no=1, company="测试公司")

        self.assertEqual(candidates, [])

    def test_visual_hash_is_stable_under_resize(self) -> None:
        image = Image.new("RGB", (220, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((40, 30, 160, 150), outline=(200, 0, 0), width=8)
        resized = image.resize((330, 270))

        left = visual_hashes(image)
        right = visual_hashes(resized)

        self.assertLessEqual(hamming_hex(left["dhash"], right["dhash"]), 8)
        self.assertLessEqual(hamming_hex(left["phash"], right["phash"]), 12)

    def test_visual_hash_distinguishes_different_image(self) -> None:
        left_image = Image.new("RGB", (220, 180), "white")
        left_draw = ImageDraw.Draw(left_image)
        left_draw.ellipse((40, 30, 160, 150), outline=(200, 0, 0), width=8)
        right_image = Image.new("RGB", (220, 180), "white")
        right_draw = ImageDraw.Draw(right_image)
        right_draw.rectangle((30, 30, 180, 120), fill=(20, 20, 20))

        left = visual_hashes(left_image)
        right = visual_hashes(right_image)

        self.assertGreater(hamming_hex(left["dhash"], right["dhash"]), 8)

    def test_image_heavy_classification(self) -> None:
        self.assertEqual(
            classify_image_heavy_bid_file(
                page_count=100,
                text_layer_page_count=10,
                pages_with_images=95,
                text_chars_total=500,
            ),
            IMAGE_HEAVY_BID_FILE,
        )
        self.assertEqual(
            classify_image_heavy_bid_file(
                page_count=100,
                text_layer_page_count=70,
                pages_with_images=50,
                text_chars_total=20000,
            ),
            MIXED_TEXT_IMAGE_BID_FILE,
        )
        self.assertEqual(
            classify_image_heavy_bid_file(
                page_count=100,
                text_layer_page_count=95,
                pages_with_images=5,
                text_chars_total=60000,
            ),
            TEXT_LAYER_PRESENT,
        )

    def test_markdown_uses_cautious_language(self) -> None:
        markdown = build_forensics_markdown(
            {
                "records": [
                    {
                        "company": "测试公司",
                        "page_count": 1,
                        "image_heavy_state": IMAGE_HEAVY_BID_FILE,
                        "text_layer_page_count": 0,
                        "low_text_page_count": 1,
                        "stamp_candidate_count": 2,
                        "stamp_repeated_candidate_count": 2,
                        "forensic_statuses": [OBSERVED_REPEATED_STAMP_IMAGE],
                        "official_check_recommendations": ["仅作内部复核，不作违法废标结论"],
                        "project_manager_qualification_readback": {
                            "stage5_qualification_overall_status": "NOT_CONFIRMED"
                        },
                    }
                ],
                "status_counts": {OBSERVED_REPEATED_STAMP_IMAGE: 1},
                "stamp_clusters": [],
                "pairwise_similarity": [],
            }
        )

        for term in ("造假", "违法", "围标", "废标"):
            self.assertNotIn(term, markdown)
        self.assertIn("内部复核", markdown)


if __name__ == "__main__":
    unittest.main()
