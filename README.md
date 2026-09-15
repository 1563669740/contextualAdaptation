# TIFS — 仓库级软件缺陷修复的委托研究

本仓库是论文

> **《何时应将软件缺陷修复交给 AI？——面向仓库级软件修复的情境–策略匹配与自适应委托》**

的**代码与数据集**：只保留两部分——**业务代码**（`code/`）与**数据集**（`dataset/`）。实验产物、冻结资产、构造样本与运行工作区都不在仓库内，见 §2。

研究对象是 SWE-bench-Live 类的仓库级纠错性缺陷修复任务：**3 个阶段**（Pilot 6 仓库/24 任务、Discovery 20/120、Held-out 12/72，合计 38 仓库 / 216 任务），**2×3 情境–委托设计**（Clow / Chigh × AI-led / Shared-control / Human-led），**792 个冻结分配的 session**（Discovery 360 + Held-out 360 + Pilot 72）。

> **复现边界**：原论文使用可复现 Docker 环境，本工作区采用「固定 Linux 镜像 + 每任务快照/克隆 + 语言级虚拟环境」的**非容器化**实现（non-containerized replication / infrastructure adaptation），执行环境与原文不完全相同，需作为潜在效度威胁单独报告。任务信息暴露规则、控制权定义、评价口径与数据冻结逻辑均按原文保留。

---

## 1. 仓库结构

```
TIFS/
├── README.md                本文件
├── INVENTORY.md             内容清单：进库/本机保留、体积、理由
├── .gitignore               进库规则的「可分发」部分（缓存、编辑器、密钥兜底）
├── code/                    业务代码（62 文件 / 0.55 MB）
│   ├── README.md            论文位置 ↔ 代码 ↔ 运行命令
│   ├── CODE_INDEX.md/.json  逐文件索引 + SHA256（由 sync.py 生成）
│   ├── code_map.json        映射表（sync/verify 的唯一输入）
│   ├── sync.py / verify.py  与上游实验目录对齐、逐字节校验 + 语法检查
│   ├── run.py               统一启动器（解决跨模块 import）
│   └── requirements.txt     只依赖标准库 + PyYAML
│   ├── 01_infra_noncontainer/   3  非容器环境底座、38 仓库抓取与 base commit 快照
│   ├── 02_freeze_protocol/      9  任务清单、划分与平衡分配、协议/事件 schema/
│   │                               codebook/策略冻结、Chigh context package、理解检查
│   ├── 03_leakage/              2  答案泄漏机器筛查与双评审仲裁
│   ├── 04_session/              3  session 时钟与事件流、三 regime 权限守卫、75 分钟硬停
│   ├── 05_evaluation/           6  隐藏评价 harness、指标汇总、预注册准入闸门
│   ├── 06_holdout/             14  holdout 测试编写与三条件准入、差分探针、可行性标定
│   ├── 07_rq2_coding/           2  RQ2 编码手册/盲法包/κ 估计器、一致率–κ 边界核算
│   ├── 08_rq3_policy/           5  在线信号提取器、Adaptive Policy 状态机、阈值 CV 演练
│   ├── 09_rq1_rq4_analysis/     2  合成 session 生成 + 管线回收检验
│   ├── 10_audit/                1  A–I 组审计、QA 报告、全量冻结清单
│   └── 99_scratch/              8  一次性诊断、路径修补、PDF 提取（非论文产物）
└── dataset/                 数据集（3,499 文件 / 96 MB）
    ├── tasks/               648 文件  216 个任务：issue / metadata / base_commit
    ├── benchmark_tests/   1,080 文件  F2P / P2P 清单、oracle、test patch、测试命令
    ├── gold/              1,320 文件  216 个任务的 gold patch + commits.csv
    ├── environments/        433 文件  上游 Dockerfile 与环境元数据
    ├── splits/                3 文件  Pilot / Discovery / Held-out 任务清单
    ├── holdout_tests/        14 文件  已通过三条件准入的 holdout 套件 + 标定
    ├── screening/             1 文件  自动筛查结果（难度、可复现性、泄漏风险）
    ├── raw/                 29 文件  **本机保留、未进库**：上游 parquet/jsonl + 论文 PDF
    ├── tasks.csv              1 文件  **本机保留、未进库**：上游数据集全量导出（342 MB）
    ├── repositories/     3,140 文件  **本机保留、未进库**：5 个第三方仓库快照
    ├── contexts/              空
    └── versions/              空
```

`dataset/` 的职责分工：`tasks/`、`benchmark_tests/`、`gold/`、`environments/` 是**输入素材**（来自上游 SWE-bench-Live 与本研究的任务筛选）；`splits/`、`screening/`、`holdout_tests/` 是**本研究的任务级记录**（哪些任务入选、分到哪个阶段），不含受试者数据。

---

## 2. 什么不在仓库里

| 内容 | 本地位置 | 为什么不进库 |
|---|---|---|
| 实验产物与冻结资产 | `experiment_root/`（manifests 216、context_packages 216、evaluation_spec 216、protocol、splits、tools，以及 sessions、evaluation、codebook、interview、screening、policy、audit、analysis） | 是**本研究的输出**，不是代码也不是数据集 |
| 构造 / 演练样本 | `work/`、`run/`（各约 96 MB / 38,000 文件，另含 `run/release/` 发布包） | 按论文报告结果**反向构造**的分析样本，标记为 SYNTHETIC / NOT_A_RESULT；生成器 `work/experiment_root/tools/sim_*.py` 可重建 |
| 实施方案文档提取 | `_docx_extract/`（实施方案 `.docx` 的 XML/文本提取） | 设计文档，非代码非数据 |
| 一次性探针脚本 | 根目录 `_*.py` / `_*.json` / `_*.txt`（30 个） | 非业务代码；正式代码见 `code/`，索引见 `code/CODE_INDEX.md` |
| 上游原始数据归档 | `dataset/raw/`（29 文件 / 1.36 GB：上游 parquet/jsonl + 论文 PDF） | 上游公开数据，可重新下载；按 README §3 获取 |
| 上游数据集全量导出 | `dataset/tasks.csv`（342 MB，70,280 行 × 63 列） | 单文件超 GitHub 100 MB 限制；逐任务素材已在 `dataset/tasks/` |
| 第三方仓库快照 | `dataset/repositories/`（3,140 文件 / 177 MB，含 `.git`） | 许可归上游，可用 `code/01_infra_noncontainer/fetch_repos*.py` 重建 |

忽略规则分两层：对任何 clone 都成立的规则（上游原始数据、全量导出、第三方快照、缓存）写在 `.gitignore`，**随仓库分发**；上表其余「本机资产」（`experiment_root/`、`work/`、`run/`、`_docx_extract/`、探针脚本）的规则写在 `.git/info/exclude`，不随仓库分发。因此 clone 出来的仓库只有 `code/` 与 `dataset/` 两部分。

**真实受试者数据目前不存在**：`experiment_root/sessions/` 为空目录，`experiment_root/STATUS.md` §5 把 792 个正式 session 列为「尚未采集」。因此**本仓库不包含任何个人信息**；`dataset/` 里唯一的 `password` 字样是上游 issue 原文中已脱敏的 `'REDACTED'`。

---

## 3. 数据集来源与重建

| 资产 | 来源 | 获取方式 |
|---|---|---|
| 任务与 issue | SWE-bench-Live 类真实 GitHub issue 数据集 | 重新下载月度 parquet / jsonl 到 `dataset/raw/`（上游公开数据） |
| 仓库快照 | 38 个上游开源仓库的 base commit | `python code/run.py 01_infra_noncontainer/fetch_repos.py` |
| gold patch | 上游 PR / commit | `dataset/gold/commits.csv` 逐任务记录 commit URL 与 patch 文件 |
| holdout 套件 | 本研究编写 | 已生成，随库分发（`dataset/holdout_tests/`） |

重新抓取后的目录布局必须与任务 manifest 里的 `base_commit` 一致，否则审计会报不一致。

---

## 4. 运行

```bash
python -m pip install -r code/requirements.txt     # 仅需 PyYAML

python code/verify.py                              # 代码归档逐字节校验 + 语法检查
python code/run.py --list                          # 列出所有可运行脚本
python code/run.py 10_audit/audit.py               # 全量审计
python code/run.py 05_evaluation/aggregate_metrics.py
python code/run.py 08_rq3_policy/online_policy.py --self-test
```

`code/` 是**镜像 + 统一入口**，不是沙箱：脚本读写的仍是工作区里的实验目录；`code/run.py` 负责把分组目录一起放进 `sys.path`，以解决跨模块 import。`code/README.md` §1 给出「论文四个研究问题 ↔ 代码入口」的对应表。

### 路径要求（重要）

业务代码里**硬编码了绝对路径**：

```python
ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
TIFS = r"C:\Users\Administrator\Desktop\TIFS"
```

`code/` 下 62 个文件中有 **55 个**含此类路径，共 101 处引用：其中 **67 处指向 `experiment_root/`**（未进库）、**21 处指向 `dataset/`**（已进库）、**13 处指向 TIFS 根目录**。因此：

* **只读数据集与算法**：`dataset/` 自带全部输入素材，`code/` 里的构建类脚本（`02_freeze_protocol/`、`03_leakage/`、`06_holdout/`）可直接以 `dataset/` 为输入运行；
* **完整跑通采集与评价链**：需要本机保留的 `experiment_root/`（运行期根目录），或把仓库克隆到 `C:\Users\Administrator\Desktop\TIFS` 后按原布局重建；
* 若要改路径，批量替换 `C:\Users\Administrator\Desktop\TIFS` 为新路径即可；注意 `experiment_root/audit/freeze_manifest.json` 用 tree digest 冻结了产物与生成器源码哈希，改动实验目录会让冻结校验失败。

---

## 5. 许可（待定）

`LICENSE` **尚未添加，待作者确定**。建议分部分处理：

* `code/` 与本研究编写的文档 → 例如 MIT 或 Apache-2.0；
* `dataset/splits/`、`dataset/screening/`、`dataset/holdout_tests/`（本研究整理/编写）→ 例如 CC-BY-4.0；
* `dataset/tasks/`、`dataset/benchmark_tests/`、`dataset/gold/`、`dataset/environments/` 来自上游 SWE-bench-Live 与各开源仓库，**版权归各自上游**，随库分发前请核对上游许可；如有疑虑可只保留指针与哈希，按 §3 重新获取。
