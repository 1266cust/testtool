import pytest
from test_tool.generators.action_classifier import classify_action, infer_case_type, infer_priority


class TestClassifyAction:
    def test_login_action(self):
        assert classify_action("用户登录", "登录模块") == "登录认证"
        assert classify_action("token验证", "认证") == "登录认证"

    def test_create_action(self):
        assert classify_action("新增用户", "用户管理") == "新增创建"
        assert classify_action("创建订单", "订单") == "新增创建"
        assert classify_action("添加商品", "商品") == "新增创建"

    def test_edit_action(self):
        assert classify_action("编辑信息", "信息管理") == "编辑修改"
        assert classify_action("修改配置", "配置") == "编辑修改"

    def test_delete_action(self):
        assert classify_action("删除记录", "记录管理") == "删除禁用"
        assert classify_action("禁用用户", "用户") == "删除禁用"

    def test_query_action(self):
        assert classify_action("查询列表", "列表") == "查询筛选"
        assert classify_action("搜索商品", "商品") == "查询筛选"

    def test_export_action(self):
        assert classify_action("导出数据", "数据") == "导入导出"
        assert classify_action("导入文件", "文件") == "导入导出"

    def test_payment_action(self):
        assert classify_action("支付订单", "订单") == "支付资金"
        assert classify_action("退款处理", "退款") == "支付资金"

    def test_approval_action(self):
        assert classify_action("审批流程", "流程") == "审批流转"
        assert classify_action("审核申请", "申请") == "审批流转"

    def test_permission_action(self):
        assert classify_action("权限配置", "权限") == "权限角色"
        assert classify_action("角色管理", "角色") == "权限角色"

    def test_generic_action(self):
        assert classify_action("普通操作", "其他") == "通用操作"


class TestInferCaseType:
    def test_performance_type(self):
        assert infer_case_type("性能测试要求") == "性能测试"
        assert infer_case_type("并发处理") == "性能测试"
        assert infer_case_type("响应时间限制") == "性能测试"

    def test_security_type(self):
        assert infer_case_type("安全验证") == "安全测试"
        assert infer_case_type("越权检测") == "安全测试"
        assert infer_case_type("注入防护") == "安全测试"

    def test_compatibility_type(self):
        assert infer_case_type("浏览器兼容") == "兼容性测试"
        assert infer_case_type("终端适配") == "兼容性测试"

    def test_api_type(self):
        assert infer_case_type("接口调用") == "接口测试"
        assert infer_case_type("api测试") == "接口测试"
        assert infer_case_type("http请求") == "接口测试"

    def test_functional_type(self):
        assert infer_case_type("普通功能") == "功能测试"
        assert infer_case_type("业务逻辑") == "功能测试"


class TestInferPriority:
    def test_high_priority(self):
        assert infer_priority("支付功能", "支付") == "P0"
        assert infer_priority("登录模块", "登录") == "P0"
        assert infer_priority("核心业务", "核心") == "P0"
        assert infer_priority("安全模块", "安全") == "P0"

    def test_medium_priority(self):
        assert infer_priority("查询功能", "查询") == "P1"
        assert infer_priority("列表展示", "列表") == "P1"
        assert infer_priority("搜索模块", "搜索") == "P1"

    def test_low_priority(self):
        assert infer_priority("导出功能", "导出") == "P2"
        assert infer_priority("帮助页面", "帮助") == "P2"

    def test_default_priority(self):
        assert infer_priority("其他功能", "其他") == "P1"