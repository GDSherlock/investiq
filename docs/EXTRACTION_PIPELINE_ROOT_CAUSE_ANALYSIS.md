# Extraction Pipeline 根因调查报告

> 调查日期：2026-07-13
> 工作位置：`.claude/worktrees/Modelextratcion_test`（仓库实际拼写）
> 范围：只读调查；未修改 extraction pipeline。
> 样本：`01_solar_pv_project_finance.xlsx` 与 API 响应 `response_1783932046027.json`。

## 1. 结论先行

当前问题不是 FastAPI 在最终序列化时把正确分桶的数据清空。真实数据流是：

```text
read_range 读取完整范围
  -> AzureDriver.observe 把工具结果硬截断到 12,000 字符
  -> Agent 只看到宽表前部和 inspect_sheet 的前 8 行缓存值预览
  -> Agent 漏提取大量输入/公式行/时间序列，并把 31 个 candidate 全塞进 parameter_candidates
  -> 后端未执行 canonical submit schema 校验，缺少必填 output_candidates 仍 accepted
  -> Validator 31 进 31 出，只产生 validation_results，不重建/重分桶 FinalExtraction
  -> API 原样返回 Agent 的 final_extraction
```

主根因按严重度排序：

1. **Parser/observation（首要）**：`agent_loop.py:189-194` 对每次工具输出做 `[:12000]` 字符截断。coverage 记为已读，但 Agent 实际只看到部分 JSON。
2. **Schema enforcement**：canonical schema 存在但后端未执行；真实 payload 缺少必填 `output_candidates`，仍 `submitted=true`。
3. **Agent classification**：31 个 candidate 全在 `parameter_candidates`；validated roles 实际为 14 derived、6 output、9 hardcoded input、2 scenario input。
4. **Routing**：没有 validation 后统一 router，也没有 validated `FinalExtraction`。
5. **Coverage gate**：只证明调用过 inspect/read，不证明完整观察或提取到内容。
6. **Financial series**：没有确定性 row/range grouping，series schema 也只是通用单 cell candidate。
7. **Review summary**：7 个 result 的 `review_required=true`，但 summary 为 0。
8. **Serialization 不是本次根因**：31 个 candidate_id 在 Validator 前后零丢失；API 返回的就是 Agent 原始对象。

## 2. 五节点主线与计数

| 节点 | 实际对象 | 数量 | 证据 |
|---|---|---:|---|
| Agent submit | candidate buckets（不含 metadata/structures） | 31 | 全在 `parameter_candidates` |
| Validator input | 7 个 candidate bucket 汇总 | 31 | `validator.py:183-197` |
| Validation output | `validation_results` | 31 | 27 validated + 2 validated_null + 1 reclassified + 1 rejected |
| Router output | 不存在 | N/A | 没有 routing function |
| API final serialized | 原始 Agent candidate buckets | 31 | `workbook_validation.py:137` |

补充口径：

- Agent 共提交 **42 个带 candidate_id 的对象**：11 metadata + 31 candidate。
- Validator 不读取 `metadata`；这 11 个不是中途丢失，而是设计上不参与 validation。
- 31 个 submitted IDs 与 validation IDs 完全相等：
  - `dropped_candidate_ids = []`
  - `extra_validation_ids = []`
  - 无重复 ID。
- 未被 Agent 创建的 workbook cell 没有 candidate_id，不能伪造 dropped ID；例如 `Project Setup!C14:C16`、`C20:C25` 与 Debt Sculpting 各行属于 discovery omission。

### 2.1 守恒检查

| 检查 | 当前结果 |
|---|---|
| `agent_submitted_count == validator_input_count` | 31 == 31，成立（candidate 口径） |
| `validation_result_count == validated + reclassified + rejected + validated_null` | 31 == 27 + 1 + 1 + 2，成立 |
| `routed_candidate_count == validation_result_count` | 无法检查；router 不存在 |
| `final_serialized_count == routed_candidate_count` | 无法检查；API 返回原始 submit |
| `dropped_candidate_count > 0` gate | 未实现 |
| `dropped_candidate_ids` | 未实现；本次离线集合对比为 `[]` |

## 3. 当前 canonical schema

代码库里**没有名为 `FinalExtraction` 的 Pydantic model**。当前唯一 canonical extraction contract 是 `experiments/workbook_agent_poc/extraction_contract.py:47-63` 的 `SUBMIT_RESULT_SCHEMA`（JSON Schema dict）。

### 3.1 顶层字段

| 字段 | 类型 | required | 真实 payload |
|---|---|---:|---|
| `metadata` | candidate[] | 否 | 11 |
| `all_assumption_candidates` | candidate[] | 是 | 0 |
| `parameter_candidates` | candidate[] | 否 | 31 |
| `derived_value_candidates` | candidate[] | 否 | **缺失** |
| `output_candidates` | candidate[] | **是** | **缺失** |
| `financial_series_candidates` | candidate[] | 否 | **缺失** |
| `scenario_structures` | object[] | 否 | 0 |
| `sensitivity_structures` | object[] | 否 | 0 |
| `unclassified_inputs` | candidate[] | 否 | **缺失** |
| `review_candidates` | candidate[] | 否 | **缺失** |
| `coverage_declaration` | object | 否 | 有 |

真实 payload 做 Draft 2020-12 校验：

```text
schema_errors 1
[] 'output_candidates' is a required property
```

但 submit 仍返回 `{"received": true, "candidate_count": 31}`，证明 schema 没有在后端边界执行。

### 3.2 Candidate contract

Properties：

```text
candidate_id, original_label, submitted_role, raw_value,
displayed_value, unit, period, scenario, source_references,
formula_status, reasoning_summary, llm_confidence,
category, canonical_name, evidence
```

Required：

```text
candidate_id, original_label, submitted_role, raw_value, source_references
```

Role enum：

```text
hardcoded_input, scenario_input, parameter,
formula_derived_value, formula_output, hardcoded_display_output,
sensitivity_output, scenario_selector, financial_series,
metadata, label, header, period_header, presentation_only, unknown
```

### 3.3 Prompt/tool/Pydantic 一致性

- System prompt 明确要求 derived/output 分桶，见 `extraction_contract.py:96-122`。
- submit tool parameters 直接引用 `SUBMIT_RESULT_SCHEMA`，见 `extraction_contract.py:90-93`。
- **不存在 FinalExtraction Pydantic model 可比较**。
- FastAPI response 的 `final_extraction` 只是 `dict[str, Any]`（`schemas.py:22-38`），不验证内部 bucket/candidate。
- `WorkbookValidationResponse` 未设 `extra="forbid"`；Pydantic 默认忽略未知**顶层**字段。实测未知顶层字段被丢弃，但 `final_extraction` 内未知 bucket 原样保留。
- 没有 Pydantic list `default_factory=list`；空数组来自 Agent，或 `.get(key, [])` 的读取默认。
- Validator 兼容旧式 `value` 与 `candidate_type`（`validator.py:38-43`），而正式 schema 使用 `raw_value` 与 `submitted_role`。这是未声明的 legacy compatibility。
- 未找到“字段重命名后旧字段仍由 Agent 使用”的提交证据；这些 bucket 当前同时存在于 schema。
- schema 未设 `additionalProperties:false`，tool 未启用 strict；最关键仍是后端没有再次验证。
- Validator 可产生 `formula_external`，但该值不在 submit `ROLE_ENUM`，validated role universe 与 submit role universe 也不完全一致。
- `summary_output` 不在 `roles.py` family 映射，会落入 unknown。

### 3.4 Missing 与 [] 被等价

是：

- `workbook_tools.py:270-272`：`result.get(k, [])`
- `validator.py:191`：`extraction.get(b, []) or []`
- `agent_loop.py:116`：`final_extraction or {}`

本次 raw 区别：

- `all_assumption_candidates`：字段存在，值为 `[]`
- `output_candidates` 等：字段完全缺失

当前统计语义没有保留这个区别。

## 4. Agent 实际提交

### 4.1 Bucket 数量

| Bucket | Raw 状态 | 数量 |
|---|---|---:|
| metadata | 存在 | 11 |
| all_assumption_candidates | 存在 | 0 |
| parameter_candidates | 存在 | 31 |
| derived_value_candidates | 缺失 | effective 0 |
| output_candidates | 缺失（违反 required） | effective 0 |
| financial_series_candidates | 缺失 | effective 0 |
| unclassified_inputs | 缺失 | effective 0 |
| review_candidates | 缺失 | effective 0 |
| scenario_structures | 存在 | 0 |
| sensitivity_structures | 存在 | 0 |

`candidate_count` 在 `workbook_tools.py:267-273` 汇总五个主 bucket，不是定义上只数 parameter；但本次其他四个 bucket missing/empty，因此 **31 全来自 parameter_candidates**。

### 4.2 角色数量

| submitted_role | 数量 |
|---|---:|
| hardcoded_input | 11 |
| scenario_input | 2 |
| formula_derived_value | 12 |
| formula_output | 6 |

Validator 后：

| validated_role | 数量 |
|---|---:|
| hardcoded_input | 9 |
| scenario_input | 2 |
| formula_derived_value | 14 |
| formula_output | 6 |

Agent 实际生成了 assumptions/inputs、derived values 和 outputs，只是全错放一个 bucket；没有生成 financial series。

### 4.3 完整 ID、来源与状态

| ID | Label | 原 role | Source | Validation | validated_role | review |
|---|---|---|---|---|---|---:|
| p1 | Project capacity | hardcoded_input | Project Setup!C5 | validated | hardcoded_input | false |
| p2 | Construction start | hardcoded_input | Project Setup!C6 | validated | hardcoded_input | false |
| p3 | Construction period | hardcoded_input | Project Setup!C7 | validated | hardcoded_input | false |
| p4 | Operating life | hardcoded_input | Project Setup!C8 | validated | hardcoded_input | true |
| p5 | Base power price | hardcoded_input | Project Setup!C9 | validated | hardcoded_input | false |
| p6 | Power price escalation | hardcoded_input | Project Setup!C10 | validated | hardcoded_input | false |
| p7 | Net capacity factor | hardcoded_input | Project Setup!C11 | validated | hardcoded_input | false |
| p8 | Annual degradation | hardcoded_input | Project Setup!C12 | validated | hardcoded_input | true |
| p9 | Total EPC cost | hardcoded_input | Project Setup!C13 | validated | hardcoded_input | true |
| d1 | Construction % | scenario_input | Build Schedule!B4 | validated | scenario_input | false |
| d2 | Construction % | scenario_input | Build Schedule!C4 | validated | scenario_input | false |
| d3 | Base EPC spend | formula_derived_value | Build Schedule!B5 | validated | formula_derived_value | false |
| d4 | Contingency | formula_derived_value | Build Schedule!B6 | validated | formula_derived_value | false |
| d5 | Total capex | formula_derived_value | Build Schedule!B7 | validated | formula_derived_value | false |
| d6 | Cumulative capex | formula_derived_value | Build Schedule!B8 | validated | formula_derived_value | false |
| s1 | Operating flag | formula_derived_value | Solar Operations!B4 | validated | formula_derived_value | false |
| s2 | Net generation (GWh) | formula_derived_value | Solar Operations!B5 | validated | formula_derived_value | false |
| s3 | Power price ($/MWh) | hardcoded_input | Solar Operations!B6 | reclassified | formula_derived_value | true |
| s4 | Revenue ($mm) | formula_derived_value | Solar Operations!B7 | validated | formula_derived_value | false |
| s5 | Fixed O&M ($mm) | hardcoded_input | Solar Operations!B8 | rejected | formula_derived_value | true |
| c1 | Revenue | formula_derived_value | Cash Flow!B4 | validated | formula_derived_value | false |
| c2 | EBITDA | formula_derived_value | Cash Flow!B5 | validated | formula_derived_value | false |
| c3 | Capex | formula_derived_value | Cash Flow!B6 | validated | formula_derived_value | false |
| c4 | Tax | formula_derived_value | Cash Flow!B7 | validated | formula_derived_value | false |
| c5 | CFADS | formula_derived_value | Cash Flow!B8 | validated | formula_derived_value | false |
| r1 | Total project cost | formula_output | Investor Returns!B5 | validated | formula_output | false |
| r2 | Peak debt | formula_output | Investor Returns!B6 | validated | formula_output | false |
| r3 | Minimum DSCR | formula_output | Investor Returns!B7 | validated | formula_output | false |
| r4 | Project IRR | formula_output | Investor Returns!B8 | validated_null | formula_output | true |
| r5 | Equity IRR | formula_output | Investor Returns!B9 | validated_null | formula_output | true |
| r6 | Average EBITDA margin | formula_output | Investor Returns!B10 | validated | formula_output | false |

异常：

- `s3` 实际是 formula，Validator 正确 reclassify。
- `s5` 提交 2.4，但 `Solar Operations!B8` cached value 是 0；2.4 是后续运行期列值，Validator 正确 rejected。
- `r4/r5` 为 formula_no_cache，正确保留 `raw_value=null`，没有被丢弃。

### 4.4 Trace 与原始 payload

Trace 是刻意省略 submit 参数：

- `agent_loop.py:73` coverage record 使用 `{"result":"<omitted>"}`
- `agent_loop.py:78-79` trace 使用 `"arguments":"<result omitted>"`
- `agent_loop.py:84` 仍把完整 `args["result"]` 保存为 `final_extraction`

所以 API response 的 `final_extraction` 就是完整原始 payload。可以增加受控 debug artifact：run_id、workbook hash、timestamp、schema errors、每层 count/IDs；应有敏感数据策略与访问控制，不能只依赖 trace preview。

## 5. 上游 observation 截断

`AzureDriver.observe()`：

```python
"output": json.dumps(result, default=str, ensure_ascii=False)[:12000]
```

离线按同一代码复现：

| Sheet | 完整 JSON 字符 | 实际上限 | 最后完整 source_reference |
|---|---:|---:|---|
| Project Setup | 23,377 | 12,000 | Project Setup!C13 |
| Build Schedule | 66,185 | 12,000 | Build Schedule!D4 |
| Solar Operations | 110,896 | 12,000 | Solar Operations!C4 |
| Debt Sculpting | 93,521 | 12,000 | Debt Sculpting!D4 |
| Cash Flow | 102,562 | 12,000 | Cash Flow!E4 |
| Investor Returns | 6,433 | 6,433 | Investor Returns!B10 |

因果对应：

- Project Setup 正好只提取到 C13；C14:C16 与 C20:C25 全漏。
- Investor Returns 不截断，6 个 output 全发现。
- 宽表绝大部分 formula facts 未回传；Agent 主要依赖 `inspect_sheet` 前 8 行/8 列 cached-value preview。
- inspect preview 不显示 formula 字符串（`workbook_tools.py:144-169`），所以 Solar B6/B8 被误判 hardcoded。
- Debt Sculpting 有 preview 但 Agent 零 candidate，coverage 没发现 semantic omission。
- 字符截断发生在 JSON 中间，回传甚至不是完整 JSON。

API 的 `trace_truncated=true` 来自另一个 200 字符 trace preview，不是 12,000 字符 model observation 的精确遥测。

## 6. Candidate 收集与 Validation

Validator 读取：

```text
all_assumption_candidates
parameter_candidates
derived_value_candidates
output_candidates
financial_series_candidates
unclassified_inputs
review_candidates
```

位置：`validator.py:183-197`。它不是只读 parameter；本次只有 parameter 非空。

未纳入普通 candidate validation：

- `metadata`
- `scenario_structures`
- `sensitivity_structures`

另外：

- 没有 `rejected_candidates` bucket。
- `review_candidates` 只作为输入读取，validation 后不会写入。
- `_bucket` 只记录来源，不重分桶。
- scenario/sensitivity structure 应有独立 schema/validator，不应当普通 cell candidate。


## 7. Validation 前后是否丢数据

对 31 个 candidate：**没有 candidate_id 丢失**。

流程：

1. `agent_loop.py:84` 保存 Agent 原始 dict。
2. Validator 为每个 candidate 生成一个 result。
3. `workbook_validation.py:115` 接收 validation list。
4. `workbook_validation.py:137` 返回原始 `run["final_extraction"]`。
5. `workbook_validation.py:139` 另行返回 validation_results。

不存在：

- `FinalExtraction()` 空对象覆盖；
- shallow/deep copy 或 model_dump 丢字段；
- async 后一步覆盖；
- validation 后重建空对象。

但存在语义缺口：

- validation 不更新 final_extraction；
- reclassified s3 仍在原始 parameter bucket；
- rejected s5 仍在原始 parameter bucket；
- review_required 不写 review bucket；
- validated_role 不写回 canonical bucket；
- API 同时给出“原始错桶 final_extraction”和“正确角色 validation_results”，消费者容易选错。

## 8. Routing 现状与建议规则

当前**没有统一 routing function**。建议 precedence：

```text
review/rejected policy
  > validated_role
  > submitted_role（仅 validated_deferred 且策略明确时）
  > original bucket（只作 audit metadata）
```

| 条件/validated_role | 目标 |
|---|---|
| rejected | 新增 `rejected_candidates`，保留 reason/evidence；可另进 review queue |
| review_required=true | `review_candidates` 优先 |
| hardcoded_input / scenario_input | `all_assumption_candidates` |
| parameter | `parameter_candidates` |
| formula_derived_value | `derived_value_candidates` |
| formula_output / hardcoded_display_output / sensitivity_output | `output_candidates` |
| financial_series | `financial_series_candidates` |
| unknown / 无法分类 input | `unclassified_inputs` |
| metadata/label/header | `metadata` |
| scenario/sensitivity structure | 独立 structure validator |

Router 必须从旧 bucket 删除后只写一个新 bucket，以 candidate_id 去重，并保留 submitted_role、validated_role、original_bucket、rejection/source/role/value evidence。必须输出 routed/dropped/duplicate IDs。

## 9. API 序列化

数据源：

- `final_extraction`：Agent 原始提交，`workbook_validation.py:137`
- `validation_results`：deterministic validator，`workbook_validation.py:139`

结论：

- route 使用当前 `WorkbookValidationResponse`，不是旧 response model（`routers/models.py:46-70`）。
- 未发现显式 `model_dump(exclude_unset/exclude_none/exclude_defaults)`。
- 未发现 alias 配置。
- `final_extraction: dict[str, Any]` 不过滤内部 bucket。
- `UUIDJSONResponse` 只处理 UUID/datetime，不初始化列表。
- 空/缺失 bucket 在 Agent submit 时已形成，不是 FastAPI 时形成。
- 未声明 top-level 字段会被 Pydantic 默认忽略；这不是本次已声明字段丢失原因。

API 最终 bucket 数量与原始 submit 相同：metadata 11、all_assumption 0、parameter 31，其余 candidate bucket missing/effective 0。

## 10. Coverage Gate

当前 gate（`coverage_gate.py:92-119`）只要求：

- 调用过 metadata；
- 每张 sheet 调用过 inspect；
- 每个 content sheet 至少调用一次 read_range/get_cell/get_formulas。

它不检查：

- read_range 回传给模型是否完整；
- cell/range 覆盖率；
- 每张 sheet 是否产生 candidate/series 或 no-content 声明；
- minimum assumption/output/series count；
- candidate bucket 是否全空；
- schema 是否有效；
- validator/routing/serialization 守恒；
- dropped IDs。

所以 Debt Sculpting 已读但零 candidate、Project Setup 只提取 9/18 静态输入、甚至所有 candidate bucket 为空，仍可 `submitted=true`。Agent 的 `coverage_declaration` 不参与 gate；executed call 也不能证明模型完整看过结果。

应增加：

1. **Observation coverage**：chunk 完整回传、cell IDs、最后可见 cell、JSON 完整性、所有 chunk ack。
2. **Extraction coverage**：每个 material row/sheet 产生 candidate/series，或结构化 `no_extractable_content + reason`；最低 input/output 与 dropped=0。

## 11. Financial Series

本次 workbook 的 series 很明确：

- Build Schedule：B3:AB3 为 27 年；rows 4-8 为 5 条序列。
- Solar Operations：rows 4-11 为 8 条公式序列。
- Debt Sculpting：rows 4-10 为 7 条公式序列。
- Cash Flow：rows 4-11 为 8 条公式序列。

为空的原因：

1. 宽表 read_range 回传被截断。
2. prompt 只泛化提及 repeated columns/period headers，未强制 series contract。
3. `financial_series_candidates` 复用单 cell candidate schema，没有 periods、values、range、formula_pattern。
4. 没有后处理 row/range grouping。
5. Agent 每 row 只提交一个代表单元格，未形成 series。

建议后端从 workbook/validated facts 确定性聚合：

- 识别 period header row；
- 识别相同行 label；
- 聚合连续横向 cells；
- 标准化相对 formula pattern；
- 保存 source range、periods、raw/cached values、formula statuses；
- LLM 只补语义 label/role。

## 12. Assumption 提取

Project Setup 有 18 个明确 label-unit-value 静态数值：

- 已提交：`C5:C13`，9 个。
- 漏：`C14:C16`，3 个。
- 漏第二段 Financing Inputs：`C20:C25`，6 个。

最后完整可见 source ref 正是 C13，随后 JSON 在 A14 中途截断。因此不是空行/merged header 让 parser 停止，而是 observation cutoff；A18 merged section 后第二表完全不可见。

另外：

- Build Schedule B4/C4 被提交 scenario_input；D4:AB4 是否为完整 schedule series 需明确策略。
- hardcoded input 应进入 assumption family，但 Agent 全放 parameter。
- dependency graph 只用于 validation，没有从公式 precedents 反向补提静态输入的 discovery backtracking。
- 公式引用 C14/C15/C16/C20:C25，本可 deterministic backtracking 补漏。
- 未见固定 candidate 数上限；真正限制是 tool/iteration/deadline 与 12,000 字符 cutoff。
- assumption 与 parameter 在 `roles.py` 是同一 family，但 schema 分 bucket，业务定义需明确。

## 13. Derived Value 与 Output

- 12 个 `formula_derived_value` 在 `parameter_candidates`。
- 6 个 `formula_output` 在 `parameter_candidates`。
- Validator 将 s3/s5 再识别为 derived，validated derived 共 14。
- Investor Returns 的 Total project cost、Peak debt、Minimum DSCR、Project IRR、Equity IRR、Average EBITDA margin 均生成但错桶。
- Cash Flow 只生成 B4:B8；B9:B11 与完整 series 未生成。
- Solar Operations 只生成 B4:B8；rows 9-11 未生成。
- Debt Sculpting 零 candidate。
- formula_no_cache r4/r5 正确保留为 output + null。

结构规则：

- formula + downstream dependents -> formula_derived_value
- formula + no dependents -> formula_output
- 但 `reconcile()` 对已提交 derived/output 的 formula 保留 Agent 的语义子分类；这是刻意允许 semantic choice。
- summary leaf formula 通常识别 output。
- 无 final router，因此正确 validated_role 不体现在 final bucket。

## 14. Review 与 Rejected

真实结果：

- `review_required=true`：7 个
  `p4, p8, p9, s3, s5, r4, r5`
- rejected：s5
- reclassified：s3
- validated_null：r4、r5
- validated_deferred 导致 review flag：p4、p8、p9

`validation_summary.review_required=0` 是因为 `_validation_summary()` 只按 `validation_status` 计数；review 是独立 bool（`workbook_validation.py:48-61`）。

final review bucket 为空/缺失，因为它只作为 Validator 输入，没有 validation 后 router。

Rejected 信息保留在 validation_results：

- `rejection_reason=value_mismatch`
- `rejected_claims=["submitted 2.4 != workbook 0 at Solar Operations!B8"]`
- role/source/dependency evidence 都保留。

但 s5 仍在原始 final_extraction；只读 final_extraction 的消费者会误用 rejected value。

## 15. 根因分类

| 分类 | 结论 | 级别 |
|---|---|---|
| schema mismatch | **有**：缺必填 output_candidates；无后端 schema validation | P0 |
| parser/observation | **有，首要**：12,000 字符截断；inspect preview 不含 formula | P0 |
| validation | 31进31出；但 review summary 错、metadata/structures 无 validation | P1 |
| routing | **有**：完全不存在 validation 后 router/重建 | P0 |
| serialization | 本次无字段丢失；但返回原始错桶对象，内部类型过宽 | P1 |
| coverage gate | **有**：只检查读过，不检查完整观察/提取/守恒 | P0 |
| financial series | **有**：schema 与 deterministic grouping 均缺失 | P1 |
| Agent discovery | **有**：漏 9 个 setup 输入、Debt 0、宽表大量漏项 | P0/P1 |

## 16. 最小修复方案

按最小可验证顺序：

1. **修复 observation 完整性**
   - 删除任意字符串 `[:12000]` 截断。
   - 宽表强制 chunk（按 row 或列窗口），每次必须是完整合法 JSON。
   - 返回 `chunk_id/range/cell_count/serialized_bytes/is_complete`。
   - 所有 chunk 完整 observe 后才算 covered。

2. **backend submit boundary 强制 schema**
   - 建立 typed `FinalExtraction` 与 Candidate Pydantic models。
   - canonical buckets 全部 required；ingress 不用默认 [] 掩盖 missing。
   - `extra="forbid"`，验证 role enum。
   - tool 可 strict/closed，但后端验证必须保留。
   - schema error 时拒绝 submit并继续循环，不能 submitted=true。

3. **新增唯一 router**
   - 输入 original candidates + validation results。
   - validated_role 路由，review/rejected 优先。
   - 输出 `validated_final_extraction`；原始另名 `agent_submitted_extraction`。
   - 输出 count/ID conservation。

4. **强化 gate**
   - schema_valid；
   - observation chunks 完整；
   - 每 material sheet/row 有 extraction 或 no-content；
   - 可配置 minimum assumptions/outputs；
   - `dropped_candidate_count == 0`；
   - routed count 守恒。

5. **确定性 series 聚合**
   - 从 workbook/validated facts 聚合 period rows；LLM 不逐 cell 复制整条 series。

6. **确定性 assumption 补漏**
   - 扫描 label-unit-static-value 表；
   - 从 formula precedents 反向补提 hardcoded cells；
   - section break/merged header 不终止扫描。

## 17. 自动化测试清单

### Schema contract

- tool schema 与 FinalExtraction model 字段完全一致。
- 缺 `output_candidates` 必须拒绝 submit。
- unknown bucket/field 必须拒绝。
- missing 与 explicit [] 可区分。
- legacy `value/candidate_type` 显式测试或移除。
- `formula_external` 与 role universe 一致。

### Observation/chunking

- >12,000 字符结果不得产生半截 JSON。
- Project Setup A1:F25 的最后 cell C25 必须可 observe。
- A1:AB11 所有 chunk cell IDs 守恒。
- 最后 chunk 未 ack 时 coverage 不通过。
- trace/debug 记录 sent bytes、chunk range、完整性。

### Discovery coverage

- Project Setup 18/18 静态输入。
- C14:C16、C20:C25 回归。
- Debt Sculpting 每核心 row 产生 series/candidate 或 no-content。
- 每个 read material sheet 有 extraction outcome。
- 全 candidate bucket 空时 submit 失败。

### Validation/routing

- 七输入 bucket 全汇总。
- 31 input -> 31 validation -> 31 routed/rejected/review records。
- s3 从 parameter 移到 derived/review。
- s5 不留在可消费 final bucket，保留 rejection reason。
- 7 个 `review_required=true` 与 summary 一致。
- candidate_id 不可多 bucket。
- 每阶段返回 dropped IDs。

### Series

- B3:AB3 年份识别。
- 同 row B:AB 聚合单 series。
- relative formula pattern 标准化。
- formula_no_cache 保留 null。
- schema 含 range、periods、values、formula statuses、source refs。

### API

- 明确区分 `agent_submitted_extraction` 与 `validated_final_extraction`。
- response model 内部 typed validation。
- serialization 前后 bucket counts/IDs 相等。
- rejected/review 不被过滤。

## 18. 当前测试验证状态

执行：

```bash
python -m pytest \
  experiments/workbook_agent_poc/tests \
  tests/test_workbook_validation.py \
  tests/test_experimental_workbook_upload.py -q
```

结果：

```text
39 passed, 32 failed
```

32 失败主要因本机 `openpyxl==3.0.10`，而 `apps/api/requirements.txt` 固定 `openpyxl==3.1.2`：

```text
AttributeError: 'DefinedNameList' object has no attribute 'items'
workbook_tools.py:289
```

这属于当前 Anaconda 验证环境依赖不匹配，不解释已生成 API response 的 31-candidate 主问题；但现有文档“50 tests pass”无法在当前解释器直接复现，需在容器/锁定依赖下再跑。

## 19. 具体代码位置

| 问题 | 代码位置 |
|---|---|
| model observation 硬截断 | `experiments/workbook_agent_poc/agent_loop.py:189-194` |
| trace 隐藏 submit payload | `agent_loop.py:73-90` |
| 原始 submit 保存为 final_extraction | `agent_loop.py:84,115-121` |
| inspect preview 前8行/8列且只显示 cached value | `workbook_tools.py:144-169` |
| read_range 完整读取事实 | `workbook_tools.py:171-190` |
| candidate_count 五 bucket 求和 | `workbook_tools.py:267-273` |
| canonical submit schema | `extraction_contract.py:47-63` |
| submit tool schema | `extraction_contract.py:90-93` |
| prompt 分桶要求 | `extraction_contract.py:96-122` |
| coverage 只检查 calls | `coverage_gate.py:92-119` |
| Validator 七 buckets | `validator.py:183-197` |
| role reconciliation | `roles.py:87-128` |
| review flag | `validator.py:110-152` |
| summary 漏数 review bool | `apps/api/app/workbook_validation.py:48-61` |
| API 返回原始 final_extraction | `workbook_validation.py:114-145` |
| extraction 为 Any dict | `apps/api/app/schemas.py:22-38` |
| route response model | `apps/api/app/routers/models.py:46-70` |
| serializer 只处理 UUID/datetime | `apps/api/app/main.py:28-37` |

## 20. 原始 Agent submit payload（完整）

以下 JSON 是 API response 的 `final_extraction`，即 `agent_loop.py:84` 保存的完整 `args["result"]`，未补字段或重分桶。

```json
{
  "metadata": [
    {
      "candidate_id": "m1",
      "original_label": "Utility-Scale Solar PV Project Finance Model",
      "submitted_role": "metadata",
      "raw_value": "Utility-Scale Solar PV Project Finance Model",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "A1"
        }
      ],
      "reasoning_summary": "Workbook title; descriptive metadata, not an input.",
      "llm_confidence": 0.99
    },
    {
      "candidate_id": "m2",
      "original_label": "Project and Commercial Inputs",
      "submitted_role": "header",
      "raw_value": "Project and Commercial Inputs",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "A3"
        }
      ],
      "reasoning_summary": "Section header for input table.",
      "llm_confidence": 0.98
    },
    {
      "candidate_id": "m3",
      "original_label": "Input",
      "submitted_role": "header",
      "raw_value": "Input",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "A4"
        }
      ],
      "reasoning_summary": "Column header for input labels.",
      "llm_confidence": 0.98
    },
    {
      "candidate_id": "m4",
      "original_label": "Unit",
      "submitted_role": "header",
      "raw_value": "Unit",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "B4"
        }
      ],
      "reasoning_summary": "Column header for units.",
      "llm_confidence": 0.98
    },
    {
      "candidate_id": "m5",
      "original_label": "Base Case",
      "submitted_role": "scenario_selector",
      "raw_value": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C4"
        }
      ],
      "reasoning_summary": "Scenario heading for the assumption column.",
      "llm_confidence": 0.9
    },
    {
      "candidate_id": "m6",
      "original_label": "Construction and Capex Schedule",
      "submitted_role": "metadata",
      "raw_value": "Construction and Capex Schedule",
      "source_references": [
        {
          "sheet_name": "Build Schedule",
          "cell": "A1"
        }
      ],
      "reasoning_summary": "Section title, not an assumption.",
      "llm_confidence": 0.99
    },
    {
      "candidate_id": "m7",
      "original_label": "Metric",
      "submitted_role": "header",
      "raw_value": "Metric",
      "source_references": [
        {
          "sheet_name": "Build Schedule",
          "cell": "A3"
        }
      ],
      "reasoning_summary": "Row/column header for schedule table.",
      "llm_confidence": 0.98
    },
    {
      "candidate_id": "m8",
      "original_label": "Generation and Revenue Forecast",
      "submitted_role": "metadata",
      "raw_value": "Generation and Revenue Forecast",
      "source_references": [
        {
          "sheet_name": "Solar Operations",
          "cell": "A1"
        }
      ],
      "reasoning_summary": "Section title.",
      "llm_confidence": 0.99
    },
    {
      "candidate_id": "m9",
      "original_label": "Debt Schedule",
      "submitted_role": "metadata",
      "raw_value": "Debt Schedule",
      "source_references": [
        {
          "sheet_name": "Debt Sculpting",
          "cell": "A1"
        }
      ],
      "reasoning_summary": "Section title.",
      "llm_confidence": 0.99
    },
    {
      "candidate_id": "m10",
      "original_label": "Project Cash Flow",
      "submitted_role": "metadata",
      "raw_value": "Project Cash Flow",
      "source_references": [
        {
          "sheet_name": "Cash Flow",
          "cell": "A1"
        }
      ],
      "reasoning_summary": "Section title.",
      "llm_confidence": 0.99
    },
    {
      "candidate_id": "m11",
      "original_label": "Investor Returns Summary",
      "submitted_role": "metadata",
      "raw_value": "Investor Returns Summary",
      "source_references": [
        {
          "sheet_name": "Investor Returns",
          "cell": "A1"
        }
      ],
      "reasoning_summary": "Section title.",
      "llm_confidence": 0.99
    }
  ],
  "all_assumption_candidates": [],
  "parameter_candidates": [
    {
      "candidate_id": "p1",
      "original_label": "Project capacity",
      "submitted_role": "hardcoded_input",
      "raw_value": 180,
      "displayed_value": "180",
      "unit": "MW",
      "period": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C5"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Editable project size input in setup table.",
      "llm_confidence": 0.99,
      "category": "capacity",
      "canonical_name": "Project Capacity",
      "evidence": [
        "Label/value adjacency in setup table"
      ]
    },
    {
      "candidate_id": "p2",
      "original_label": "Construction start",
      "submitted_role": "hardcoded_input",
      "raw_value": 2027,
      "displayed_value": "2027",
      "unit": "Year",
      "period": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C6"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Editable start year input.",
      "llm_confidence": 0.99,
      "category": "timing",
      "canonical_name": "Construction Start Year",
      "evidence": [
        "Label/value adjacency in setup table"
      ]
    },
    {
      "candidate_id": "p3",
      "original_label": "Construction period",
      "submitted_role": "hardcoded_input",
      "raw_value": 2,
      "displayed_value": "2",
      "unit": "Years",
      "period": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C7"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Editable duration input.",
      "llm_confidence": 0.99,
      "category": "timing",
      "canonical_name": "Construction Period",
      "evidence": [
        "Label/value adjacency in setup table"
      ]
    },
    {
      "candidate_id": "p4",
      "original_label": "Operating life",
      "submitted_role": "hardcoded_input",
      "raw_value": 25,
      "displayed_value": "25",
      "unit": "Years",
      "period": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C8"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Editable operating horizon input.",
      "llm_confidence": 0.99,
      "category": "timing",
      "canonical_name": "Operating Life",
      "evidence": [
        "Label/value adjacency in setup table"
      ]
    },
    {
      "candidate_id": "p5",
      "original_label": "Base power price",
      "submitted_role": "hardcoded_input",
      "raw_value": 62,
      "displayed_value": "62",
      "unit": "$/MWh",
      "period": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C9"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Editable base price assumption.",
      "llm_confidence": 0.99,
      "category": "price",
      "canonical_name": "Base Power Price",
      "evidence": [
        "Label/value adjacency in setup table"
      ]
    },
    {
      "candidate_id": "p6",
      "original_label": "Power price escalation",
      "submitted_role": "hardcoded_input",
      "raw_value": 0.018,
      "displayed_value": "1.8%",
      "unit": "%",
      "period": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C10"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Editable escalation assumption.",
      "llm_confidence": 0.99,
      "category": "price",
      "canonical_name": "Power Price Escalation",
      "evidence": [
        "Label/value adjacency in setup table"
      ]
    },
    {
      "candidate_id": "p7",
      "original_label": "Net capacity factor",
      "submitted_role": "hardcoded_input",
      "raw_value": 0.275,
      "displayed_value": "27.5%",
      "unit": "%",
      "period": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C11"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Editable operating performance input.",
      "llm_confidence": 0.99,
      "category": "operations",
      "canonical_name": "Net Capacity Factor",
      "evidence": [
        "Label/value adjacency in setup table"
      ]
    },
    {
      "candidate_id": "p8",
      "original_label": "Annual degradation",
      "submitted_role": "hardcoded_input",
      "raw_value": 0.004,
      "displayed_value": "0.4%",
      "unit": "%",
      "period": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C12"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Editable degradation assumption.",
      "llm_confidence": 0.99,
      "category": "operations",
      "canonical_name": "Annual Degradation",
      "evidence": [
        "Label/value adjacency in setup table"
      ]
    },
    {
      "candidate_id": "p9",
      "original_label": "Total EPC cost",
      "submitted_role": "hardcoded_input",
      "raw_value": 198,
      "displayed_value": "198",
      "unit": "$mm",
      "period": "Base Case",
      "source_references": [
        {
          "sheet_name": "Project Setup",
          "cell": "C13"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Editable capex input in setup table.",
      "llm_confidence": 0.99,
      "category": "capex",
      "canonical_name": "Total EPC Cost",
      "evidence": [
        "Label/value adjacency in setup table"
      ]
    },
    {
      "candidate_id": "d1",
      "original_label": "Construction %",
      "submitted_role": "scenario_input",
      "raw_value": 0.45,
      "displayed_value": "45.0%",
      "unit": "%",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Build Schedule",
          "cell": "B4"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Construction allocation across years; hardcoded timeline input.",
      "llm_confidence": 0.95,
      "category": "capex schedule",
      "canonical_name": "Construction Percentage",
      "evidence": [
        "Hardcoded numeric on schedule row"
      ]
    },
    {
      "candidate_id": "d2",
      "original_label": "Construction %",
      "submitted_role": "scenario_input",
      "raw_value": 0.55,
      "displayed_value": "55.0%",
      "unit": "%",
      "period": 2028,
      "source_references": [
        {
          "sheet_name": "Build Schedule",
          "cell": "C4"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Construction allocation across years; hardcoded timeline input.",
      "llm_confidence": 0.95,
      "category": "capex schedule",
      "canonical_name": "Construction Percentage",
      "evidence": [
        "Hardcoded numeric on schedule row"
      ]
    },
    {
      "candidate_id": "d3",
      "original_label": "Base EPC spend",
      "submitted_role": "formula_derived_value",
      "raw_value": 0.03375,
      "unit": null,
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Build Schedule",
          "cell": "B5"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Formula-driven capex spend by year.",
      "llm_confidence": 0.95,
      "category": "capex schedule",
      "canonical_name": "Base EPC Spend",
      "evidence": [
        "Formula present in row"
      ]
    },
    {
      "candidate_id": "d4",
      "original_label": "Contingency",
      "submitted_role": "formula_derived_value",
      "raw_value": 0.10800000000000001,
      "unit": null,
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Build Schedule",
          "cell": "B6"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Formula-driven contingency by year.",
      "llm_confidence": 0.95,
      "category": "capex schedule",
      "canonical_name": "Contingency",
      "evidence": [
        "Formula present in row"
      ]
    },
    {
      "candidate_id": "d5",
      "original_label": "Total capex",
      "submitted_role": "formula_derived_value",
      "raw_value": 0.14175000000000001,
      "unit": null,
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Build Schedule",
          "cell": "B7"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Formula-driven total capex by year.",
      "llm_confidence": 0.95,
      "category": "capex schedule",
      "canonical_name": "Total Capex",
      "evidence": [
        "Formula present in row"
      ]
    },
    {
      "candidate_id": "d6",
      "original_label": "Cumulative capex",
      "submitted_role": "formula_derived_value",
      "raw_value": 0.14175000000000001,
      "unit": null,
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Build Schedule",
          "cell": "B8"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Formula-driven cumulative capex by year.",
      "llm_confidence": 0.95,
      "category": "capex schedule",
      "canonical_name": "Cumulative Capex",
      "evidence": [
        "Formula present in row"
      ]
    },
    {
      "candidate_id": "s1",
      "original_label": "Operating flag",
      "submitted_role": "formula_derived_value",
      "raw_value": 0,
      "unit": null,
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Solar Operations",
          "cell": "B4"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Formula computes whether plant is operational in year.",
      "llm_confidence": 0.97,
      "category": "operations",
      "canonical_name": "Operating Flag",
      "evidence": [
        "Formula references setup years"
      ]
    },
    {
      "candidate_id": "s2",
      "original_label": "Net generation (GWh)",
      "submitted_role": "formula_derived_value",
      "raw_value": 0,
      "unit": "GWh",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Solar Operations",
          "cell": "B5"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Formula-derived annual generation.",
      "llm_confidence": 0.97,
      "category": "operations",
      "canonical_name": "Net Generation",
      "evidence": [
        "Formula row in operating forecast"
      ]
    },
    {
      "candidate_id": "s3",
      "original_label": "Power price ($/MWh)",
      "submitted_role": "hardcoded_input",
      "raw_value": 62,
      "displayed_value": "62",
      "unit": "$/MWh",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Solar Operations",
          "cell": "B6"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Initial year price shown as a hardcoded forecast input/anchor.",
      "llm_confidence": 0.84,
      "category": "price",
      "canonical_name": "Power Price",
      "evidence": [
        "Hardcoded numeric in forecast row"
      ]
    },
    {
      "candidate_id": "s4",
      "original_label": "Revenue ($mm)",
      "submitted_role": "formula_derived_value",
      "raw_value": 0,
      "unit": "$mm",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Solar Operations",
          "cell": "B7"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Revenue is formula-derived from generation and price.",
      "llm_confidence": 0.97,
      "category": "revenue",
      "canonical_name": "Revenue",
      "evidence": [
        "Formula row in operations forecast"
      ]
    },
    {
      "candidate_id": "s5",
      "original_label": "Fixed O&M ($mm)",
      "submitted_role": "hardcoded_input",
      "raw_value": 2.4,
      "displayed_value": "2.4",
      "unit": "$mm",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Solar Operations",
          "cell": "B8"
        }
      ],
      "formula_status": "static_value",
      "reasoning_summary": "Recurring operating cost input shown as hardcoded value.",
      "llm_confidence": 0.97,
      "category": "opex",
      "canonical_name": "Fixed O&M",
      "evidence": [
        "Hardcoded numeric in forecast row"
      ]
    },
    {
      "candidate_id": "c1",
      "original_label": "Revenue",
      "submitted_role": "formula_derived_value",
      "raw_value": 0,
      "unit": "$mm",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Cash Flow",
          "cell": "B4"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Linked from operations revenue forecast.",
      "llm_confidence": 0.96,
      "category": "cash flow",
      "canonical_name": "Revenue",
      "evidence": [
        "Cross-sheet formula link"
      ]
    },
    {
      "candidate_id": "c2",
      "original_label": "EBITDA",
      "submitted_role": "formula_derived_value",
      "raw_value": 0,
      "unit": "$mm",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Cash Flow",
          "cell": "B5"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Calculated operating cash flow.",
      "llm_confidence": 0.96,
      "category": "cash flow",
      "canonical_name": "EBITDA",
      "evidence": [
        "Formula row in cash flow statement"
      ]
    },
    {
      "candidate_id": "c3",
      "original_label": "Capex",
      "submitted_role": "formula_derived_value",
      "raw_value": -0.14175000000000001,
      "unit": "$mm",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Cash Flow",
          "cell": "B6"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Cash outflow linked to build schedule.",
      "llm_confidence": 0.96,
      "category": "cash flow",
      "canonical_name": "Capex",
      "evidence": [
        "Cross-sheet formula link"
      ]
    },
    {
      "candidate_id": "c4",
      "original_label": "Tax",
      "submitted_role": "formula_derived_value",
      "raw_value": 0,
      "unit": "$mm",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Cash Flow",
          "cell": "B7"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Formula-derived tax line.",
      "llm_confidence": 0.95,
      "category": "cash flow",
      "canonical_name": "Tax",
      "evidence": [
        "Formula row in cash flow statement"
      ]
    },
    {
      "candidate_id": "c5",
      "original_label": "CFADS",
      "submitted_role": "formula_derived_value",
      "raw_value": 0,
      "unit": "$mm",
      "period": 2027,
      "source_references": [
        {
          "sheet_name": "Cash Flow",
          "cell": "B8"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Cash flow available for debt service is formula-derived.",
      "llm_confidence": 0.95,
      "category": "cash flow",
      "canonical_name": "CFADS",
      "evidence": [
        "Formula row in cash flow statement"
      ]
    },
    {
      "candidate_id": "r1",
      "original_label": "Total project cost",
      "submitted_role": "formula_output",
      "raw_value": 0.31500000000000006,
      "unit": "$mm",
      "source_references": [
        {
          "sheet_name": "Investor Returns",
          "cell": "B5"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Summary output of maximum cumulative capex.",
      "llm_confidence": 0.98,
      "category": "summary",
      "canonical_name": "Total Project Cost",
      "evidence": [
        "Summary cell referencing build schedule"
      ]
    },
    {
      "candidate_id": "r2",
      "original_label": "Peak debt",
      "submitted_role": "formula_output",
      "raw_value": 0.22050000000000003,
      "unit": "$mm",
      "source_references": [
        {
          "sheet_name": "Investor Returns",
          "cell": "B6"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Summary output of maximum debt balance.",
      "llm_confidence": 0.98,
      "category": "summary",
      "canonical_name": "Peak Debt",
      "evidence": [
        "Summary cell referencing debt schedule"
      ]
    },
    {
      "candidate_id": "r3",
      "original_label": "Minimum DSCR",
      "submitted_role": "formula_output",
      "raw_value": 0,
      "unit": "x",
      "source_references": [
        {
          "sheet_name": "Investor Returns",
          "cell": "B7"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Summary output of minimum debt service coverage ratio.",
      "llm_confidence": 0.95,
      "category": "summary",
      "canonical_name": "Minimum DSCR",
      "evidence": [
        "Summary cell referencing cash flow"
      ]
    },
    {
      "candidate_id": "r4",
      "original_label": "Project IRR",
      "submitted_role": "formula_output",
      "raw_value": null,
      "unit": "%",
      "source_references": [
        {
          "sheet_name": "Investor Returns",
          "cell": "B8"
        }
      ],
      "formula_status": "formula_no_cache",
      "reasoning_summary": "IRR formula present but cached value unavailable.",
      "llm_confidence": 0.9,
      "category": "summary",
      "canonical_name": "Project IRR",
      "evidence": [
        "Formula with no cached value"
      ]
    },
    {
      "candidate_id": "r5",
      "original_label": "Equity IRR",
      "submitted_role": "formula_output",
      "raw_value": null,
      "unit": "%",
      "source_references": [
        {
          "sheet_name": "Investor Returns",
          "cell": "B9"
        }
      ],
      "formula_status": "formula_no_cache",
      "reasoning_summary": "IRR formula present but cached value unavailable.",
      "llm_confidence": 0.9,
      "category": "summary",
      "canonical_name": "Equity IRR",
      "evidence": [
        "Formula with no cached value"
      ]
    },
    {
      "candidate_id": "r6",
      "original_label": "Average EBITDA margin",
      "submitted_role": "formula_output",
      "raw_value": -281.5039555072965,
      "unit": "%",
      "source_references": [
        {
          "sheet_name": "Investor Returns",
          "cell": "B10"
        }
      ],
      "formula_status": "formula_with_cached_value",
      "reasoning_summary": "Summary output computed from operations margins.",
      "llm_confidence": 0.9,
      "category": "summary",
      "canonical_name": "Average EBITDA Margin",
      "evidence": [
        "Formula output in summary sheet"
      ]
    }
  ],
  "scenario_structures": [],
  "sensitivity_structures": [],
  "coverage_declaration": {
    "sheets_inspected": [
      "Project Setup",
      "Build Schedule",
      "Solar Operations",
      "Debt Sculpting",
      "Cash Flow",
      "Investor Returns"
    ],
    "all_sheets_read_regions": [
      "Project Setup!A1:F25",
      "Build Schedule!A1:AB8",
      "Solar Operations!A1:AB11",
      "Debt Sculpting!A1:AB10",
      "Cash Flow!A1:AB11",
      "Investor Returns!A1:F10"
    ],
    "hidden_sheets_checked": true,
    "named_ranges_checked": true,
    "data_validations_checked": [
      "Project Setup",
      "Build Schedule",
      "Solar Operations",
      "Debt Sculpting",
      "Cash Flow",
      "Investor Returns"
    ]
  }
}
```
