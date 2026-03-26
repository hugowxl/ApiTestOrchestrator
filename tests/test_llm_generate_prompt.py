"""LLM 生成用例：user prompt 拼装（业务说明 + 场景组合）。"""

from app.services.llm_test_designer import (
    _MAX_BUSINESS_CONTEXT_IN_PROMPT,
    _MAX_ENDPOINT_NOTES_IN_PROMPT,
    _expand_scenario_matrix,
    build_generate_user_prompt,
    compute_scenario_path_coverage,
)


def test_build_prompt_without_business_omits_section():
    p = build_generate_user_prompt('{"paths":{}}', None)
    assert "【OpenAPI 片段】" in p
    assert '{"paths":{}}' in p
    # 仅在有业务说明时插入的标题（任务正文会提到类似字样，故不用短标题判断）
    assert "【业务规则与场景说明（产品/领域知识，与 OpenAPI 互补）】" not in p
    assert "【★高优先级｜测试负责人对「当前接口」的专项说明】" not in p
    assert "【任务】" in p


def test_build_prompt_includes_endpoint_focus_notes():
    p = build_generate_user_prompt(
        "{}",
        None,
        endpoint_test_design_notes="必须覆盖鉴权失败与超时重试",
    )
    assert "【★高优先级｜测试负责人对「当前接口」的专项说明】" in p
    assert "必须覆盖鉴权失败与超时重试" in p
    # 专项说明紧接在 OpenAPI 之后、在通用业务说明之前（此处无业务说明）
    openapi_pos = p.index("【OpenAPI 片段】")
    focus_pos = p.index("【★高优先级")
    assert focus_pos > openapi_pos


def test_build_prompt_truncates_long_endpoint_notes():
    long_n = "n" * (_MAX_ENDPOINT_NOTES_IN_PROMPT + 50)
    p = build_generate_user_prompt("{}", None, endpoint_test_design_notes=long_n)
    assert "…(接口专项说明过长已截断)" in p
    assert long_n not in p


def test_build_prompt_with_business_includes_section():
    p = build_generate_user_prompt("{}", "订单 paid 后才可发货")
    assert "【业务规则与场景说明（产品/领域知识，与 OpenAPI 互补）】" in p
    assert "订单 paid 后才可发货" in p
    assert "【契约优先级】" in p


def test_build_prompt_truncates_long_business_context():
    long_ctx = "x" * (_MAX_BUSINESS_CONTEXT_IN_PROMPT + 100)
    p = build_generate_user_prompt("{}", long_ctx)
    assert "…(业务说明过长已截断)" in p
    assert long_ctx not in p
    assert "x" * (_MAX_BUSINESS_CONTEXT_IN_PROMPT + 1) not in p


def test_expand_scenario_matrix_cartesian_and_limit():
    lines, total, limited = _expand_scenario_matrix(
        {
            "推荐产品数": ["0", "1"],
            "理财卡余额": ["足够", "不足"],
            "转账结果": ["成功后购买", "失败直接退出"],
        },
        max_combinations=4,
    )
    assert total == 8
    assert limited is True
    assert len(lines) == 4
    assert lines[0].startswith("path-001:")
    assert "推荐产品数=0" in lines[0]
    assert "理财卡余额=足够" in lines[0]


def test_build_prompt_includes_expanded_paths():
    p = build_generate_user_prompt(
        "{}",
        "场景说明",
        {"推荐产品数": ["0", "1"], "理财卡余额": ["足够"]},
        scenario_max_combinations=10,
    )
    assert "【业务场景路径组合（由场景矩阵自动展开）】" in p
    assert "path-001:" in p
    assert "path-002:" in p
    assert "【覆盖要求】请对每条 path-xxx 至少生成 1 条 test_case" in p


def test_compute_path_coverage_disabled_without_matrix():
    r = compute_scenario_path_coverage(None, scenario_max_combinations=10, test_case_names=["任意"])
    assert r.enabled is False
    assert r.coverage_ratio == 0.0
    assert r.expected_paths == []


def test_compute_path_coverage_matches_names():
    r = compute_scenario_path_coverage(
        {"A": ["1", "2"]},
        scenario_max_combinations=10,
        test_case_names=["path-001 成功", "path-002 失败"],
    )
    assert r.enabled is True
    assert r.expanded_paths_count == 2
    assert r.covered_paths == ["path-001", "path-002"]
    assert r.missing_paths == []
    assert r.coverage_ratio == 1.0
    assert "path-001" in r.path_labels


def test_compute_path_coverage_case_insensitive():
    r = compute_scenario_path_coverage(
        {"A": ["x"]},
        scenario_max_combinations=10,
        test_case_names=["PATH-001 场景"],
    )
    assert r.covered_paths == ["path-001"]
    assert r.missing_paths == []


def test_compute_path_coverage_detects_missing():
    r = compute_scenario_path_coverage(
        {"A": ["1", "2"]},
        scenario_max_combinations=10,
        test_case_names=["仅 path-001"],
    )
    assert r.missing_paths == ["path-002"]
    assert r.coverage_ratio == 0.5
