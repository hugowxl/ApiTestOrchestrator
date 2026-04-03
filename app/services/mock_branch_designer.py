"""LLM 驱动的 Mock 分支生成器。

根据业务描述，引导 LLM 生成多个 MockProfile（不同的业务数据配置）
以及对应的多轮对话测试场景，覆盖不同的业务执行路径。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    ConversationScenario,
    ConversationTurn,
    MockProfile,
    MockBranchSkill,
)
from app.services.llm_client import LLMClient

_log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是 AI Agent 测试分支设计专家。你的任务是根据用户描述的业务场景，分析出不同的业务执行路径，
并为每条路径设计：(1) Mock 数据配置集 (2) 多轮对话测试用例。

你需要覆盖以下四类 Mock 工作流数据：
- wealth_recommend: 理财产品推荐（包含 bankCardNumber, productList 等）
- balance_query: 余额查询（包含各卡尾号的余额，格式 card_XXXX_balance）
- transfer: 转账（包含 default_status, default_amount, fail_cause 等）
- wealth_purchase: 理财购买/申购（包含 default_product_code, default_product_name, default_amount,
  default_purchase_status, fail_cause, default_confirmed_shares, order_id_prefix 等）

其中：wealth_recommend 的 productList 可能包含多条产品，但 wealth_purchase 必须只选择其中一条进行购买。
为保证“推荐-购买”上下关联，建议 wealth_purchase 额外包含：
- selected_product_code 或 selected_product_name：其值必须来自 wealth_recommend.productList 中的某一条（优先 code）。

每条分支的 profile_data 应包含上述工作流中与该分支相关的字段。

必须只输出一个 JSON 对象，不要 Markdown 代码围栏，不要前后说明文字。

【输出结构】
{
  "branches": [
    {
      "branch_name": "分支名称",
      "branch_description": "该分支覆盖的业务路径描述",
      "profile_data": {
        "wealth_recommend": { ... },
        "balance_query": { "card_1122_balance": 50000.0, ... },
        "transfer": { "default_status": "成功", ... },
        "wealth_purchase": { "default_purchase_status": "成功", ... }
      },
      "conversation_turns": [
        {
          "turn_index": 0,
          "user_message": "用户说的话",
          "expected_keywords": ["期望Agent回复包含的关键词"],
          "expected_intent": "期望意图（可选）"
        }
      ]
    }
  ]
}

【要求】
- 每条分支的 profile_data 中的数值要合理且彼此有区分度
- conversation_turns 中的 user_message 要自然、口语化
- expected_keywords 用于验证 Agent 是否走了预期路径
- 不同分支之间要覆盖不同的业务路径（如：正常/异常/边界）"""


def ensure_default_mock_branch_skill(db: Session) -> MockBranchSkill:
    """确保数据库里存在默认 Skill（用于一键生成测试分支）。"""
    existing = (
        db.query(MockBranchSkill)
        .filter(MockBranchSkill.enabled == True)  # noqa: E712
        .order_by(MockBranchSkill.created_at.desc())
        .first()
    )
    if existing:
        return existing

    skill = MockBranchSkill(
        name="默认 Mock 分支生成器",
        description="使用内置 SYSTEM_PROMPT 生成 MockProfile（推荐/余额/转账/购买）。",
        system_prompt=SYSTEM_PROMPT,
        enabled=True,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def generate_branches(
    db: Session,
    scenario: ConversationScenario,
    business_description: str,
    *,
    max_branches: int = 3,
    max_turns_per_branch: int = 5,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """调用 LLM 生成多个 MockProfile + ConversationScenario 分支。

    Returns:
        包含 created_scenarios / created_profiles 计数的字典。
    """
    llm = LLMClient()

    target = scenario.agent_target
    tools_info = ""
    if target and target.agent_tools:
        tools_info = f"\n\n该 Agent 的工具列表：{target.agent_tools}"

    user_prompt = f"""\
【业务场景描述】
{business_description}

【当前测试场景】
场景名称：{scenario.name}
场景描述：{scenario.description or '无'}
{tools_info}

【生成要求】
- 生成 {max_branches} 个不同的测试分支
- 每个分支最多 {max_turns_per_branch} 轮对话
- 分支之间的 profile_data 数据要有明确区分（如余额充足 vs 不足）
- 每个分支的对话流程要符合该分支的 Mock 数据设定"""

    prompt = system_prompt or SYSTEM_PROMPT
    raw = llm.chat_json(prompt, user_prompt, use_json_object_mode=True)
    data = llm.parse_json_strict(raw)
    branches = data.get("branches", [])

    created_scenarios = 0
    created_profiles = 0

    for branch in branches:
        branch_name = branch.get("branch_name", f"分支-{created_scenarios + 1}")
        branch_desc = branch.get("branch_description", "")
        profile_data = branch.get("profile_data", {})
        turns_data = branch.get("conversation_turns", [])

        new_scenario = ConversationScenario(
            agent_target_id=scenario.agent_target_id,
            name=f"{scenario.name} - {branch_name}",
            description=branch_desc,
            tags=["auto-branch", *(scenario.tags or [])],
            initial_context=scenario.initial_context,
            max_turns=max_turns_per_branch,
            parent_scenario_id=scenario.id,
        )
        db.add(new_scenario)
        db.flush()

        mp = MockProfile(
            scenario_id=new_scenario.id,
            name=branch_name,
            description=branch_desc,
            profile_data=profile_data,
            is_active=True,
        )
        db.add(mp)
        db.flush()
        new_scenario.active_mock_profile_id = mp.id

        for t in turns_data:
            db.add(ConversationTurn(
                scenario_id=new_scenario.id,
                turn_index=t.get("turn_index", 0),
                user_message=t.get("user_message", ""),
                expected_intent=t.get("expected_intent"),
                expected_keywords=t.get("expected_keywords"),
                assertions=t.get("assertions", [{"type": "response_not_empty"}]),
            ))

        created_scenarios += 1
        created_profiles += 1

    db.commit()

    _log.info(
        "Branch generation complete: %d scenarios, %d profiles for scenario=%s",
        created_scenarios, created_profiles, scenario.id,
    )
    return {"created_scenarios": created_scenarios, "created_profiles": created_profiles}
