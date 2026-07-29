from __future__ import annotations

import io
import json
import unittest
import zipfile
from unittest.mock import patch

from pypdf import PdfReader
from reportlab.pdfbase.ttfonts import TTFError

import stage7_sales.fixed_sku_evidence_bundle as bundle_module
from stage7_sales.customer_delivery_boundary import (
    assert_customer_delivery_payload_safe,
    customer_delivery_disclaimer_texts,
)
from stage7_sales.fixed_sku_evidence_bundle import (
    SKU_CODE,
    SKU_NAME,
    SKU_VERSION,
    build_fixed_sku_evidence_bundle,
)


class FixedSkuEvidenceBundleTests(unittest.TestCase):
    def test_pdf_font_registration_skips_incompatible_candidates(self) -> None:
        compatible_font = object()
        with (
            patch.object(bundle_module.pdfmetrics, "getRegisteredFontNames", return_value=[]),
            patch.object(bundle_module.Path, "is_file", return_value=True),
            patch.object(
                bundle_module,
                "TTFont",
                side_effect=[TTFError("unsupported outlines"), compatible_font],
            ) as font_factory,
            patch.object(bundle_module.pdfmetrics, "registerFont") as register_font,
            patch.dict(
                bundle_module.os.environ,
                {"KAKA_EVIDENCE_PDF_FONT_FILE": ""},
            ),
        ):
            bundle_module._register_pdf_font()

        self.assertEqual(font_factory.call_count, 2)
        register_font.assert_called_once_with(compatible_font)

    def test_bundle_contains_pdf_html_manifest_hashes_and_fail_closed_issuance_controls(self) -> None:
        package = {
            "项目编号": "PROJ-PROD-001",
            "商机编号": "OPP-PROD-001",
            "数据真实性边界": {
                "是否离线样本": False,
                "是否真实市场发现": True,
                "客户可交付判断": "真实公开来源已固定，仍需人工复核。",
            },
            "公开来源验证": {
                "公开来源网址": "https://example.gov.cn/project/123",
                "公开来源名称": "示例公共资源交易平台",
                "来源配置编号": "CN-GD-EXAMPLE",
                "项目名称": "示例公共建筑工程",
                "地区": "广东广州",
                "项目类型": "房建工程",
                "查询时点": "2026-07-19T10:00:00+08:00",
                "快照SHA256": "a" * 64,
                "验证口径": "核对项目名称、公告阶段和负责人。",
            },
            "证据包": {
                "证据包编号": "EVP-PROD-001",
                "交付包编号": "LP-PROD-001",
                "清单编号": "MAN-PROD-001",
                "版本哈希": "sha256:" + "b" * 64,
            },
            "证据项清单": [
                {
                    "证据项编号": "EVD-001",
                    "证据类型": "施工许可",
                    "线索类型": "公开官方来源",
                    "证据等级": "B",
                    "核验状态": "MATCHED",
                    "证据说明": "已回读施工许可项目记录。",
                    "客户交付判断": "可供人工复核，不构成法律结论。",
                    "阻断原因": "当前记录仅供人工复核。",
                    "下一步": "复核原文并由签发人确认。",
                    "公开来源网址": "https://example.gov.cn/project/123",
                    "公开来源名称": "示例公共资源交易平台",
                    "快照SHA256": "c" * 64,
                    "来源引用": ["SNAP-PROD-001"],
                    "脱敏策略": "MASKING_REQUIRED",
                }
            ],
            "字段策略": {
                "字段白名单已执行": True,
                "脱敏必需": True,
                "内部黑箱字段已隐藏": True,
            },
        }
        base_item = dict(package["证据项清单"][0])
        package["证据项清单"] = [
            {
                **base_item,
                "证据项编号": f"EVD-{index:03d}",
                "证据类型": evidence_type,
                "快照SHA256": str(index) * 64,
            }
            for index, evidence_type in enumerate(
                ("施工许可", "竣工验收", "项目经理变更", "合同履约"),
                start=1,
            )
        ]
        approval = {
            "审批请求编号": "APR-PROD-001",
            "审批对象版本一致": True,
            "职责分离已满足": True,
            "下载执行审计编号": "APREXEC-PROD-001",
        }

        result = build_fixed_sku_evidence_bundle(
            package,
            approval_audit=approval,
            generated_at="2026-07-19T10:05:00+08:00",
        )

        self.assertEqual(result["media_type"], "application/zip")
        self.assertTrue(result["filename"].endswith(".zip"))
        self.assertEqual(len(result["bundle_sha256"]), 64)
        with zipfile.ZipFile(io.BytesIO(result["bytes"])) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"README.txt", "evidence-pack.html", "evidence-pack.pdf", "manifest.json"},
            )
            manifest = json.loads(archive.read("manifest.json"))
            html_text = archive.read("evidence-pack.html").decode("utf-8")
            pdf_bytes = archive.read("evidence-pack.pdf")
            readme_text = archive.read("README.txt").decode("utf-8")

        self.assertEqual(manifest["sku"]["sku_code"], SKU_CODE)
        self.assertEqual(manifest["project_id"], "PROJ-PROD-001")
        self.assertEqual(manifest["sku"]["sku_name"], SKU_NAME)
        self.assertEqual(manifest["sku"]["sku_version"], SKU_VERSION)
        self.assertEqual(manifest["issuance_control"]["manual_signoff_state"], "READY_FOR_HUMAN_SIGNOFF")
        self.assertFalse(manifest["issuance_control"]["customer_release_authorized"])
        self.assertFalse(manifest["delivery_audit"]["external_delivery_executed"])
        self.assertEqual(manifest["evidence_items"][0]["evidence_grade"], "B")
        self.assertEqual(manifest["evidence_items"][0]["blocking_reason"], "当前记录仅供人工复核。")
        self.assertEqual(manifest["evidence_items"][0]["next_step"], "复核原文并由签发人确认。")
        self.assertTrue(manifest["verification_coverage"]["complete"])
        self.assertIn("NOT_FOUND", " ".join(manifest["disclaimers"]))
        self.assertEqual(
            manifest["customer_delivery_boundary"]["contract_id"],
            "customer_delivery_boundary_contract",
        )
        self.assertFalse(
            manifest["customer_delivery_boundary"]["automatic_email_delivery_enabled"]
        )
        self.assertFalse(
            manifest["customer_delivery_boundary"]["customer_self_service_download_enabled"]
        )
        self.assertNotIn("审批请求编号", manifest["delivery_audit"]["approval_audit"])
        self.assertNotIn("field_blacklist", manifest["field_policy"])
        self.assertIn("人工签发前不得交付", html_text)
        for disclaimer in customer_delivery_disclaimer_texts():
            self.assertIn(disclaimer, html_text)
            self.assertIn(disclaimer, readme_text)
        self.assertNotIn("<script", html_text.lower())
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
        self.assertIn("SKU-B", pdf_text)
        self.assertIn("NOT_FOUND", pdf_text)
        self.assertIn("客户交付与责任边界", pdf_text)
        self.assertIn("不是法律意见", pdf_text)

    def test_offline_sample_remains_blocked_before_human_signoff(self) -> None:
        result = build_fixed_sku_evidence_bundle(
            {
                "商机编号": "OPP-OFFLINE",
                "数据真实性边界": {"是否离线样本": True},
                "公开来源验证": {"公开来源网址": ""},
                "证据包": {"版本哈希": "sha256:" + "d" * 64},
                "证据项清单": [],
            },
            approval_audit={"审批对象版本一致": True, "职责分离已满足": True},
            generated_at="2026-07-19T10:05:00+08:00",
        )

        control = result["manifest"]["issuance_control"]
        self.assertEqual(control["manual_signoff_state"], "BLOCKED_BEFORE_HUMAN_SIGNOFF")
        self.assertIn("real_public_source_required", control["missing_issuance_fields"])
        self.assertIn("public_source_url", control["missing_issuance_fields"])
        self.assertIn("evidence_items", control["missing_issuance_fields"])
        self.assertFalse(control["customer_release_authorized"])

    def test_four_type_coverage_without_required_item_fields_stays_blocked(self) -> None:
        result = build_fixed_sku_evidence_bundle(
            {
                "商机编号": "OPP-INCOMPLETE",
                "数据真实性边界": {"是否离线样本": False},
                "公开来源验证": {
                    "公开来源网址": "https://example.gov.cn/project/incomplete",
                    "查询时点": "2026-07-19T10:00:00+08:00",
                    "快照SHA256": "a" * 64,
                },
                "证据包": {"版本哈希": "sha256:" + "b" * 64},
                "证据项清单": [
                    {"证据项编号": f"EVD-{index}", "证据类型": evidence_type}
                    for index, evidence_type in enumerate(
                        ("施工许可", "竣工验收", "项目经理变更", "合同履约"),
                        start=1,
                    )
                ],
            },
            approval_audit={"审批对象版本一致": True, "职责分离已满足": True},
            generated_at="2026-07-19T10:05:00+08:00",
        )

        control = result["manifest"]["issuance_control"]
        self.assertEqual(control["manual_signoff_state"], "BLOCKED_BEFORE_HUMAN_SIGNOFF")
        self.assertFalse(result["manifest"]["verification_coverage"]["complete"])
        self.assertIn("evidence_item:EVD-1:verification_state", control["missing_issuance_fields"])
        self.assertIn("evidence_item:EVD-1:blocking_reason", control["missing_issuance_fields"])

    def test_formal_bundle_removes_internal_identity_and_blackbox_field_names(self) -> None:
        result = build_fixed_sku_evidence_bundle(
            {
                "项目编号": "PROJ-SAFE-001",
                "商机编号": "OPP-SAFE-001",
                "数据真实性边界": {
                    "是否离线样本": False,
                    "内部推理": "must-not-escape",
                },
                "公开来源验证": {},
                "证据包": {},
                "证据项清单": [],
                "字段策略": {
                    "字段白名单已执行": True,
                    "脱敏必需": True,
                    "内部黑箱字段已隐藏": True,
                    "屏蔽字段": ["internal_score_raw", "provider_credential"],
                    "prompt": "must-not-escape",
                },
            },
            approval_audit={
                "审批对象版本一致": True,
                "职责分离已满足": True,
                "申请人": "operator-secret",
                "复核人": "reviewer-secret",
                "principal_id": "principal-secret",
            },
            generated_at="2026-07-19T10:05:00+08:00",
        )

        serialized = json.dumps(result["manifest"], ensure_ascii=False)
        for forbidden in (
            "must-not-escape",
            "operator-secret",
            "reviewer-secret",
            "principal-secret",
            "provider_credential",
            "internal_score_raw",
        ):
            self.assertNotIn(forbidden, serialized)
        assert_customer_delivery_payload_safe(result["manifest"])

    def test_customer_delivery_boundary_scanner_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden internal fields"):
            assert_customer_delivery_payload_safe({"safe": {"prompt": "hidden"}})


if __name__ == "__main__":
    unittest.main()
