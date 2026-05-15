from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage3_parsing import markitdown_adapter  # noqa: E402
from storage.responsible_person_early_probe import build_responsible_person_early_probe  # noqa: E402


class ResponsiblePersonEarlyProbeTests(unittest.TestCase):
    def test_detail_html_with_company_person_and_certificate_builds_stage4_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11029",
                project_name="屋顶光伏项目中标候选人公示",
                detail_text=(
                    "第一中标候选人：河南祥鹰市政工程有限公司\n"
                    "项目负责人：张三\n"
                    "证书编号：粤1442020202100001\n"
                    "投标报价：1234.56万元"
                ),
                pdf_name="定标候选人公示.pdf",
            )
            with patch("storage.responsible_person_early_probe.markitdown_adapter.convert_bytes_to_markdown_text") as convert:
                result = build_responsible_person_early_probe(
                    input_root=input_root,
                    output_root=root / "out",
                    created_at="2026-05-11T00:00:00+08:00",
                )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["early_probe_state"], "CERTIFICATE_READY_FROM_07")
            self.assertEqual(item["stage4_readiness_state"], "READY_FOR_STAGE4_INPUT")
            self.assertFalse(item["flow_08_targeted_parse_required"])
            self.assertEqual(result["manifest"]["stage4_candidate_verification_inputs"]["summary"]["stage4_input_count"], 1)
            stage4_item = result["manifest"]["stage4_candidate_verification_inputs"]["items"][0]
            self.assertEqual(stage4_item["candidate_company_name"], "河南祥鹰市政工程有限公司")
            self.assertEqual(stage4_item["project_manager_name"], "张三")
            self.assertEqual(stage4_item["project_manager_certificate_no"], "粤1442020202100001")
            self.assertFalse(stage4_item["stage4_live_provider_enabled"])
            convert.assert_not_called()

    def test_company_and_name_without_certificate_requires_company_first_supplement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11021",
                project_name="设计施工总承包中标候选人公示",
                detail_text="第一中标候选人：广州测试建设有限公司\n项目负责人：李四\n资质详见投标文件公开",
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["early_probe_state"], "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED")
            self.assertEqual(item["stage4_readiness_state"], "SUPPLEMENT_REQUIRED_COMPANY_FIRST")
            self.assertIn("RUN_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT", item["next_actions"])
            self.assertEqual(result["manifest"]["stage4_candidate_verification_inputs"]["summary"]["stage4_input_count"], 0)

    def test_company_candidates_filter_platform_and_agent_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11028",
                project_name="施工总承包中标候选人公示",
                detail_text=(
                    "广州交易集团有限公司\n广东省城规建设监理有限公司\n"
                    "序号 合格中标候选人 项目负责人 投标总报价\n"
                    "1 (主)广州市第三建筑工程有限公司;(成)广州市建工设计院有限公司 邓富根 5982050.83\n"
                ),
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            companies = [row["value"] for row in item["candidate_company_candidates"]]
            self.assertEqual(companies[0], "广州市第三建筑工程有限公司")
            self.assertNotIn("广州交易集团有限公司", companies)
            self.assertNotIn("广东省城规建设监理有限公司", companies)

    def test_company_first_no_match_triggers_name_enumeration_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11022",
                project_name="施工项目中标候选人公示",
                detail_text="第一中标候选人：广州测试建设有限公司\n项目负责人：王五",
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                company_first_state="NO_MATCH",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["early_probe_state"], "NAME_ENUMERATION_FALLBACK_REQUIRED")
            self.assertFalse(item["flow_08_targeted_parse_required"])
            self.assertIn("RUN_NAME_ENUMERATION_FALLBACK", item["next_actions"])

    def test_company_and_name_both_not_matched_requires_flow08_without_final_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11023",
                project_name="施工项目中标候选人公示",
                detail_text="第一中标候选人：广州测试建设有限公司\n项目负责人：赵六",
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                company_first_state="NO_MATCH",
                name_enumeration_state="NO_MATCH",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["early_probe_state"], "FLOW_08_TARGETED_PARSE_REQUIRED")
            self.assertEqual(item["risk_escalation_state"], "HIGH_CLUE_REVIEW")
            self.assertTrue(item["flow_08_targeted_parse_required"])
            self.assertIn("DO_NOT_OUTPUT_FINAL_CONFLICT", item["next_actions"])
            self.assertTrue(item["no_legal_conclusion"])

    def test_pdf_markitdown_empty_sets_ocr_required_without_fake_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11024",
                project_name="施工项目中标候选人公示",
                detail_text="第一中标候选人：广州测试建设有限公司",
                pdf_name="中标候选人公示.pdf",
            )
            with patch(
                "storage.responsible_person_early_probe.markitdown_adapter.convert_bytes_to_markdown_text",
                return_value=markitdown_adapter.MarkItDownText(
                    text="",
                    state=markitdown_adapter.MARKITDOWN_TEXT_EMPTY,
                    warnings=[markitdown_adapter.MARKITDOWN_TEXT_EMPTY],
                ),
            ):
                result = build_responsible_person_early_probe(
                    input_root=input_root,
                    output_root=root / "out",
                    created_at="2026-05-11T00:00:00+08:00",
                )

            item = result["manifest"]["items"][0]
            self.assertTrue(item["ocr_required"])
            self.assertEqual(item["early_probe_state"], "OCR_REQUIRED_FOR_07")
            self.assertEqual(result["manifest"]["stage4_candidate_verification_inputs"]["summary"]["stage4_input_count"], 0)

    def test_service_or_insurance_project_is_not_forced_to_project_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11283",
                project_name="清连高速公路运营保险项目中标候选人公示",
                detail_text="第一中标候选人：中国人民财产保险股份有限公司广东省分公司\n投标报价：88.10万元",
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["responsible_role"], "not_applicable")
            self.assertEqual(item["early_probe_state"], "RESPONSIBLE_PERSON_NOT_APPLICABLE")
            self.assertFalse(item["flow_08_targeted_parse_required"])

    def test_equipment_procurement_placeholder_person_is_not_forced_to_stage4_or_flow08(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11204",
                project_name="电动集装箱牵引车及半挂车购置项目中标候选人公示",
                detail_text=(
                    "序号\n中标候选人名称\n候选人代码\n排名\n投标报价\n质量承诺\n工期（交货期）\n"
                    "候选人资格情况\n候选人业绩情况\n拟派项目负责人\n项目负责人资质\n项目负责人业绩\n"
                    "1\n三一海洋重工有限公司\n914404005764303531\n1\n15706000.00元\n合格\n88天\n"
                    "满足招标文件要求\n详见附件\n/\n/\n/\n"
                    "2\n广州市华奥德汽车销售服务有限公司\n91440116082744192A\n2\n15456000.00元\n合格\n89天\n"
                    "满足招标文件要求\n详见附件\n/\n/\n/"
                ),
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["responsible_role"], "not_applicable")
            self.assertEqual(item["early_probe_state"], "RESPONSIBLE_PERSON_NOT_APPLICABLE")
            self.assertFalse(item["verification_targets"])
            self.assertFalse(item["flow_08_targeted_parse_required"])

    def test_candidate_table_uses_later_specific_person_over_placeholder_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11292",
                project_name="工程可行性研究及方案深化研究中标候选人公示",
                detail_text=(
                    "项目负责人姓名及证书、证号\n详见附件\n详见附件\n详见附件\n"
                    "序号\n中标候选人名称\n候选人代码\n排名\n投标报价\n质量承诺\n工期（交货期）\n"
                    "候选人资格情况\n候选人业绩情况\n拟派项目负责人\n项目负责人资质\n项目负责人业绩\n"
                    "1\n广东省交通规划设计研究院集团股份有限公司\n91440000455857836N\n1\n9400000元\n"
                    "研究成果需通过专家评审\n按招标人规定\n工程勘察综合甲级资质、工程设计公路行业甲级资质\n"
                    "惠州至肇庆高速公路白云至三水段项目勘察设计\n雷明\n路桥高级工程师\n惠州惠城至惠阳霞涌高速公路工程勘察设计SJ1标段。\n"
                    "2\n中交第二公路勘察设计研究院有限公司\n91420100177668591H\n2\n9395678元\n"
                    "研究成果需通过专家评审\n按招标人规定\n工程勘察综合甲级资质\n"
                    "武汉都市圈环线高速公路两阶段勘察设计\n查明高\n正高级工程师\n京港澳高速公路改扩建工程勘察设计。"
                ),
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["responsible_role"], "design_lead")
            self.assertEqual(
                [(group["candidate_group_order"], group["responsible_person_name"]) for group in item["candidate_groups"]],
                [(1, "雷明"), (2, "查明高")],
            )
            self.assertNotIn("按招标人规定", [row["value"] for row in item["responsible_person_candidates"]])
            self.assertEqual(item["early_probe_state"], "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED")

    def test_candidate_table_prefers_personal_registration_over_enterprise_qualification_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11026",
                project_name="EPCO 项目中标候选人公示",
                detail_text=(
                    "序号\n中标候选人名称\n候选人资格情况\n拟派项目负责人\n项目负责人资质\n"
                    "1\n广州测试建设有限公司\n"
                    "施工资质：电力工程施工总承包二级（证书编号：D244255414）；安全生产许可证（编号：(粤)JZ安许证字[2023]012542）；\n"
                    "/\n彭耀聪\n一级注册建造师（注册编号：粤1442024202500740）\n/"
                ),
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["early_probe_state"], "CERTIFICATE_READY_FROM_07")
            self.assertEqual([c["value"] for c in item["responsible_person_candidates"][:1]], ["彭耀聪"])
            self.assertEqual([c["value"] for c in item["certificate_no_candidates"][:1]], ["粤1442024202500740"])
            self.assertNotIn("D244255414", [c["value"] for c in item["certificate_no_candidates"]])

    def test_candidate_groups_bind_person_certificate_to_same_consortium_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11260",
                project_name="EPC+O一体化建设运营中标候选人公示",
                detail_text=(
                    "序号\n中标候选人名称\n候选人代码\n排名\n投标报价\n质量承诺\n工期（交货期）\n"
                    "候选人资格情况\n候选人业绩情况\n拟派项目负责人\n项目负责人资质\n项目负责人业绩\n"
                    "1\n(主)云浮市易安停科技有限公司;(成)中裕工程集团有限公司;(成)北京神州新桥科技有限公司\n"
                    "91445323MAKBQRUQ2J\n1\n100740664.10元\n按招标文件约定\n365个日历天\n满足招标文件要求\n/\n"
                    "王立亮\n通信与广电工程、建筑工程、机电工程一级注册建造师（注册编号：京1112017201745983）\n/\n"
                    "2\n(主)云浮市锐宝投资有限公司;(成)山东鸿典建设有限公司;(成)中联合创设计有限公司\n"
                    "91445302698130201R\n2\n101585088.60元\n按招标文件约定\n365个日历天\n满足招标文件要求\n/\n"
                    "侯延强\n机电工程、建筑工程一级注册建造师（注册编号：鲁1372021202201811）\n/"
                ),
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["early_probe_state"], "CERTIFICATE_READY_FROM_07")
            self.assertEqual(len(item["candidate_groups"]), 2)
            first_group = item["candidate_groups"][0]
            self.assertEqual(first_group["responsible_person_name"], "王立亮")
            self.assertEqual(first_group["certificate_no"], "京1112017201745983")
            self.assertEqual(
                [member["company_name"] for member in first_group["consortium_members"]],
                ["云浮市易安停科技有限公司", "中裕工程集团有限公司", "北京神州新桥科技有限公司"],
            )
            stage4_items = result["manifest"]["stage4_candidate_verification_inputs"]["items"]
            first_group_inputs = [row for row in stage4_items if row["responsible_person_name"] == "王立亮"]
            self.assertEqual(len(first_group_inputs), 3)
            self.assertIn("北京神州新桥科技有限公司", [row["candidate_company_name"] for row in first_group_inputs])
            self.assertNotIn(
                "云浮市锐宝投资有限公司",
                [row["candidate_company_name"] for row in first_group_inputs],
            )

    def test_candidate_table_person_without_certificate_triggers_company_first_not_fake_person_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11027",
                project_name="监理服务中标候选人公示",
                detail_text=(
                    "序号\n中标候选人名称\n候选人资格情况\n候选人业绩情况\n总监理工程师\n总监理工程师资质\n"
                    "1\n华夏邮电咨询监理有限公司\n详见投标文件公开\n详见投标文件公开\n陈光理\n详见投标文件公开\n/"
                ),
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["early_probe_state"], "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED")
            self.assertEqual([c["value"] for c in item["responsible_person_candidates"][:1]], ["陈光理"])
            self.assertNotIn("总监理工程师", [c["value"] for c in item["responsible_person_candidates"]])
            self.assertEqual(item["candidate_groups"][0]["responsible_person_name"], "陈光理")
            self.assertEqual(item["verification_targets"][0]["candidate_company_name"], "华夏邮电咨询监理有限公司")
            self.assertEqual(item["verification_targets"][0]["responsible_person_name"], "陈光理")
            self.assertEqual(item["verification_targets"][0]["certificate_no"], "")

    def test_candidate_table_person_without_certificate_keeps_all_candidate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11021",
                project_name="设计施工总承包中标候选人公示",
                detail_text=(
                    "序号\n合格中标候选人名称\n合格中标候选人代码\n投标报价\n质量承诺\n工期（交货期）\n"
                    "候选人资格情况\n候选人业绩情况\n拟派项目负责人\n项目负责人资质\n项目负责人业绩\n"
                    "1\n(主)广州市第三建筑工程有限公司;(成)广州市建工设计院有限公司\n"
                    "914401012312499892；91440101190552120A\n5982050.83元\n按招标文件要求\n按招标文件要求\n"
                    "详见投标文件公开\n详见投标文件公开\n邓富根\n详见投标文件公开\n详见投标文件公开\n"
                    "2\n(主)广州市第四建筑工程有限公司;(成)广州建筑产业开发有限公司\n"
                    "91440101190435127K；91440101712487099G\n5913417.82元\n按招标文件要求\n按招标文件要求\n"
                    "详见投标文件公开\n详见投标文件公开\n莫剑斌\n详见投标文件公开\n详见投标文件公开\n"
                    "3\n广东省第一建筑工程有限公司\n914400001903237820\n6042103.59元\n按招标文件要求\n按招标文件要求\n"
                    "详见投标文件公开\n详见投标文件公开\n唐名龙\n详见投标文件公开\n详见投标文件公开"
                ),
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["early_probe_state"], "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED")
            self.assertEqual(len(item["candidate_groups"]), 3)
            self.assertEqual(
                [(group["candidate_group_order"], group["responsible_person_name"]) for group in item["candidate_groups"]],
                [(1, "邓富根"), (2, "莫剑斌"), (3, "唐名龙")],
            )
            targets = item["verification_targets"]
            self.assertEqual(len(targets), 5)
            self.assertIn(
                ("广州市建工设计院有限公司", "邓富根"),
                [(row["candidate_company_name"], row["responsible_person_name"]) for row in targets],
            )
            self.assertIn(
                ("广州建筑产业开发有限公司", "莫剑斌"),
                [(row["candidate_company_name"], row["responsible_person_name"]) for row in targets],
            )

    def test_design_candidate_table_stops_before_score_table_and_rejects_qualification_as_person(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11215",
                project_name="广州体育学院新建学生宿舍楼项目设计中标候选人公示",
                detail_text=(
                    "序号\n投标单位\n商务文件得分\n技术文件得分\n投标报价得分\n总得分\n排名\n"
                    "1\n广东南海国际建筑设计有限公司\n30\n45.10\n9.827\n84.93\n1\n"
                    "2\n广州市设计院集团有限公司\n30\n44.40\n9.862\n84.26\n2\n"
                    "3\n浙江恒欣设计集团股份有限公司\n30\n43.80\n9.865\n83.67\n3\n"
                    "序号\n中标候选人名称\n候选人代码\n排名\n投标报价\n质量标准\n设计服务期限\n"
                    "候选人资格情况\n候选人业绩情况\n拟派项目负责人\n项目负责人资质\n项目负责人业绩\n"
                    "1\n广东南海国际建筑设计有限公司\n91440605719241964G\n1\n2409500.00元\n"
                    "按招标文件要求\n按招标文件要求\n建筑行业（建筑工程）甲级\n详见投标文件公开。\n"
                    "李献义\n一级注册建筑师（注册编号:20034401248）\n详见投标文件公开。\n"
                    "2\n广州市设计院集团有限公司\n91440101455351798Q\n2\n2349300.00元\n"
                    "按招标文件要求\n按招标文件要求\n建筑行业甲级\n详见投标文件公开。\n"
                    "高东\n一级注册建筑师（注册编号:20034401105）\n详见投标文件公开。\n"
                    "3\n浙江恒欣设计集团股份有限公司\n91330400727195881W\n3\n2350000.00元\n"
                    "按招标文件要求\n按招标文件要求\n建筑行业（建筑工程）甲级\n详见投标文件公开。\n"
                    "袁晓忠\n一级注册建筑师（注册编号:20093301403）\n详见投标文件公开。\n"
                    "异议受理部门\n广东省代建项目管理局\n"
                    "中标候选人公示\n序号\n投标单位\n商务文件得分\n技术文件得分\n投标报价得分\n总得分\n排名\n"
                    "1\n广东南海国际建筑设计有限公司\n30\n45.10\n9.827\n84.93\n1\n"
                    "2\n广州市设计院集团有限公司\n30\n44.40\n9.862\n84.26\n2\n"
                    "3\n浙江恒欣设计集团股份有限公司\n30\n43.80\n9.865\n83.67\n3\n"
                ),
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["responsible_role"], "design_lead")
            self.assertEqual(item["early_probe_state"], "CERTIFICATE_READY_FROM_07")
            self.assertEqual(len(item["candidate_groups"]), 3)
            self.assertEqual(
                [(group["candidate_group_order"], group["responsible_person_name"], group["certificate_no"]) for group in item["candidate_groups"]],
                [
                    (1, "李献义", "20034401248"),
                    (2, "高东", "20034401105"),
                    (3, "袁晓忠", "20093301403"),
                ],
            )
            self.assertNotIn("建筑行业甲级", [row["value"] for row in item["responsible_person_candidates"]])
            stage4_items = result["manifest"]["stage4_candidate_verification_inputs"]["items"]
            self.assertEqual(len(stage4_items), 3)
            self.assertEqual(stage4_items[1]["candidate_company_name"], "广州市设计院集团有限公司")
            self.assertEqual(stage4_items[1]["responsible_person_name"], "高东")

    def test_candidate_table_preserves_company_name_with_project_keyword_and_rejects_noise_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-10815",
                project_name="监理服务中标候选人公示",
                detail_text=(
                    "序号\n中标候选人名称\n候选人代码\n排名\n投标报价\n质量标准\n监理服务期限\n"
                    "候选人资格情况\n候选人业绩情况\n总监理工程师\n总监理工程师资质\n总监理工程师业绩\n"
                    "3\n中通服项目管理咨询有限公司\n9143000018379640XW\n3\n957331.34元\n一次性竣工验收合格\n"
                    "按合同约定\n详见投标文件公开\n详见投标文件公开\n曾素华\n详见投标文件公开\n详见投标文件公开\n"
                    "20\n筑工程有限公司,（成）广州建筑产业开发有限公司、（主）广州市第三建筑工程有限公\n第四建\n6042103.59\n3782"
                ),
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(len(item["candidate_groups"]), 1)
            self.assertEqual(item["candidate_groups"][0]["primary_company_name"], "中通服项目管理咨询有限公司")
            self.assertEqual(item["candidate_groups"][0]["responsible_person_name"], "曾素华")

    def test_script_outputs_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            output_root = root / "out"
            _write_project(
                input_root,
                project_id="PROJ-CN-GD-JG2026-11025",
                project_name="施工项目中标候选人公示",
                detail_text="第一中标候选人：广州测试建设有限公司\n项目负责人：孙七\n证书编号：粤1442020202100099",
            )
            result = build_responsible_person_early_probe(
                input_root=input_root,
                output_root=output_root,
                created_at="2026-05-11T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertTrue((output_root / "responsible-person-early-probe.json").exists())
            self.assertTrue((output_root / "stage4_candidate_verification_inputs.json").exists())
            payload = json.loads((output_root / "responsible-person-early-probe.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["manifest"]["customer_visible_allowed"])


def _write_project(
    input_root: Path,
    *,
    project_id: str,
    project_name: str,
    detail_text: str,
    pdf_name: str | None = None,
) -> None:
    project_dir = (
        input_root
        / "projects"
        / "CN-GD"
        / project_id
        / "07_中标候选人公示"
        / f"2026-05-11_abcd1234_{project_name[:20]}"
    )
    detail_dir = project_dir / "detail"
    detail_dir.mkdir(parents=True, exist_ok=True)
    detail_dir.joinpath("detail.html").write_text(
        f"<html><body><div>{detail_text}</div></body></html>",
        encoding="utf-8",
    )
    if pdf_name:
        attachments = project_dir / "attachments"
        attachments.mkdir(parents=True, exist_ok=True)
        attachments.joinpath(pdf_name).write_bytes(b"%PDF fake")
    map_path = input_root / "human-readable-file-map.csv"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(
        "project_id,project_name,flow_no,flow_title,file_role,human_file_name,human_readable_path,source_url,attachment_url,snapshot_id,content_type,byte_size,sha256\n"
        f"{project_id},{project_name},07,中标候选人公示,detail,detail.html,{detail_dir / 'detail.html'},https://example.test/detail.html,https://example.test/detail.html,SNAP,text/html,1,sha\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
