# project — 仓库级软件缺陷修复的委托研究

业务代码（`code/`）与数据集（`dataset/`）：38 个仓库 / 216 个任务，SWE-bench-Live 类的仓库级纠错性缺陷修复任务。

---

## 运行

### 环境

```bash
python -m pip install -r code/requirements.txt     # 只依赖标准库 + PyYAML
```

需要 Python 3.11（宿主实测 3.11.7）、git，以及能访问 github.com / codeload.github.com 的网络。

### 命令

```bash
python code/verify.py                              # 校验代码副本与源逐字节一致 + 全量语法检查
python code/run.py --list                          # 列出所有可运行脚本
python code/run.py <脚本> [参数]                    # 用统一入口运行任意脚本

# 常用入口
python code/run.py 10_audit/audit.py                       # 全量审计
python code/run.py 05_evaluation/aggregate_metrics.py      # 指标汇总
python code/run.py 05_evaluation/evaluate.py --session-id D-S0001
python code/run.py 08_rq3_policy/online_policy.py --self-test
python code/run.py 09_rq1_rq4_analysis/check_pipeline.py   # 管线自检
```

### 两个执行器

| 文件 | 作用 |
|---|---|
| `code/run.py` | 统一启动器：把 `code/` 各分组目录与 `experiment_root/{tools,evaluation,repo_cache}` 一起放进 `sys.path`，解决跨模块 import（如 `simulate.py` 要 `import online_policy, rq2_coding`） |
| `code/sync.py` / `code/verify.py` | 把 `code/` 重新对齐到权威代码目录并刷新 `CODE_INDEX.json` 的哈希；`verify.py` 逐字节比对 + 语法检查 |

大部分脚本也可直接运行（内部用的是绝对 `ROOT`），只有 `holdout_author.py` 必须走 `run.py`（它用 `__file__` 推导 `sys.path`）。

### 路径要求

代码里硬编码了绝对路径，形如：

```python
ROOT = r"<仓库根>\experiment_root"
PROJECT = r"<仓库根>"
```

本机脚本里写的是 `C:\Users\Administrator\Desktop\TIFS\...`；把工作区目录改名为 `project` 后即为 `C:\Users\Administrator\Desktop\project\...`。`code/` 的 62 个文件中有 55 个含此类路径，共 101 处：67 处指向 `experiment_root/`（运行期根目录，不在本仓库内）、21 处指向 `dataset/`（已随仓库分发）、13 处指向仓库根。因此：

* **只读数据集与算法**：`dataset/` 自带全部输入素材，`02_freeze_protocol/`、`03_leakage/`、`06_holdout/` 的构建类脚本可直接以 `dataset/` 为输入运行；
* **完整跑通采集与评价链**：需要本机另有一份 `experiment_root/` 作为运行期根目录，或把仓库放到脚本里那两个绝对路径所指的位置；
* 换路径就批量替换那个路径字符串；注意 `experiment_root/audit/freeze_manifest.json` 用 tree digest 冻结了产物与生成器源码哈希，改动实验目录会让冻结校验失败。

### 代码索引

`code/CODE_INDEX.md`（人读）与 `code/CODE_INDEX.json`（机读）给出每个文件的用途、论文锚点、源路径与 SHA256；`code/README.md` §1 给出「研究问题 ↔ 代码入口」的对应表。索引由 `python code/sync.py` 生成。

---

## 数据集

| 目录 | 文件 | 内容 |
|---|---:|---|
| `dataset/tasks/` | 648 | 216 个任务：`issue.json` / `metadata.json` / `base_commit.txt` |
| `dataset/benchmark_tests/` | 1,080 | F2P / P2P 清单、oracle、test patch、测试命令 |
| `dataset/gold/` | 1,320 | 216 个 gold patch + `commits.csv`（commit URL、改动行数、模块数） |
| `dataset/environments/` | 433 | 上游 Dockerfile 与环境元数据 |
| `dataset/splits/` | 3 | Pilot / Discovery / Held-out 任务清单 |
| `dataset/holdout_tests/` | 14 | 已通过三条件准入的 holdout 套件 + 标定 |
| `dataset/screening/` | 1 | 自动筛查结果（难度、可构建性、外部依赖、泄漏风险） |

重建与补全：

* 仓库快照（未随库分发）：`python code/run.py 01_infra_noncontainer/fetch_repos.py`，抓完的布局必须与任务 manifest 里的 `base_commit` 一致；
* 上游原始数据归档（未随库分发）：按上游公开数据重新下载到 `dataset/raw/`。
