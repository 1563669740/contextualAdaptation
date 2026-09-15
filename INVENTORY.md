# 内容清单（project 仓库 = 业务代码 + 数据集）

生成时间：2026-09-15　实测命令：`git ls-files -o --exclude-standard`

---

## 1. 结论

| | 文件数 | 体积 |
|---|---:|---:|
| **仓库内容**（`code/` + `dataset/`） | **3,564** | **96.6 MB** |
| 本机保留、不进库 | ~114,000 | ~5.0 GB |

仓库只含两部分：**业务代码** `code/`（62 文件）与**数据集** `dataset/`（3,499 文件），另加仓库根的三份说明文件（`README.md`、`INVENTORY.md`、`.gitignore`）。没有实验产物、受试者数据、构造样本或运行工作区。

最大单文件 19.3 MB（`dataset/splits/discovery.csv`），全部低于 GitHub 100 MB 单文件上限；体积主要来自划分清单与 F2P/P2P 测试节点名录。

---

## 2. 仓库内容

### 2.1 `code/` — 业务代码（62 文件 / 0.55 MB）

| 目录 | 文件 | 对应论文位置 | 职责 |
|---|---:|---|---|
| `01_infra_noncontainer/` | 3 | §IV-A、§V-E(2) | 非容器化环境底座、38 仓库抓取与 base commit 快照 |
| `02_freeze_protocol/` | 9 | §III-B/C/D、§IV-B、§V-A/C | 任务清单、划分与平衡分配、协议/事件 schema/codebook/策略冻结、Chigh context package、理解检查 |
| `03_leakage/` | 2 | §IV-B(6)、§V-A | 答案泄漏机器筛查与双评审仲裁 |
| `04_session/` | 3 | §V-B/C/E | session 时钟与事件流、三 regime 权限守卫、75 分钟硬停、Pilot 门槛 |
| `05_evaluation/` | 6 | §V-F/G | 隐藏评价 harness、指标汇总（时间口径）、预注册准入闸门 |
| `06_holdout/` | 14 | §V-G | holdout 编写与三条件准入、差分探针、可行性标定 |
| `07_rq2_coding/` | 2 | §VII、§V-G | RQ2 编码手册/盲法包/κ 估计器、一致率–κ 边界核算 |
| `08_rq3_policy/` | 5 | §VIII-A/B | 在线信号提取器、Adaptive Policy 状态机、阈值 CV 演练 |
| `09_rq1_rq4_analysis/` | 2 | §VI、§IX | 合成 session 生成 + 管线回收检验 |
| `10_audit/` | 1 | §III-D、§XII | A–I 组审计、QA 报告、冻结清单 |
| `99_scratch/` | 8 | — | 一次性诊断、路径修补、PDF 提取（非论文产物） |
| 根级 8 文件 | 8 | — | `README.md`、`code_map.json`、`sync.py`、`verify.py`、`run.py`、`requirements.txt`、`CODE_INDEX.md`、`CODE_INDEX.json` |

逐文件的用途、论文锚点、源路径与 SHA256 见 `code/CODE_INDEX.md`。

### 2.2 `dataset/` — 数据集（3,502 文件 / 93.5 MB）

| 子目录 | 文件 | 体积 | 性质 | 来源 |
|---|---:|---:|---|---|
| `tasks/` | 648 | 2.15 MB | 216 个任务：`issue.json` / `metadata.json` / `base_commit.txt` | 上游 SWE-bench-Live 派生 |
| `benchmark_tests/` | 1,080 | 41.85 MB | F2P / P2P 清单、oracle、test patch、`test_command.sh` | 上游 |
| `gold/` | 1,320 | 10.83 MB | 216 个 gold patch + `commits.csv`（commit URL、改动行数、模块数） | 上游 PR/commit |
| `environments/` | 433 | 0.28 MB | 上游 `Dockerfile`、`environment_metadata.json`、`reproduction.csv` | 上游 |
| `splits/` | 3 | 40.55 MB | Pilot / Discovery / Held-out 任务清单（含测试节点名录） | 本研究 |
| `holdout_tests/` | 14 | 0.10 MB | 已通过三条件准入的 holdout 套件 + `_calibration/` | 本研究 |
| `screening/` | 1 | 0.26 MB | 自动筛查：难度、可构建性、外部依赖、泄漏风险 | 本研究 |

不含任何受试者标识、问卷、轨迹或时间数据——那些属于实验产物，不在仓库内。

---

## 3. 本机保留、不进库

### 3.1 由 `.gitignore` 排除（随仓库分发，clone 后同样生效）

| 路径 | 文件数 | 体积 | 理由 | 补回方式 |
|---|---:|---:|---|---|
| `dataset/raw/` | 29 | 1,361 MB | 上游 SWE-bench-Live 月度 parquet/jsonl + 论文 PDF | 上游重新下载到 `dataset/raw/` |
| `dataset/tasks.csv` | 1 | 342 MB | 同一数据集全量导出（70,280 行 × 63 列），**超 GitHub 100 MB 限制**；逐任务素材已在 `dataset/tasks/` | 同上 |
| `dataset/repositories/` | 3,140 | 177 MB | 5 个第三方仓库快照（含 `.git`），许可归上游 | `python code/run.py 01_infra_noncontainer/fetch_repos.py` |

### 3.2 由 `.git/info/exclude` 排除（本机资产，规则不随仓库分发）

| 路径 | 文件数 | 体积 | 理由 | 补回方式 |
|---|---:|---:|---|---|
| `experiment_root/` | 34,386 | 3,244 MB | 实验产物与冻结资产：`manifests`(216)、`context_packages`(216)、`evaluation_spec`(216)、`protocol`、`splits`、`tools`，以及 `sessions`、`evaluation`、`codebook`、`interview`、`screening`、`policy`、`audit`、`analysis` | 重跑 `02_freeze_protocol/` 等构建脚本 |
| `work/` | 38,175 | 96.6 MB | 构造分析样本树（SYNTHETIC / NOT_A_RESULT，792 session） | `work/experiment_root/tools/sim_*.py` |
| `run/` | 38,184 | 96.8 MB | 同上（含 `run/release/` 去标识发布包） | 同上 |
| `_docx_extract/` | 20 | 1.0 MB | 实施方案 `.docx` 的 XML/文本提取 | 重新解包 `.docx` |
| 根目录 `_*.py`/`_*.json`/`_*.txt` | 30 | 0.05 MB | 一次性探针脚本 | 无（已在 `code/99_scratch/` 留副本） |

`experiment_root/` 里**没有任何真实受试者数据**：`sessions/` 是空目录，792 个正式 session 在 `STATUS.md` §5 中列为「尚未采集」。

---

## 4. 上传前需要知道的三件事

1. **代码里的绝对路径未改**：`code/` 62 个文件中 55 个含 `C:\Users\Administrator\Desktop\project\...`，共 101 处引用（`experiment_root/` 67 处、`dataset/` 21 处、仓库根 13 处）。只读数据集与算法的脚本可直接跑；完整采集/评价链需要本机保留的 `experiment_root/`。详见 README「路径要求」。
2. **答案材料随库分发**：`dataset/gold/`（10.8 MB 修复 patch）与 `dataset/benchmark_tests/`（41.9 MB F2P/P2P）等于答案。若仓库要公开、且后续仍用同一批任务做实采，建议把这两项也加到 `.gitignore`。
3. **密钥扫描已过**：`dataset/` 全量扫描唯一命中是 `patroni__patroni-3045` 的 issue 原文，内容为上游已脱敏的 `password: 'REDACTED'`，非真实凭据。

---

## 5. 已执行的上传

```powershell
cd C:\Users\Administrator\Desktop\project

git add .
git commit -m "project: repository-level repair delegation study -- code and dataset"
git remote add origin https://github.com/1563669740/contextualAdaptation.git
git push -u origin main
```

远端：`https://github.com/1563669740/contextualAdaptation`，分支 `main`，3,565 个文件。
提交前已把仓库级 `core.autocrlf` 设为 `false` 并加入 `.gitattributes`（`* text=auto eol=lf`），
避免 `dataset/gold/patches/*.patch` 与 `dataset/holdout_tests/*/*.diff` 的行尾被改写成 CRLF。
