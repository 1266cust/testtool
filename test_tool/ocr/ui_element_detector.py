from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Optional

import cv2
import numpy as np
from PIL import Image
import pytesseract

from ..core.models import (
    BoundingBox,
    UIElement,
    UIElementType,
    OCRResult,
    UIAnalysisResult,
)
from ..core.logging import get_logger

logger = get_logger("ocr.ui_element_detector")


# 按钮关键词 - 触发操作的元素
BUTTON_KEYWORDS = {
    # 中文
    "提交", "保存", "取消", "确认", "删除", "新增", "编辑", "修改",
    "查询", "搜索", "重置", "导出", "导入", "上传", "下载", "返回",
    "登录", "注册", "申请", "审批", "通过", "驳回", "发送", "打印",
    "关闭", "确定", "下一步", "上一步", "完成", "开始", "结束",
    "添加", "移除", "清空", "复制", "粘贴", "刷新", "同步",
    "启用", "停用", "锁定", "解锁", "发布", "撤回", "撤回发布",
    "分配", "转派", "跟进", "处理", "回复", "评论", "点赞",
    "收藏", "分享", "转发", "关注", "订阅", "购买", "下单",
    "支付", "退款", "结算", "开票", "续费", "充值",
    # 英文
    "submit", "save", "cancel", "confirm", "delete", "add", "edit",
    "query", "search", "reset", "export", "import", "upload", "download",
    "login", "register", "apply", "approve", "reject", "send", "print",
    "close", "ok", "next", "previous", "finish", "start", "end",
    "remove", "clear", "copy", "paste", "refresh", "sync",
}

# 标签关键词 - 表单字段名称
LABEL_KEYWORDS = {
    # 中文
    "名称", "标题", "编码", "编号", "类型", "状态", "日期", "时间",
    "金额", "数量", "价格", "费用", "账户", "账号", "密码",
    "手机", "电话", "邮箱", "地址", "备注", "说明", "描述",
    "用户", "姓名", "身份证", "证件", "性别", "年龄", "生日",
    "部门", "岗位", "角色", "权限", "组织", "公司", "企业",
    "订单", "商品", "产品", "项目", "任务", "工单", "流程",
    "客户", "供应商", "联系人", "联系方式", "地区", "城市",
    "开始时间", "结束时间", "有效期", "期限", "截止日期",
    "附件", "文件", "图片", "文档", "内容", "正文",
    "原因", "意见", "结果", "结论", "备注", "标签",
    # 英文
    "name", "title", "code", "id", "type", "status", "date", "time",
    "amount", "quantity", "price", "cost", "account", "password",
    "phone", "email", "address", "note", "description",
    "user", "name", "gender", "age", "birthday",
    "department", "position", "role", "permission", "organization",
    "order", "product", "project", "task", "process",
    "customer", "supplier", "contact", "region", "city",
    "start", "end", "expiry", "deadline",
    "attachment", "file", "image", "document", "content",
}

# 输入提示关键词
INPUT_HINTS = {
    "请输入", "请填写", "请选择", "请搜索", "请上传",
    "请添加", "请设置", "请描述", "请说明",
    "输入", "填写", "选择", "搜索",
    "enter", "input", "select", "search", "choose",
    "placeholder", "click", "点击", "下拉", "可选",
}

# 下拉/选择关键词
SELECT_KEYWORDS = {
    "下拉", "选择框", "单选", "多选", "勾选",
    "全部", "默认", "自定义", "手动", "自动",
    "select", "dropdown", "checkbox", "radio", "option",
}


class UIElementDetector:
    def __init__(
        self,
        ocr_lang: str = "chi_sim+eng",
        min_confidence: float = 25.0,
        min_element_area: int = 200,
    ):
        self.ocr_lang = ocr_lang
        self.min_confidence = min_confidence
        self.min_element_area = min_element_area

    def analyze_screenshot(self, image_path: Path) -> UIAnalysisResult:
        """分析 UI 截图，提取所有可测试的元素。"""
        img_pil = Image.open(str(image_path))
        img_cv = cv2.imread(str(image_path))

        if img_cv is None:
            logger.error("Failed to load image: " + str(image_path))
            return UIAnalysisResult(
                elements=[],
                full_text="",
                ocr_results=[],
                detected_shapes=[],
                form_fields=[],
                action_buttons=[],
            )

        # OCR 提取所有文字及其位置
        ocr_results = self._extract_ocr_with_boxes(img_pil)
        full_text = "\n".join(r.text for r in ocr_results if r.text.strip())

        # OpenCV 检测 UI 元素形状
        detected_shapes = self._detect_ui_shapes(img_cv)

        # 分类和关联 UI 元素
        elements = self._classify_ui_elements(ocr_results, detected_shapes)

        # 关联表单字段和标签
        form_fields = self._associate_labels_with_fields(elements)

        # 提取可操作的按钮
        action_buttons = self._extract_action_buttons(elements)

        logger.info(
            "Detected " + str(len(elements)) + " elements, "
            + str(len(action_buttons)) + " action buttons, "
            + str(len(form_fields)) + " form fields"
        )

        return UIAnalysisResult(
            elements=elements,
            full_text=full_text,
            ocr_results=ocr_results,
            detected_shapes=detected_shapes,
            form_fields=form_fields,
            action_buttons=action_buttons,
        )

    def _extract_ocr_with_boxes(self, img_pil: Image.Image) -> List[OCRResult]:
        """使用 Tesseract 提取文字及其 bounding box。"""
        data = pytesseract.image_to_data(
            img_pil,
            lang=self.ocr_lang,
            output_type=pytesseract.Output.DICT,
        )

        results: List[OCRResult] = []
        n_boxes = len(data["text"])

        for i in range(n_boxes):
            text = data["text"][i].strip()
            if not text:
                continue

            conf = float(data["conf"][i])
            if conf < self.min_confidence:
                continue

            bbox = BoundingBox(
                x=data["left"][i],
                y=data["top"][i],
                width=data["width"][i],
                height=data["height"][i],
            )

            results.append(OCRResult(
                text=text,
                confidence=conf,
                bounding_box=bbox,
                block_num=data["block_num"][i],
                line_num=data["line_num"][i],
                word_num=data["word_num"][i],
            ))

        return results

    def _detect_ui_shapes(self, img_cv: np.ndarray) -> List[BoundingBox]:
        """使用 OpenCV 检测可能的 UI 元素形状（按钮、输入框等）。"""
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

        # 检测高亮区域（可能是按钮）
        _, thresh_light = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
        contours_light, _ = cv2.findContours(
            thresh_light, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # 检测边框区域（可能是输入框）
        edges = cv2.Canny(gray, 50, 150)
        contours_edges, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        shapes: List[BoundingBox] = []

        for contour in contours_light + contours_edges:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h

            if area < self.min_element_area:
                continue

            # 按钮通常是横向的，宽度 > 高度
            aspect_ratio = w / h if h > 0 else 0

            # 按钮候选：aspect ratio 2-10，高度适中
            if 1.5 < aspect_ratio < 15 and h < 100:
                shapes.append(BoundingBox(x=x, y=y, width=w, height=h))
            # 输入框候选：aspect ratio 3-20，高度较小
            elif 2 < aspect_ratio < 25 and 20 < h < 60:
                shapes.append(BoundingBox(x=x, y=y, width=w, height=h))

        return shapes

    def _classify_ui_elements(
        self,
        ocr_results: List[OCRResult],
        shapes: List[BoundingBox],
    ) -> List[UIElement]:
        """将 OCR 结果分类为具体的 UI 元素类型。"""
        elements: List[UIElement] = []

        for ocr in ocr_results:
            element_type = self._determine_element_type(ocr.text)

            # 检查是否在检测到的形状内
            containing_shape = self._find_containing_shape(ocr.bounding_box, shapes)
            is_inside_shape = containing_shape is not None

            # 提取关键词
            keywords = self._extract_keywords(ocr.text)

            # 判断是否可交互
            is_interactive = self._is_interactive_element(
                element_type, is_inside_shape, ocr.text, keywords
            )

            elements.append(UIElement(
                element_type=element_type,
                bounding_box=ocr.bounding_box,
                text=ocr.text,
                confidence=ocr.confidence,
                is_interactive=is_interactive,
                keywords=keywords,
            ))

        # 合并相邻的同类元素
        merged_elements = self._merge_adjacent_elements(elements)

        return merged_elements

    def _determine_element_type(self, text: str) -> UIElementType:
        """根据文本内容判断 UI 元素类型。"""
        text_lower = text.lower().strip()

        # 输入提示 -> 输入框
        if any(hint in text_lower for hint in INPUT_HINTS):
            return UIElementType.INPUT_FIELD

        # 选择提示 -> 下拉框
        if any(hint in text_lower for hint in SELECT_KEYWORDS):
            return UIElementType.DROPDOWN

        # 按钮关键词 -> 按钮
        if any(kw in text_lower for kw in BUTTON_KEYWORDS):
            return UIElementType.BUTTON

        # 标签关键词 -> 标签
        if any(kw in text_lower for kw in LABEL_KEYWORDS):
            return UIElementType.LABEL

        return UIElementType.UNKNOWN

    def _find_containing_shape(
        self,
        bbox: BoundingBox,
        shapes: List[BoundingBox],
    ) -> Optional[BoundingBox]:
        """找到包含该 bounding box 的形状。"""
        for shape in shapes:
            # 扩大形状范围以包含文字
            expanded = BoundingBox(
                x=shape.x - 5,
                y=shape.y - 5,
                width=shape.width + 10,
                height=shape.height + 10,
            )
            if self._is_inside(bbox, expanded):
                return shape
        return None

    def _is_inside(self, inner: BoundingBox, outer: BoundingBox) -> bool:
        """检查 inner 是否在 outer 内。"""
        return (
            inner.x >= outer.x
            and inner.y >= outer.y
            and inner.x + inner.width <= outer.x + outer.width
            and inner.y + inner.height <= outer.y + outer.height
        )

    def _extract_keywords(self, text: str) -> List[str]:
        """提取文本中的操作关键词。"""
        text_lower = text.lower()
        return [kw for kw in BUTTON_KEYWORDS if kw in text_lower]

    def _is_interactive_element(
        self,
        element_type: UIElementType,
        is_inside_shape: bool,
        text: str,
        keywords: List[str],
    ) -> bool:
        """判断元素是否可交互。"""
        if element_type in (UIElementType.BUTTON, UIElementType.INPUT_FIELD, UIElementType.DROPDOWN):
            return True
        if is_inside_shape and keywords:
            return True
        return False

    def _merge_adjacent_elements(self, elements: List[UIElement]) -> List[UIElement]:
        """合并同一行相邻的同类型元素。"""
        if not elements:
            return elements

        merged: List[UIElement] = []
        current: Optional[UIElement] = None

        for elem in sorted(elements, key=lambda e: (e.bounding_box.y, e.bounding_box.x)):
            if current is None:
                current = elem
                continue

            # 检查是否相邻（同一行，间距小）
            y_diff = abs(current.bounding_box.y - elem.bounding_box.y)
            x_gap = elem.bounding_box.x - (current.bounding_box.x + current.bounding_box.width)

            if (
                y_diff < 10
                and x_gap < 20
                and current.element_type == elem.element_type
                and current.is_interactive == elem.is_interactive
            ):
                # 合并
                current = UIElement(
                    element_type=current.element_type,
                    bounding_box=BoundingBox(
                        x=current.bounding_box.x,
                        y=current.bounding_box.y,
                        width=elem.bounding_box.x + elem.bounding_box.width - current.bounding_box.x,
                        height=max(current.bounding_box.height, elem.bounding_box.height),
                    ),
                    text=current.text + " " + elem.text,
                    confidence=max(current.confidence, elem.confidence),
                    is_interactive=current.is_interactive,
                    keywords=current.keywords + elem.keywords,
                )
            else:
                merged.append(current)
                current = elem

        if current:
            merged.append(current)

        return merged

    def _associate_labels_with_fields(
        self, elements: List[UIElement]
    ) -> List[Tuple[UIElement, Optional[UIElement]]]:
        """将标签与输入字段关联。"""
        fields: List[Tuple[UIElement, Optional[UIElement]]] = []

        # 找出所有标签和输入字段
        labels = [
            e for e in elements
            if e.element_type == UIElementType.LABEL
        ]

        potential_fields = [
            e for e in elements
            if e.element_type in (UIElementType.INPUT_FIELD, UIElementType.DROPDOWN, UIElementType.UNKNOWN)
            and e.is_interactive
        ]

        for field in potential_fields:
            best_label: Optional[UIElement] = None
            best_distance = float("inf")

            for label in labels:
                # 标签通常在输入框左边或上方

                # 左侧关联：标签在字段左边，y坐标相近
                y_diff = abs(label.bounding_box.center[1] - field.bounding_box.center[1])
                if y_diff < 25:
                    if label.bounding_box.x < field.bounding_box.x:
                        distance = field.bounding_box.x - (label.bounding_box.x + label.bounding_box.width)
                        if 0 < distance < 150 and distance < best_distance:
                            best_distance = distance
                            best_label = label

                # 上方关联：标签在字段上方，x坐标相近
                x_diff = abs(label.bounding_box.center[0] - field.bounding_box.center[0])
                if x_diff < 50:
                    if label.bounding_box.y < field.bounding_box.y:
                        distance = field.bounding_box.y - (label.bounding_box.y + label.bounding_box.height)
                        if 0 < distance < 30 and distance < best_distance:
                            best_distance = distance
                            best_label = label

            if best_label:
                field.associated_label = best_label.text

            fields.append((field, best_label))

        return fields

    def _extract_action_buttons(self, elements: List[UIElement]) -> List[UIElement]:
        """提取可操作的按钮。"""
        buttons: List[UIElement] = []

        for elem in elements:
            if elem.element_type == UIElementType.BUTTON:
                buttons.append(elem)
            elif elem.is_interactive and elem.keywords:
                # 有操作关键词的可交互元素也视为按钮
                buttons.append(elem)

        # 按重要性排序：有关键词的优先
        buttons.sort(key=lambda b: (-len(b.keywords), b.bounding_box.y))

        return buttons