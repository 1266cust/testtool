from __future__ import annotations

from typing import List, Tuple

ACTION_RULES: List[Tuple[str, List[str]]] = [
    ("登录认证", ["登录", "登出", "退出", "token", "验证码", "密码", "认证", "鉴权"]),
    ("新增创建", ["新增", "创建", "新建", "添加", "提交", "申请"]),
    ("编辑修改", ["编辑", "修改", "更新", "变更", "保存"]),
    ("删除禁用", ["删除", "移除", "禁用", "作废", "停用"]),
    ("查询筛选", ["查询", "搜索", "筛选", "过滤", "列表", "详情", "查看"]),
    ("导入导出", ["导入", "导出", "下载", "上传", "模板"]),
    ("审批流转", ["审批", "审核", "驳回", "通过", "流转", "提交审核"]),
    ("支付资金", ["支付", "退款", "扣款", "充值", "提现", "资金"]),
    ("通知消息", ["短信", "邮件", "通知", "消息", "推送", "站内信"]),
    ("权限角色", ["权限", "角色", "菜单", "可见", "越权"]),
]


def classify_action(point: str, module_name: str) -> str:
    text = f"{module_name} {point}".lower()
    for action, keys in ACTION_RULES:
        if any(k in text for k in keys):
            return action
    return "通用操作"


def infer_case_type(text: str) -> str:
    haystack = text.lower()
    if any(k in haystack for k in ["性能", "并发", "响应时间", "吞吐"]):
        return "性能测试"
    if any(k in haystack for k in ["安全", "越权", "注入", "鉴权"]):
        return "安全测试"
    if any(k in haystack for k in ["兼容", "浏览器", "终端", "机型"]):
        return "兼容性测试"
    if any(k in haystack for k in ["接口", "api", "http", "返回码"]):
        return "接口测试"
    return "功能测试"


def infer_priority(text: str, module: str) -> str:
    high_keywords = ["支付", "下单", "资金", "安全", "登录", "注册", "核心", "主流程"]
    medium_keywords = ["查询", "列表", "搜索", "展示"]
    low_keywords = ["导出", "帮助", "关于"]

    haystack = (text + " " + module).lower()

    if any(k.lower() in haystack for k in high_keywords):
        return "P0"
    if any(k.lower() in haystack for k in medium_keywords):
        return "P1"
    if any(k.lower() in haystack for k in low_keywords):
        return "P2"
    return "P1"