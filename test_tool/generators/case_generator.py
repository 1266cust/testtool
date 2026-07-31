from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from ..core.config import GenerationConfig
from ..core.models import TestCase, RequirementSection, UIElement, UIElementType, UIAnalysisResult
from ..parsers.image_parser import extract_text_from_file, analyze_ui_image
from .heading_parser import parse_headings
from .action_classifier import classify_action, infer_case_type, infer_priority
from ..utils.file_utils import is_supported_file, is_image_file, SUPPORTED_EXTENSIONS
from ..utils.text_utils import clean_feature_line, short_text, split_points
from ..core.logging import get_logger

logger = get_logger("generators.case_generator")


def _extract_feature_points(section: RequirementSection) -> List[str]:
    """从需求章节提取功能点。"""
    points: List[str] = []
    for line in section.content:
        cleaned = clean_feature_line(line)
        if not cleaned or len(cleaned) < 4:
            continue
        points.extend(split_points(cleaned))

    if not points:
        # 如果没有提取到功能点，生成默认的
        points = [
            section.title + "功能",
            section.title + "数据输入",
            section.title + "数据校验",
        ]

    # 去重并限制数量
    uniq: List[str] = []
    seen = set()
    for p in points:
        p2 = short_text(p, 80)
        if p2 not in seen:
            uniq.append(p2)
            seen.add(p2)
    return uniq[:20]


def _build_simple_preconditions() -> str:
    """生成简化的预置条件。"""
    return """1. 系统功能模块已部署完成，可正常访问。
2. 测试账号已准备就绪，具备相应操作权限。
3. 测试数据已准备，便于验证功能正确性。"""


_COMMON_VERIFY = """校验点：
- 页面提示正确，无异常报错
- 数据保存正确，字段完整
- 操作结果可查询验证"""


def _build_case(
    module_name: str,
    point: str,
    index: int,
    scene_name: str,
    acceptance: str,
    pre: str,
    process: str,
    expected: str,
    case_type: str,
    priority: str = "P1",
) -> TestCase:
    """构建测试用例。"""
    return TestCase(
        case_id="TEMP-" + str(index).zfill(5),
        module=module_name,
        name=point + " - " + scene_name,
        acceptance_purpose=acceptance,
        preconditions=pre,
        steps=process,
        expected_result=expected,
        case_type=case_type,
        priority=priority,
    )


def sections_to_test_cases(
    sections: List[RequirementSection],
    cfg: GenerationConfig,
) -> List[TestCase]:
    """从需求章节生成测试用例。"""
    cases: List[TestCase] = []
    temp_index = 1

    for sec in sections:
        if sec.level > 3:
            continue

        module_name = sec.title
        content_text = "\n".join(sec.content).strip()
        feature_points = _extract_feature_points(sec)
        base_type = infer_case_type(content_text or module_name)
        priority = infer_priority(content_text, module_name)
        pre = _build_simple_preconditions()

        for point in feature_points:
            action = classify_action(point, module_name)

            # 根据操作类型生成不同场景的用例
            scenarios = _get_scenarios_for_action(action)

            for scene_name, process_template, expected_template, case_type_override, _scene_type in scenarios:
                process = process_template.replace("{point}", point).replace("{module}", module_name)
                expected = expected_template.replace("{point}", point)

                ct = case_type_override if case_type_override else (
                    "核心功能测试" if priority == "P0" else base_type
                )

                acceptance = "验证" + point + "在" + scene_name + "场景下功能正确。"

                cases.append(_build_case(
                    module_name=module_name,
                    point=point,
                    index=temp_index,
                    scene_name=scene_name,
                    acceptance=acceptance,
                    pre=pre,
                    process=process,
                    expected=expected,
                    case_type=ct,
                    priority=priority,
                ))
                temp_index += 1

    return cases


def _get_scenarios_for_action(action: str) -> List[Tuple[str, str, str, Optional[str], str]]:
    """根据操作类型返回测试场景。返回 (scene_name, process, expected, case_type_override, test_type)"""
    # 通用场景
    common_scenarios = [
        ("正常操作",
         """1. 进入【{module}】页面。
2. 执行{point}操作。
3. 观察操作结果和页面反馈。
""" + _COMMON_VERIFY,
         """1. 操作成功完成，提示正确。
2. 数据变更符合预期。""",
         None, "界面校验"),
        ("异常输入",
         """1. 进入【{module}】页面。
2. 在{point}中输入异常数据（空值/特殊字符/超长文本）。
3. 观察系统校验和提示。
""" + _COMMON_VERIFY,
         """1. 系统正确校验并给出明确提示。
2. 不产生脏数据。""",
         "异常测试", "格式校验"),
        ("边界值测试",
         """1. 进入【{module}】页面。
2. 在{point}中输入边界值数据（最小/最大/临界值）。
3. 观察系统处理结果。
""" + _COMMON_VERIFY,
         """1. 系统正确处理边界值。
2. 无截断或精度丢失。""",
         "边界值测试", "边界值校验"),
    ]

    # 根据操作类型添加特定场景
    action_specific: List[Tuple[str, str, str, Optional[str], str]] = []

    if action in ("新增创建", "编辑修改"):
        action_specific = [
            ("必填字段校验",
             """1. 进入【{module}】页面。
2. 尝试提交{point}，保持必填字段为空。
3. 观察校验提示。
""" + _COMMON_VERIFY,
             """1. 系统阻止提交并提示必填字段。
2. 提示信息明确具体。""",
             "功能测试", "必填项校验"),
            ("重复提交幂等",
             """1. 进入【{module}】页面。
2. 快速重复点击{point}按钮。
3. 检查最终数据记录。
""" + _COMMON_VERIFY,
             """1. 仅生成一条有效记录。
2. 无重复数据产生。""",
             "稳定性测试", "数据一致性校验"),
        ]

    elif action in ("删除禁用",):
        action_specific = [
            ("删除确认",
             """1. 进入【{module}】页面。
2. 执行{point}操作，观察确认提示。
3. 确认删除后检查数据状态。
""" + _COMMON_VERIFY,
             """1. 删除前有确认提示。
2. 删除后数据状态正确。""",
             None, "状态流转校验"),
            ("删除后恢复",
             """1. 进入【{module}】页面。
2. 执行{point}删除操作。
3. 验证删除后是否可恢复或重新创建。
""" + _COMMON_VERIFY,
             """1. 删除操作符合业务规则。
2. 恢复机制正确（如有）。""",
             None, "状态流转校验"),
        ]

    elif action in ("查询筛选",):
        action_specific = [
            ("多条件组合查询",
             """1. 进入【{module}】页面。
2. 使用多个筛选条件组合查询{point}。
3. 验证查询结果准确性。
""" + _COMMON_VERIFY,
             """1. 组合查询结果准确。
2. 无遗漏或误匹配。""",
             None, "联动校验"),
            ("查询结果分页",
             """1. 进入【{module}】页面。
2. 查询{point}，验证分页功能。
3. 翻页并核对数据一致性。
""" + _COMMON_VERIFY,
             """1. 分页功能正常。
2. 每页数据完整准确。""",
             None, "数据一致性校验"),
        ]

    elif action in ("导入导出",):
        action_specific = [
            ("导入数据格式",
             """1. 进入【{module}】页面。
2. 使用不同格式的数据文件导入{point}。
3. 验证导入结果。
""" + _COMMON_VERIFY,
             """1. 合法格式导入成功。
2. 非法格式有明确提示。""",
             None, "格式校验"),
            ("导出数据完整性",
             """1. 进入【{module}】页面。
2. 导出{point}数据。
3. 核验导出文件数据完整性。
""" + _COMMON_VERIFY,
             """1. 导出文件数据完整。
2. 格式正确可打开。""",
             None, "数据一致性校验"),
        ]

    elif action in ("登录认证",):
        action_specific = [
            ("登录成功",
             """1. 打开登录页面。
2. 使用正确账号密码执行{point}。
3. 验证登录成功并跳转。
""" + _COMMON_VERIFY,
             """1. 登录成功，跳转正确。
2. 用户信息显示正确。""",
             None, "界面校验"),
            ("登录失败",
             """1. 打开登录页面。
2. 使用错误账号密码执行{point}。
3. 观察错误提示。
""" + _COMMON_VERIFY,
             """1. 登录失败提示明确。
2. 不跳转主页面。""",
             None, "格式校验"),
            ("退出登录",
             """1. 已登录状态。
2. 执行{point}退出操作。
3. 验证退出后状态。
""" + _COMMON_VERIFY,
             """1. 退出成功，返回登录页。
2. 无法直接访问系统功能。""",
             None, "状态流转校验"),
        ]

    elif action in ("权限角色",):
        action_specific = [
            ("权限控制",
             """1. 使用无权限账号登录。
2. 尝试访问或操作{point}。
3. 观察权限控制效果。
""" + _COMMON_VERIFY,
             """1. 无权限时正确拒绝。
2. 提示信息友好。""",
             "权限测试", "权限校验"),
            ("角色切换",
             """1. 使用不同角色账号登录。
2. 执行{point}操作。
3. 验证不同角色下的操作差异。
""" + _COMMON_VERIFY,
             """1. 不同角色权限正确。
2. 操作范围符合角色定义。""",
             "权限测试", "权限校验"),
        ]

    elif action in ("支付资金",):
        action_specific = [
            ("支付流程",
             """1. 进入支付页面。
2. 执行{point}支付操作。
3. 验证支付结果和订单状态。
""" + _COMMON_VERIFY,
             """1. 支付成功，订单状态正确。
2. 资金流水记录准确。""",
             None, "状态流转校验"),
            ("支付失败处理",
             """1. 进入支付页面。
2. 模拟支付失败场景（余额不足等）。
3. 观察失败提示和订单状态。
""" + _COMMON_VERIFY,
             """1. 失败提示明确。
2. 订单状态正确，无扣款。""",
             None, "数据一致性校验"),
        ]

    # 安全测试场景（对所有涉及输入/提交的操作添加）
    security_scenarios: List[Tuple[str, str, str, Optional[str], str]] = [
        ("XSS注入测试",
         """1. 进入【{module}】页面。
2. 在{point}中输入恶意脚本代码（如<script>alert('xss')</script>）。
3. 观察系统是否正确过滤或转义。
""" + _COMMON_VERIFY,
         """1. 脚本代码被正确过滤或转义。
2. 不执行任何恶意代码。
3. 页面正常显示，无安全漏洞。""",
         "安全测试", "格式校验"),
        ("参数篡改测试",
         """1. 进入【{module}】页面。
2. 正常填写{point}后，使用开发工具修改提交参数。
3. 验证后端参数校验机制。
""" + _COMMON_VERIFY,
         """1. 后端正确校验参数合法性。
2. 非法参数被拒绝或忽略。
3. 无数据篡改风险。""",
         "安全测试", "数据一致性校验"),
    ]

    # 特定操作的安全测试场景
    if action in ("查询筛选",):
        security_scenarios.append((
            "SQL注入测试",
            """1. 进入【{module}】页面。
2. 在{point}查询条件中输入SQL注入语句（如' OR '1'='1）。
3. 观察系统是否正确处理。
""" + _COMMON_VERIFY,
            """1. SQL注入语句被正确过滤。
2. 查询结果不泄露额外数据。
3. 数据库无异常查询日志。""",
            "安全测试", "格式校验",
        ))

    if action in ("权限角色",):
        security_scenarios.append((
            "越权访问测试",
            """1. 使用普通用户账号登录。
2. 尝试通过修改URL或参数访问{point}的管理功能。
3. 验证权限控制机制。
""" + _COMMON_VERIFY,
            """1. 越权访问被正确拦截。
2. 返回权限不足提示。
3. 无法执行超出权限的操作。""",
            "安全测试", "权限校验",
        ))

    if action in ("导入导出",):
        security_scenarios.append((
            "敏感数据泄露测试",
            """1. 进入【{module}】页面。
2. 执行{point}导出操作。
3. 检查导出文件是否包含敏感信息（密码、身份证号等）。
""" + _COMMON_VERIFY,
            """1. 敏感数据正确脱敏或加密。
2. 导出文件不包含明文敏感信息。
3. 符合数据安全规范。""",
            "安全测试", "数据一致性校验",
        ))

    if action in ("登录认证",):
        security_scenarios.append((
            "暴力破解防护测试",
            """1. 打开登录页面。
2. 连续多次尝试错误密码执行{point}。
3. 验证账号锁定或验证码机制。
""" + _COMMON_VERIFY,
            """1. 多次失败后触发防护机制。
2. 账号临时锁定或强制验证码。
3. 无法无限尝试密码。""",
            "安全测试", "权限校验",
        ))

    return common_scenarios + action_specific + security_scenarios


def generate_ui_element_test_cases(
    ui_result: UIAnalysisResult,
    cfg: GenerationConfig,
) -> List[TestCase]:
    """从 UI 元素分析结果生成测试用例。"""
    cases: List[TestCase] = []
    temp_index = 1

    module_name = "UI界面"
    pre = _build_simple_preconditions()

    # 按钮测试用例
    for button in ui_result.action_buttons:
        point = "按钮[" + button.text + "]"

        # 按钮点击测试
        cases.append(_build_case(
            module_name=module_name,
            point=point,
            index=temp_index,
            scene_name="点击响应",
            acceptance="验证" + point + "点击后响应正确。",
            pre=pre,
            process="""1. 进入对应页面，定位""" + point + """。
2. 点击按钮触发操作。
3. 观察页面响应（跳转/弹窗/提示/数据变更）。
""" + _COMMON_VERIFY,
            expected="""1. 点击响应及时，无卡顿或报错。
2. 响应行为符合产品定义。
3. 异常情况有友好提示。""",
            case_type="功能测试",
        ))
        temp_index += 1

        # 按钮状态测试
        cases.append(_build_case(
            module_name=module_name,
            point=point,
            index=temp_index,
            scene_name="状态验证",
            acceptance="验证" + point + "在不同场景下状态正确。",
            pre=pre,
            process="""1. 在不同条件下观察""" + point + """状态（可见/禁用/可点击）。
2. 尝试在不同状态下点击按钮。
3. 记录状态变化和点击效果。
""" + _COMMON_VERIFY,
            expected="""1. 按钮状态与业务规则一致。
2. 禁用状态不可点击。
3. 状态切换及时准确。""",
            case_type="功能测试",
        ))
        temp_index += 1

        # 按钮关键词对应的特殊测试
        for kw in button.keywords:
            if kw in ("提交", "保存", "确认", "确定", "完成"):
                cases.append(_build_case(
                    module_name=module_name,
                    point=point,
                    index=temp_index,
                    scene_name="重复点击幂等",
                    acceptance="验证" + point + "重复点击不产生重复数据。",
                    pre=pre,
                    process="""1. 快速连续点击""" + point + """2-3次。
2. 检查最终数据记录数量。
3. 验证是否有重复提交拦截机制。
""" + _COMMON_VERIFY,
                    expected="""1. 仅产生一条有效记录。
2. 重复请求被正确拦截或忽略。""",
                    case_type="稳定性测试",
                ))
                temp_index += 1
                break

            if kw in ("删除", "移除"):
                cases.append(_build_case(
                    module_name=module_name,
                    point=point,
                    index=temp_index,
                    scene_name="删除确认",
                    acceptance="验证" + point + "有确认提示且删除正确。",
                    pre=pre,
                    process="""1. 点击""" + point + """触发删除。
2. 观察是否有确认提示弹窗。
3. 确认后验证数据删除结果。
""" + _COMMON_VERIFY,
                    expected="""1. 删除前有确认提示。
2. 删除成功，数据状态正确。""",
                    case_type="功能测试",
                    
                ))
                temp_index += 1
                break

    # 输入字段测试用例
    for field, label in ui_result.form_fields:
        field_name = field.associated_label or field.text or "输入字段"
        point = "字段[" + field_name + "]"

        # 字段输入测试
        cases.append(_build_case(
            module_name=module_name,
            point=point,
            index=temp_index,
            scene_name="输入校验",
            acceptance="验证" + point + "输入校验规则正确。",
            pre=pre,
            process="""1. 进入包含""" + point + """的页面。
2. 输入不同类型数据（合法/非法/边界）。
3. 观察输入响应和校验提示。
""" + _COMMON_VERIFY,
            expected="""1. 合法输入正常接受。
2. 非法输入有明确校验提示。
3. 边界值处理正确。""",
            case_type="功能测试",
            
        ))
        temp_index += 1

        # 字段必填测试
        cases.append(_build_case(
            module_name=module_name,
            point=point,
            index=temp_index,
            scene_name="必填校验",
            acceptance="验证" + point + "必填校验正确。",
            pre=pre,
            process="""1. 保持""" + point + """为空。
2. 尝试提交表单。
3. 观察必填校验提示。""",
            expected="""1. 必填字段为空时阻止提交。
2. 提示信息清晰明确。
3. 填写后可正常提交。""",
            case_type="功能测试",
            
        ))
        temp_index += 1

        # 字段长度测试
        cases.append(_build_case(
            module_name=module_name,
            point=point,
            index=temp_index,
            scene_name="长度限制",
            acceptance="验证" + point + "长度限制正确。",
            pre=pre,
            process="""1. 在""" + point + """中输入超长文本。
2. 观察系统对长度的处理。
3. 验证是否有截断或提示。
""" + _COMMON_VERIFY,
            expected="""1. 系统正确限制输入长度。
2. 超长输入有提示或截断。
3. 无数据丢失或异常。""",
            case_type="边界值测试",
            
        ))
        temp_index += 1

        # 输入字段安全测试
        cases.append(_build_case(
            module_name=module_name,
            point=point,
            index=temp_index,
            scene_name="XSS注入防护",
            acceptance="验证" + point + "对XSS攻击的防护能力。",
            pre=pre,
            process="""1. 在""" + point + """中输入恶意脚本代码（如<script>alert('xss')</script>）。
2. 提交表单或触发数据保存。
3. 检查数据是否被正确过滤或转义。
""" + _COMMON_VERIFY,
            expected="""1. 恶意脚本被正确过滤或转义。
2. 页面不执行任何注入代码。
3. 存储和显示时无安全风险。""",
            case_type="安全测试",
            
        ))
        temp_index += 1

    return cases


def expand_to_min_cases(cases: List[TestCase], min_cases: int) -> List[TestCase]:
    """扩展用例数量到最小值。"""
    if not cases or len(cases) >= min_cases:
        return cases

    expanded: List[TestCase] = list(cases)
    round_index = 1
    base_len = len(cases)

    while len(expanded) < min_cases:
        template = cases[(len(expanded) - base_len) % base_len]
        variant = replace(
            template,
            name=template.name + " - 测试数据集" + str(round_index),
            steps=template.steps + "\n4. 使用测试数据集" + str(round_index) + "进行验证。",
            expected_result=template.expected_result + "\n数据集" + str(round_index) + "验证结果符合预期。",
        )
        expanded.append(variant)
        round_index += 1

    return expanded


def _iter_supported_files(path: Path) -> Iterable[Path]:
    """遍历支持的文件。"""
    if path.is_file():
        yield path
        return
    for p in sorted(path.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield p


def parse_requirement_path(
    path: Path,
    min_cases: int = 300,
    cfg: Optional[GenerationConfig] = None,
    use_llm: bool = False,
    project_id: str = "",
) -> List[TestCase]:
    """解析需求路径，生成测试用例。

    Args:
        path: 需求文件或目录路径
        min_cases: 最少用例数（仅在模板模式下使用）
        cfg: 生成配置
        use_llm: 是否使用LLM智能生成
        project_id: 项目ID（用于知识库检索）
    """
    effective_cfg = cfg or GenerationConfig()

    if use_llm and effective_cfg.llm_config.enabled and effective_cfg.llm_config.api_key:
        return generate_with_llm(path, effective_cfg, min_cases, project_id)

    return _generate_with_template(path, min_cases, effective_cfg)


def _generate_with_template(
    path: Path,
    min_cases: int,
    cfg: GenerationConfig,
) -> List[TestCase]:
    """使用模板方式生成用例（原有逻辑 + 视觉增强）。"""
    from ..ocr.multimodal_vision import MultimodalVisionAnalyzer

    all_cases: List[TestCase] = []
    image_paths: List[Path] = []

    for one_file in _iter_supported_files(path):
        logger.info("Processing file: " + str(one_file))

        if is_image_file(one_file):
            ui_result = analyze_ui_image(one_file)
            ui_cases = generate_ui_element_test_cases(ui_result, cfg)
            all_cases.extend(ui_cases)
            logger.info("Generated " + str(len(ui_cases)) + " UI element test cases from " + str(one_file))
            image_paths.append(one_file)

        text = extract_text_from_file(one_file)
        if text.strip():
            sections = parse_headings(text)
            file_cases = sections_to_test_cases(sections, cfg)
            all_cases.extend(file_cases)
            logger.info("Generated " + str(len(file_cases)) + " test cases from text in " + str(one_file))

    if image_paths and cfg.llm_config.api_key:
        try:
            from ..llm.client import LLMClient, LLMConfig

            llm_config = LLMConfig(
                provider=cfg.llm_config.provider,
                model_name=cfg.llm_config.model_name,
                api_key=cfg.llm_config.api_key,
                base_url=cfg.llm_config.base_url,
            )
            llm_client = LLMClient(llm_config)
            vision_analyzer = MultimodalVisionAnalyzer(llm_client=llm_client)

            for img_path in image_paths:
                try:
                    vision_result = vision_analyzer.extract_test_points(
                        img_path, module_name=img_path.stem,
                    )
                    vision_cases = _generate_cases_from_vision_test_points(
                        vision_result, cfg,
                    )
                    all_cases.extend(vision_cases)
                    logger.info(
                        f"Generated {len(vision_cases)} cases from vision test points of {img_path.name}"
                    )
                except Exception as exc:
                    logger.warning(f"Vision test point extraction failed for {img_path.name}: {exc}")
        except Exception as exc:
            logger.warning(f"Vision enhancement not available: {exc}")

    all_cases = expand_to_min_cases(all_cases, min_cases=min_cases)

    for i, c in enumerate(all_cases, start=1):
        c.case_id = "TC-" + str(i).zfill(6)

    logger.info("Total test cases generated: " + str(len(all_cases)))
    return all_cases


def _generate_cases_from_vision_test_points(
    test_points,
    cfg: GenerationConfig,
) -> List[TestCase]:
    """从视觉分析提取的测试点生成测试用例"""
    from .test_point_analyzer import TestPoint
    from .smart_generator import SmartCaseGenerator, GenerationContext
    from ..llm.client import LLMClient, LLMConfig

    if not test_points:
        return []

    if not cfg.llm_config.api_key:
        return _generate_cases_from_vision_test_points_template(test_points, cfg)

    llm_config = LLMConfig(
        provider=cfg.llm_config.provider,
        model_name=cfg.llm_config.model_name,
        api_key=cfg.llm_config.api_key,
        base_url=cfg.llm_config.base_url,
    )
    llm_client = LLMClient(llm_config)
    generator = SmartCaseGenerator(llm_client)

    all_cases: List[TestCase] = []
    for point in test_points:
        context = GenerationContext(
            module_name=point.module_name or point.related_requirement,
            test_point=point,
            requirement_context=point.ui_elements_context or point.related_requirement,
            system_config=cfg,
        )
        cases = generator.generate_for_test_point(context)
        all_cases.extend(cases)

    return all_cases


def _generate_cases_from_vision_test_points_template(
    test_points,
    cfg: GenerationConfig,
) -> List[TestCase]:
    """从视觉测试点用模板方式生成用例（无需LLM）"""
    cases: List[TestCase] = []
    temp_index = 1

    for point in test_points:
        module_name = point.module_name or "UI界面"
        feature_points = [point.point_name]
        pre = _build_simple_preconditions()

        for fp in feature_points:
            action = classify_action(fp, module_name)
            scenarios = _get_scenarios_for_action(action)

            for scene_name, process_template, expected_template, case_type_override, _ in scenarios:
                process = process_template.replace("{point}", fp).replace("{module}", module_name)
                expected = expected_template.replace("{point}", fp)

                if point.ui_elements_context:
                    process = "1. 在【" + point.ui_elements_context + "】中，\n" + process.replace("1. ", "2. ")

                ct = case_type_override if case_type_override else "功能测试"
                acceptance = "验证" + fp + "在" + scene_name + "场景下功能正确。"

                cases.append(_build_case(
                    module_name=module_name,
                    point=fp,
                    index=temp_index,
                    scene_name=scene_name,
                    acceptance=acceptance,
                    pre=pre,
                    process=process,
                    expected=expected,
                    case_type=ct,
                    priority=point.priority,
                ))
                temp_index += 1

    return cases


def generate_with_llm(
    path: Path,
    cfg: GenerationConfig,
    min_cases: int = 100,
    project_id: str = "",
) -> List[TestCase]:
    """使用LLM智能生成测试用例。

    Args:
        path: 需求文件或目录路径
        cfg: 生成配置（需包含LLM配置）
        min_cases: 最少用例数
        project_id: 项目ID（用于知识库检索）
    """
    from ..llm.client import LLMClient, LLMConfig
    from ..llm.config_loader import load_llm_config_from_env
    from .test_point_analyzer import TestPointAnalyzer
    from .smart_generator import SmartCaseGenerator
    from ..ocr.multimodal_vision import MultimodalVisionAnalyzer

    llm_config = LLMConfig(
        provider=cfg.llm_config.provider,
        model_name=cfg.llm_config.model_name,
        api_key=cfg.llm_config.api_key,
        base_url=cfg.llm_config.base_url,
        max_tokens=cfg.llm_config.max_tokens,
        temperature=cfg.llm_config.temperature,
    )

    if not llm_config.api_key:
        env_config = load_llm_config_from_env()
        llm_config.api_key = env_config.api_key
        llm_config.base_url = llm_config.base_url or env_config.base_url
        llm_config.provider = llm_config.provider or env_config.provider

    if not llm_config.api_key:
        logger.warning("LLM API key not configured, falling back to template generation")
        return _generate_with_template(path, min_cases, cfg)

    llm_client = LLMClient(llm_config)

    all_sections: List[RequirementSection] = []
    ui_results: dict[str, UIAnalysisResult] = {}
    image_paths: List[Path] = []

    for one_file in _iter_supported_files(path):
        logger.info("Processing file for LLM: " + str(one_file))

        if is_image_file(one_file):
            ui_result = analyze_ui_image(one_file)
            ui_results[one_file.stem] = ui_result
            image_paths.append(one_file)

        text = extract_text_from_file(one_file)
        if text.strip():
            sections = parse_headings(text)
            all_sections.extend(sections)

    vision_test_points = []
    if image_paths and llm_client:
        vision_analyzer = MultimodalVisionAnalyzer(llm_client=llm_client)
        for img_path in image_paths:
            module_name = img_path.stem
            try:
                v_points = vision_analyzer.extract_test_points(
                    img_path, module_name=module_name,
                )
                vision_test_points.extend(v_points)
                logger.info(
                    f"Extracted {len(v_points)} test points from vision analysis of {img_path.name}"
                )
            except Exception as exc:
                logger.warning(f"Vision test point extraction failed for {img_path.name}: {exc}")

    if not all_sections and not vision_test_points:
        logger.warning("No requirement sections or vision test points found")
        return []

    text_test_points = []
    module_analyses: dict = {}
    if all_sections:
        analyzer = TestPointAnalyzer(llm_client)
        text_test_points, module_analyses = analyzer.analyze_all_sections(
            all_sections, ui_results
        )
        logger.info(f"Analyzed {len(text_test_points)} text test points")

    all_test_points = _merge_test_points(text_test_points, vision_test_points)

    logger.info(f"Total test points after merge: {len(all_test_points)}")

    generator = SmartCaseGenerator(llm_client)
    cases = generator.generate_for_all_points(all_test_points, all_sections, cfg, module_analyses, project_id)

    if len(cases) < min_cases:
        logger.info(f"Generated {len(cases)} cases, below minimum {min_cases}")
        template_cases = _generate_with_template(path, min_cases - len(cases), cfg)
        cases.extend(template_cases)

    for i, c in enumerate(cases, start=1):
        c.case_id = "TC-" + str(i).zfill(6)

    logger.info("Total test cases generated with LLM: " + str(len(cases)))
    return cases


def _merge_test_points(text_points, vision_points):
    """合并文本测试点和视觉测试点，去除重复"""
    seen_signatures = set()
    merged = []

    for point in text_points:
        sig = f"{point.point_name}:{point.category}".lower().strip()
        if sig not in seen_signatures:
            seen_signatures.add(sig)
            merged.append(point)

    for point in vision_points:
        sig = f"{point.point_name}:{point.category}".lower().strip()
        if sig not in seen_signatures:
            seen_signatures.add(sig)
            merged.append(point)

    return merged