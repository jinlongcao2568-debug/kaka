from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.jzsc_browser_executor import (
    JZSC_COMPANY_SEARCH_DOM_OR_API_STRUCTURE_CHANGED,
    JZSC_COMPANY_SEARCH_LOADED_BUT_NO_VUE_DATA,
    JZSC_COMPANY_SEARCH_OK_COMPANY_ROW_MATCHED,
    JZSC_COMPANY_SEARCH_PAGE_NOT_LOADED,
    JZSC_COMPANY_SEARCH_PARAMETER_INVALID_OR_NOT_APPLIED,
    JZSC_COMPANY_SEARCH_PUBLIC_PLATFORM_EMPTY_RESULT,
    JZSC_COMPANY_SEARCH_ROWS_RETURNED_WITHOUT_TARGET_MATCH,
    JZSC_COMPANY_SEARCH_SUSPECTED_CAPTCHA_OR_ACCESS_BLOCK,
    classify_jzsc_company_search_diagnostics,
)


class Stage4JzscSourceHealthTests(unittest.TestCase):
    def test_control_company_rows_with_match_passes(self) -> None:
        result = classify_jzsc_company_search_diagnostics(
            page_loaded=True,
            body_text="企业名称 中铁五局集团有限公司",
            target_company_name="中铁五局集团有限公司",
            query_parameter_present=True,
            vue_component_count=3,
            company_row_count=1,
            company_match_found=True,
        )

        self.assertEqual(result["diagnostic_state"], "PASS")
        self.assertEqual(
            result["diagnostic_status_code"],
            JZSC_COMPANY_SEARCH_OK_COMPANY_ROW_MATCHED,
        )
        self.assertEqual(result["failure_reasons"], [])

    def test_page_not_loaded_is_classified(self) -> None:
        result = classify_jzsc_company_search_diagnostics(
            page_loaded=False,
            body_text="",
            target_company_name="中铁五局集团有限公司",
            query_parameter_present=True,
        )

        self.assertEqual(result["diagnostic_state"], "FAIL_CLOSED_QUERY_ERROR")
        self.assertIn(JZSC_COMPANY_SEARCH_PAGE_NOT_LOADED, result["failure_reasons"])

    def test_loaded_without_vue_data_is_classified(self) -> None:
        result = classify_jzsc_company_search_diagnostics(
            page_loaded=True,
            body_text="全国建筑市场监管公共服务平台",
            target_company_name="中铁五局集团有限公司",
            query_parameter_present=True,
            vue_component_count=0,
            company_row_count=0,
        )

        self.assertEqual(result["diagnostic_state"], "FAIL_CLOSED_QUERY_ERROR")
        self.assertIn(
            JZSC_COMPANY_SEARCH_LOADED_BUT_NO_VUE_DATA,
            result["failure_reasons"],
        )

    def test_public_empty_result_is_classified(self) -> None:
        result = classify_jzsc_company_search_diagnostics(
            page_loaded=True,
            body_text="暂无数据",
            target_company_name="不存在企业",
            query_parameter_present=True,
            vue_component_count=2,
            company_row_count=0,
        )

        self.assertEqual(result["diagnostic_state"], "FAIL_CLOSED_QUERY_ERROR")
        self.assertIn(
            JZSC_COMPANY_SEARCH_PUBLIC_PLATFORM_EMPTY_RESULT,
            result["failure_reasons"],
        )

    def test_challenge_is_fail_closed_review_required(self) -> None:
        result = classify_jzsc_company_search_diagnostics(
            page_loaded=True,
            body_text="请完成验证 拖动滑块",
            target_company_name="中铁五局集团有限公司",
            query_parameter_present=True,
            challenge_state="captcha_or_slider_manual_required",
            vue_component_count=1,
            company_row_count=0,
        )

        self.assertEqual(result["diagnostic_state"], "BLOCKED_REVIEW_REQUIRED")
        self.assertIn(
            JZSC_COMPANY_SEARCH_SUSPECTED_CAPTCHA_OR_ACCESS_BLOCK,
            result["failure_reasons"],
        )

    def test_query_parameter_problem_and_dom_change_are_classified(self) -> None:
        result = classify_jzsc_company_search_diagnostics(
            page_loaded=True,
            body_text="全国建筑市场监管公共服务平台",
            target_company_name="中铁五局集团有限公司",
            query_parameter_present=False,
            vue_component_count=2,
            company_row_count=0,
            extraction_error="tableData field missing",
        )

        self.assertIn(
            JZSC_COMPANY_SEARCH_PARAMETER_INVALID_OR_NOT_APPLIED,
            result["failure_reasons"],
        )
        self.assertIn(
            JZSC_COMPANY_SEARCH_DOM_OR_API_STRUCTURE_CHANGED,
            result["failure_reasons"],
        )

    def test_rows_without_target_match_requires_review(self) -> None:
        result = classify_jzsc_company_search_diagnostics(
            page_loaded=True,
            body_text="企业名称 其他公司",
            target_company_name="中铁五局集团有限公司",
            query_parameter_present=True,
            vue_component_count=3,
            company_row_count=2,
            company_match_found=False,
        )

        self.assertEqual(result["diagnostic_state"], "FAIL_CLOSED_QUERY_ERROR")
        self.assertIn(
            JZSC_COMPANY_SEARCH_ROWS_RETURNED_WITHOUT_TARGET_MATCH,
            result["failure_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
