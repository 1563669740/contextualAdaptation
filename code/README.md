# code/ — 论文复现代码归档

**论文**：《何时应将软件缺陷修复交给 AI？面向仓库级软件修复的情境–策略匹配与自适应委托》
**依据方案**：`无Docker_论文复现实验数据采集实施方案.docx`（v1.0, 2026-09-14）
**数据资产**：`../experiment_root/`（216 任务 / 38 仓库 / 792 个冻结分配的 session）
**本目录定位**：把散落在工作区里的复现代码，按论文位置归拢成一份可索引、可校验的归档

---

## 0. 一句话说明这份归档的性质

```
experiment_root/   ← 权威副本（权威数据 + 权威代码）。本目录从不改动它。
code/              ← 归档镜像 + 统一入口。只复制，不移动，不删除。
```

**为什么不直接把 `experiment_root/tools/` 挪进来**：`experiment_root/audit/freeze_manifest.json`
用 tree digest 冻结了 676 个产物，`splits/randomisation.json` 记录了分配生成器的
SHA256。把工具源码移走会直接改变冻结包的内容哈希——那是一份已经交付、可核验的
权威副本。所以这里做的是**镜像**：`code/` 里 55 个文件中的 54 个与源文件**逐字节一致**，
第 55 个只有一处行级适配（见 §4）。

| 命令 | 作用 |
|---|---|
| `python code/sync.py` | 把 `code/` 重新对齐到 `experiment_root/`（幂等，可反复跑） |
| `python code/verify.py` | 校验副本与源逐字节一致 + 全量语法检查 |
| `python code/run.py --list` | 列出所有可运行脚本 |
| `python code/run.py <脚本> [参数]` | 用统一入口运行任意脚本（解决跨模块 import） |

---

## 1. 论文位置 ↔ 代码

论文的四个研究问题对应四段代码，加上基础设施与质控共 11 组。

| 分组 | 论文位置 | 代码 | 干什么 |
|---|---|---|---|
| `01_infra_noncontainer/` | §IV-A、§V-E(步骤2) | 3 | 非容器化环境底座、38 仓库抓取与 base commit 快照 |
| `02_freeze_protocol/` | §III-B/C/D、§IV-B、§V-A/C（M0） | 9 | 任务清单、划分与平衡分配、协议/事件 schema/codebook/策略冻结、Chigh context package、理解检查 |
| `03_leakage/` | §IV-B 第6条、§V-A | 2 | 答案泄漏机器筛查与双评审仲裁 |
| `04_session/` | §V-B、§V-C、§V-E | 3 | Session 时钟与事件流、三 regime 权限守卫、75 分钟硬停止、Pilot 门槛 |
| `05_evaluation/` | §V-F、§V-G | 6 | 隐藏评价 harness、指标汇总（时间口径）、预注册准入闸门 |
| `06_holdout/` | §V-G | 14 | holdout 测试编写与三条件准入、差分探针、可行性标定 |
| `07_rq2_coding/` | §VII、§V-G | 2 | RQ2 编码手册/盲法包/κ 估计器、一致率–κ 边界核算 |
| `08_rq3_policy/` | §VIII-A/B | 5 | 在线信号提取器、Adaptive Policy 状态机、阈值 CV 演练 |
| `09_rq1_rq4_analysis/` | §VI、§IX（表 V、表 XV） | 2 | 合成 session 生成 + 管线回收检验 |
| `10_audit/` | §III-D、§XII | 1 | A–I 组审计、QA 报告、全量冻结清单 |
| `99_scratch/` | 非论文产物 | 8 | 一次性诊断、路径修补、PDF 提取 |

> 每个文件的逐条用途、论文锚点、源路径与 SHA256 见 **`CODE_INDEX.md`**（由
> `sync.py` 生成；机器可读版本是同目录的 `CODE_INDEX.json`）。

### 1.1 论文四个研究问题分别由哪些代码回答

| RQ | 论文结论线索 | 代码入口 |
|---|---|---|
| **RQ1** 情境–策略匹配 | `Wald χ²(2) = 7.80, p = .020`；Clow 下共享控制 +31.7pp；Chigh 下 AI 主导 78.3% 且省 14.3 分钟 | `02_freeze_protocol/build_allocation.py`（2×3 平衡，6 cell 各 60）→ `05_evaluation/` → `09_rq1_rq4_analysis/` |
| **RQ2** 过程证据 | 搜索空间扩散、假设翻转、修改边界漂移为负向；验证证据收敛为正向 | `07_rq2_coding/rq2_coding.py`（P1–P6 编码 + κ） |
| **RQ3** 委托决策 | 任务前信息做初始路由 + 早期过程信号做控制权转换，组合最佳 | `08_rq3_policy/online_policy.py`（在线提取器，只用当时可见事件） |
| **RQ4** 前瞻性效用 | Adaptive 79.2% Enhanced Resolved / 17.9 分钟人工时间 | `09_rq1_rq4_analysis/simulate.py` + `05_evaluation/`（5 policy × 72 任务） |

---

## 2. 目录结构

```
code/
├── README.md                      # 本文件：论文 ↔ 代码 ↔ 命令
├── code_map.json                  # 映射表（手工维护，sync/verify 的唯一输入）
├── sync.py                        # 幂等同步：experiment_root → code/
├── verify.py                       # 哈希比对 + 语法检查
├── run.py                          # 统一启动器（修好跨模块 import）
├── requirements.txt               # 只依赖标准库 + PyYAML
├── CODE_INDEX.json / .md          # 生成物：逐文件索引 + SHA256
├── 01_infra_noncontainer/
├── 02_freeze_protocol/
├── 03_leakage/
├── 04_session/
├── 05_evaluation/
├── 06_holdout/
│   └── probes/
├── 07_rq2_coding/
├── 08_rq3_policy/
│   └── diagnostics/
├── 09_rq1_rq4_analysis/
├── 10_audit/
└── 99_scratch/
```

---

## 3. 怎么跑

所有脚本内部都硬编码了 `ROOT = <仓库根>\experiment_root`，
所以**副本照旧读写权威数据**，`code/` 只是入口而不是沙箱。运行会写进
`experiment_root/` 的产物——这一点和直接在 `experiment_root/` 下跑完全一致。

```bash
# 0) 依赖
python -m pip install -r code/requirements.txt        # 只有 PyYAML

# 1) 校验归档（应输出 consistent 55 / 0 problems）
python code/verify.py

# 2) 全量审计（只扫 experiment_root，不认识 code/）
python code/run.py 10_audit/audit.py

# 3) 指标汇总
python code/run.py 05_evaluation/aggregate_metrics.py

# 4) 隐藏评价（独立干净工作区）
python code/run.py 05_evaluation/evaluate.py --session-id D-S0001

# 5) 管线自检：从合成样本回收论文表 V / 表 XV 的结构
python code/run.py 09_rq1_rq4_analysis/check_pipeline.py

# 6) 在线策略自测（输出 experiment_root/policy/extractor_self_test.json）
python code/run.py 08_rq3_policy/online_policy.py --self-test
```

### 3.1 为什么需要 `run.py`

`experiment_root/tools/simulate.py` 要 `import online_policy, rq2_coding`；
`admission_gate.py` / `holdout_probe.py` / `holdout_author.py` 要
`import task_env, evaluate`。这些脚本靠 `sys.path.insert` 找兄弟模块，而
`code/` 的分组和 `experiment_root/{tools,evaluation}` 不同。
`run.py` 把 `code/` 的每个分组目录与 `experiment_root/{tools,evaluation,repo_cache}`
一起放进 `sys.path`，于是副本**不改一行逻辑**就能跑。已验证：

```
python code/run.py 05_evaluation/admission_gate.py --help   → exit 0
python code/run.py 06_holdout/holdout_author.py status      → exit 0
python code/run.py 09_rq1_rq4_analysis/simulate.py --help    → exit 0
```

直接 `python code/05_evaluation/admission_gate.py` 也可以（它用的是绝对
`ROOT`），只有 `holdout_author.py` 必须走 `run.py`——它是唯一用 `__file__`
推导 `sys.path` 的脚本。

---

## 4. 唯一一处适配（`path_pin`）

`experiment_root/repo_cache/fetch_repos.py` 是全部代码里唯一用 `__file__`
定位自身缓存目录的：

```python
CACHE = os.path.dirname(os.path.abspath(__file__))
```

复制到 `code/01_infra_noncontainer/` 后 `__file__` 会指向那里，脚本会去
`code/` 下建 `_inventory/`、`_snapshots/`，与已冻结的 `repo_cache/` 分叉。
所以副本只改这一行，把 `CACHE` 钉死到权威目录：

```python
CACHE = r"<仓库根>\experiment_root\repo_cache"  # code-tree adapter: pin to the authoritative cache
# 注：改动此字符串会让 code/verify.py 报 SOURCE_CHANGED（适配规则见 §4），
#     换路径后需重跑 code/sync.py 刷新哈希。
```

逻辑一行未改。适配规则写在 `code_map.json` 的 `adapters` 段，实际改动逐字记录在
`CODE_INDEX.json` 该条目的 `adaptation` 字段里；`verify.py` 会重新套用同一规则
比对，因此这处偏差不会被"忘记"。另一个抓取脚本
`fetch_repos_tarball.py` 本来就用绝对路径，无需适配。

---

## 5. 这个工作区正在被并发编辑

整理当时（2026-09-15 08:44 +08:00），`experiment_root/tools/` 下仍有文件在被
写入（`online_policy.py` 08:40、`simulate.py` 08:39、`aggregate_metrics.py` 08:36，
以及新出现的 `_diag_p1.py`、`_diag_p1b.py`、`_diag_freq.py`）。因此归档是
**当时状态的快照**：

* 跑 `python code/verify.py` —— 若报 `SOURCE_CHANGED`，说明源侧有新编辑；
* 跑 `python code/sync.py` —— 重新对齐并刷新哈希；
* 若源目录里出现了没登记的新脚本，`sync.py` 会把它列在
  `unmapped` 里（默认不复制）。要收拢就加 `--adopt-unmapped`，它会进
  `99_scratch/_unmapped/`，但仍需人工归位并在 `code_map.json` 里登记。

---

## 6. 本目录不做什么

* **不改** `experiment_root/` 里的任何文件——没有移动、没有删除、没有重命名。
* **不参与** `experiment_root` 的冻结哈希，也**不被** `tools/audit.py` 扫描
  （审计只走 `manifests/ splits/ context_packages/ protocol/ codebook/ policy/ audit/`
  七个目录），所以新增 `code/` 不会让既有审计结果从 PASS 变 WARN。
* **不是** `dataset/holdout_tests/*/tests_holdout_task.py` 这类**数据**的归档——
  那是评价材料，不是代码。
* `09_rq1_rq4_analysis/simulate.py` 产出的是 **SYNTHETIC / NOT_A_RESULT** 数据，
  用于验证管线而不是产生结论；引用时必须带上这个标记。
