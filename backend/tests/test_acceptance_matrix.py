"""验收矩阵：项目要求 2.8.10 的 9 条验收标准与自动化用例的对应关系。

跑 `pytest tests/test_acceptance_matrix.py -v` 可以看到每条验收项落到哪些用例。
真实断言在 test_ac01_*.py 与 test_ac_chain.py，本文件只做覆盖登记，
并注明每条的实现边界（哪些是真实链路、哪些用了本地替代组件）。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.acceptance

COVERAGE = {
    "AC-01": ("test_ac01_role_separation.py", "独立三角色配置 + 职责混用硬拦截 + 审批槽/能力推导"),
    "AC-02": ("test_ac_chain.py", "SQLite 数据源接入 + 只读探查 + 脱敏样本（其他类型返回 UNSUPPORTED）"),
    "AC-03": ("test_ac_chain.py", "意图解析 + 缺参中断 + Checkpoint 恢复后生成 EtlPlan/HOCON（规则化生成器）"),
    "AC-04": ("test_ac_chain.py", "确定性门禁（7 类检查）+ 不可变版本 SHA256 与组件分片摘要"),
    "AC-05": ("test_ac_chain.py", "Prepare 冻结事实 / 双槽四眼审批 / Commit 签发 Ed25519 单次 Capability / 重放拦截"),
    "AC-06": ("test_ac_chain.py", "本地执行器真实读写 + 质量契约分流写入错误表（SeaTunnel 未接入）"),
    "AC-07": ("test_ac_chain.py", "影子表校验通过后改名 Swap 发布 + 实时指标与质量报告"),
    "AC-08": ("test_ac_chain.py", "预算超限硬中断 + 失败快照 + 根因诊断 + 受管回滚清理"),
    "AC-09": ("test_ac_chain.py", "Benchmark 套件运行 + 准确率与 P0/P1 拦截率报告"),
}

LIMITATIONS = {
    "AC-02": "仅 SQLite 类型的连接参与真实探查；MySQL/Doris 等依赖驱动与实例，当前明确返回 UNSUPPORTED 而不是伪造成功。",
    "AC-03": "生成器是规则化的确定性实现，未接 LLM Provider；中断/恢复状态机与 LangGraph 语义对齐，但不是 LangGraph 运行时。",
    "AC-06": "执行器在本地进程内同步执行，未接 Celery Worker 与 SeaTunnel Zeta；数据搬运、分流、指标均真实发生。",
    "AC-07": "Swap 用 SQLite 表改名实现（等价语义），未接 Doris REPLACE TABLE 语法。",
}


@pytest.mark.parametrize("criterion", sorted(COVERAGE))
def test_criterion_is_covered(criterion: str):
    module, description = COVERAGE[criterion]
    assert module and description
    # 覆盖登记必须指向真实存在的测试文件
    import os

    path = os.path.join(os.path.dirname(__file__), module)
    assert os.path.exists(path), f"{criterion} 指向的用例文件不存在：{module}"


def test_all_nine_criteria_registered():
    assert len(COVERAGE) == 9
    assert set(COVERAGE) == {f"AC-0{i}" for i in range(1, 10)}


def test_limitations_are_documented():
    """有替代实现的三条必须写明边界，禁止把本地替代说成完整实现。"""
    assert set(LIMITATIONS) == {"AC-02", "AC-03", "AC-06", "AC-07"}
