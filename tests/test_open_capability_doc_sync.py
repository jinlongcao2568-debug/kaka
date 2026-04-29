from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
POLICY_ID = "PTL-I100-OPEN-CAPABILITY-BASELINE"

D_DOCS = {
    "D1": "docs/D1_研发_Codex执行手册.md",
    "D2": "docs/D2_正式对象契约与字段字典.md",
    "D3": "docs/D3_正式规则码总表与判定说明书.md",
    "D4": "docs/D4_OpenAPI接口契约.md",
    "D5": "docs/D5_页面导出与人工复核规范.md",
    "D6": "docs/D6_字段策略字典与客户交付字段规范.md",
    "D7": "docs/D7_对象级交付矩阵与外发治理规范.md",
    "D8": "docs/D8_真实竞争者识别可售对象与销售推进规范.md",
    "D9": "docs/D9_联系对象与销售触达规范.md",
    "D10": "docs/D10_订单支付交付与治理反馈规范.md",
    "D11": "docs/D11_测试验收与金标回归清单.md",
    "D12": "docs/D12_部署发布与运行治理规范.md",
    "D13": "docs/D13_公开可查边界能力清单.md",
    "D14": "docs/D14_AI模型治理规范.md",
}


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load(read_text(relative_path))


class TestOpenCapabilityDocSync(unittest.TestCase):
    def test_product_module_registry_points_to_open_capability_policy_and_all_d_docs(self) -> None:
        registry = read_yaml("control/product_module_registry.yaml")
        authority_docs = set(registry["source_priority"]["authority_docs"])

        self.assertEqual(
            registry["open_capability_policy_ref"],
            "control/product_task_library.yaml#open_capability_policy",
        )
        self.assertEqual(registry["open_capability_policy_id"], POLICY_ID)
        self.assertEqual(registry["open_capability_policy_summary"]["sold_product"], "evidence_pack_and_leadpack")
        self.assertIn("automated_refund_execution", registry["open_capability_policy_summary"]["excluded_capabilities"])
        self.assertIn("PTL-I100-118-full-product-operational-acceptance", registry["open_capability_policy_summary"]["required_gates"])

        for path in D_DOCS.values():
            self.assertIn(path, authority_docs, path)

    def test_route_map_uses_111f_and_112_navigation_without_stale_active_prompt(self) -> None:
        route_map = read_text("docs/AX9S_开发执行路由图.md")

        self.assertIn(POLICY_ID, route_map)
        self.assertIn("PTL-I100-111F-open-capability-registry-route-doc-sync", route_map)
        self.assertIn("PTL-I100-112-production-platform-infrastructure", route_map)
        self.assertIn("controlled-opening-required", route_map)
        self.assertIn("自动退款执行不实现", route_map)
        self.assertIn("candidate navigation asset", route_map)
        self.assertIn("候选导航资产", route_map)
        self.assertIn("control/current_task.yaml", route_map)
        self.assertIn("control/product_task_library.yaml", route_map)
        self.assertIn("只作导航提示，不决定执行顺序", route_map)
        self.assertNotIn("当前 active packet：`PTL-GOV-122", route_map)
        self.assertNotIn("当前推荐方向仅作导航建议，不是已激活任务：`Stage8 governed touch 深化`", route_map)

    def test_d_docs_all_contain_open_capability_appendix_and_refund_exclusion(self) -> None:
        for doc_id, path in D_DOCS.items():
            with self.subTest(doc_id=doc_id):
                text = read_text(path)
                self.assertIn(POLICY_ID, text)
                self.assertIn("controlled-opening-required", text)
                self.assertIn("自动退款执行", text)
                self.assertIn("excluded", text)
                self.assertIn("manual exception", text)
                self.assertIn("governed review", text)

    def test_d_docs_all_reference_143e_autonomous_source_strategy_policy(self) -> None:
        for doc_id, path in D_DOCS.items():
            with self.subTest(doc_id=doc_id):
                text = read_text(path)
                self.assertIn("PTL-I100-143E", text)
                self.assertIn("全国聚合", text)
                self.assertIn("北京", text)
                self.assertIn("四川", text)
                self.assertIn("江苏", text)
                self.assertIn("浙江", text)
                self.assertIn("山东", text)
                self.assertIn("广东", text)
                self.assertIn("湖北", text)
                self.assertIn("城市适配", text)
                self.assertIn("商业钩子", text)
                self.assertIn("LLM", text)

    def test_d_docs_all_reference_143g_public_web_capture_and_captcha_resume_policy(self) -> None:
        for doc_id, path in D_DOCS.items():
            with self.subTest(doc_id=doc_id):
                text = read_text(path)
                self.assertIn("PTL-I100-143G", text)
                self.assertIn("公开网站抓取失败", text)
                self.assertIn("自动诊断", text)
                self.assertIn("验证码", text)
                self.assertIn("挂起任务", text)
                self.assertIn("operator console", text)
                self.assertIn("输入后续跑", text)
                self.assertIn("Stage2 public source adapter", text)
                self.assertIn("Stage2Service", text)
                self.assertIn("Stage3 parser", text)
                self.assertIn("repository/readback surfaces", text)
                self.assertIn("不得创建第二套重复链路", text)
                self.assertIn("不得自动解验证码", text)
                self.assertIn("144 -> 145 -> 150 -> 151 -> 146 -> 147 -> 148 -> 149", text)

    def test_143e_authority_docs_record_source_strategy_acceptance_and_boundary(self) -> None:
        d1 = read_text(D_DOCS["D1"])
        d11 = read_text(D_DOCS["D11"])
        d13 = read_text(D_DOCS["D13"])

        self.assertIn("D1-R-072", d1)
        self.assertIn("手工 URL 选择作为主流程", d1)
        self.assertIn("技术回归", d1 + d11 + d13)
        self.assertIn("D11-R-054", d11)
        self.assertIn("143E-DOC-002", d11)
        self.assertIn("143E-DOC-007", d11)
        self.assertIn("D13-R-075", d13)
        self.assertIn("全量实时线索源", d13)
        self.assertIn("北京不得用于", d13)
        self.assertIn("城市级适配只在以下条件命中时进入任务池", d13)

    def test_143g_authority_docs_record_capture_upgrade_acceptance_and_boundary(self) -> None:
        d1 = read_text(D_DOCS["D1"])
        d11 = read_text(D_DOCS["D11"])
        d13 = read_text(D_DOCS["D13"])

        self.assertIn("D1-R-073", d1)
        self.assertIn("D11-R-055", d11)
        self.assertIn("D13-R-076", d13)
        self.assertIn("143G-DOC-001", d11)
        self.assertIn("143G-DOC-005", d11)
        self.assertIn("公开网站抓取失败", d1 + d11 + d13)
        self.assertIn("operator console 输入后续跑", d1 + d11 + d13)
        self.assertIn("不得自动解验证码", d1 + d11 + d13)
        self.assertIn("144 -> 145 -> 150 -> 151 -> 146 -> 147 -> 148 -> 149", d1 + d11 + d13)

    def test_stage8_stage9_leadpack_payment_delivery_are_target_capabilities_not_permanent_out_of_scope(self) -> None:
        registry_text = read_text("control/product_module_registry.yaml")
        route_map = read_text("docs/AX9S_开发执行路由图.md")
        combined = registry_text + "\n" + route_map

        for token in (
            "sales outreach",
            "CRM/Quote",
            "LeadPack/Page/Export",
            "payment collection",
            "charge execution",
            "delivery fulfillment",
            "receipt/invoice",
            "target capability",
            "目标能力",
            "不表示永久不做",
        ):
            self.assertIn(token, combined)

        self.assertIn("automated_refund_execution is excluded", combined)
        self.assertIn("manual exception record", combined)
        self.assertNotIn("真实触达是永久不做", combined)
        self.assertNotIn("支付是永久不做", combined)
        self.assertNotIn("交付是永久不做", combined)

    def test_docs_capture_doc_specific_acceptance_scope(self) -> None:
        expected_tokens = {
            "D1": ("三层验收", "PTL-I100-118-full-product-operational-acceptance"),
            "D2": ("字段单口径", "控制面 policy"),
            "D3": ("规则扩展目标", "公开可查证据"),
            "D4": ("live endpoint", "无 provider config"),
            "D5": ("客户可见", "版本锁定"),
            "D6": ("字段白名单", "内部黑箱评分"),
            "D7": ("交付/外发目标", "外发审批审计"),
            "D8": ("真实竞争者识别", "CRM/Quote"),
            "D9": ("真实触达", "退订/opt-out"),
            "D10": ("payment gateway", "reconciliation"),
            "D11": ("engineering regression", "product closure"),
            "D12": ("Postgres", "SLO"),
            "D13": ("公开可查", "绕验证码"),
            "D14": ("AI 只能辅助", "模型判断直接变成客户结论"),
        }

        for doc_id, tokens in expected_tokens.items():
            text = read_text(D_DOCS[doc_id])
            for token in tokens:
                with self.subTest(doc_id=doc_id, token=token):
                    self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
