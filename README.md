# 学徒跨企业轮岗的学分兑现与席位互换

一个学期的职业学校轮岗演练。日历以左闭右开日期区间交接，学分小时与席位数分别声明。

## 资料约定

CSV 使用 UTF-8，首行为列名。多值字段以竖线分隔。空单元格表示来源未填。

- requirements.csv。每条毕业能力需要的时数与课程前置。version 与 active_from 是公布口径。
  字段为 `mode`、`competency`、`min_hours`、`precedes`、`version`、`active_from`。
- people.csv。学生适用方向及结业截止。mode_options 以管道符分隔可选的完整方向。
  字段为 `learner`、`mode_options`、`deadline`。
- proofs.csv。实作时数证明。uses 是可选用途，group 中非空值表示必须共同认定的整套实作。withdrawn/replaces 表示导师撤回的事实。
  字段为 `proof`、`learner`、`hours`、`uses`、`group`、`completed`、`mentor`、`state`、`replaces`、`received`。
- rotations.csv。企业可给的轮岗席位。requires 是入场之前的能力，offers/hours 对应按要求完成后可认定的能力。导师相同且区间重叠时共用 mentor_limit。
  字段为 `slot`、`firm`、`mentor`、`start`、`end`、`requires`、`offers`、`hours`、`seats`、`mentor_limit`。
- agreements.csv。企业和学校收到的席位安排。group 非空的多条需要当作一个交换承诺，旧协议引用不会随提议删除。
  字段为 `agreement`、`learner`、`slot`、`status`、`group`、`replaces`、`recorded`。
- acknowledgements.csv。对交换提议的外部确认与证明补报。party 表示有签认权的角色，source_id 关联本行依据。
  字段为 `entry`、`agreement`、`party`、`state`、`source_id`、`recorded`。

## 认定与排席规则

代码只做资料可支持的判断，不替学校做用途决定：

- **时数一次性使用**：一份证明在一个毕业方向内只能认定到一个候选能力；同一批时数不会同时冲抵两个毕业要求。
- **整套实作**：`group` 非空的证明要么全部共同认定、要么全部不用。
- **撤回与替代**：撤回的证明“记录尚在、学分不可用”；被新确认证明替代（`replaces`）的旧证明退出有效集，记录仍保留。
- **候选不自动决定**：证明的 `uses` 有多个候选且资料无法区分实际用途时，全部认定选择都保留并标记为待学籍确认，系统不会自动选一个。
- **前置链**：能力按 `precedes` 链判定，前置未满足的缺口标记为 blocked；轮岗席位的 `requires` 在接席开始日检查，进行中或未开始的轮岗不提前计学分。
- **席位双层容量**：单席位受 `seats` 限制；同一导师、区间重叠的席位共用 `mentor_limit`。区间为左闭右开，端点相接不算重叠。
- **互换承诺**：同一 `group` 的提议是一个整体，任一方 `declined` 即整组作废、原持有人保留席位；全部签认 `accepted` 才生效，生效日取最后一条签认日；签认依据的证明被撤回时整组转为需重核。
- **不可回滚与可暂停**：已完成（`as_of >= end`）的轮岗锁定；尚未开始（`as_of < start`）的席位可暂停交接并恢复。
- **路径三分类**：`on_track`（现有认定即可毕业）、`feasible`/`needs_confirmation`（需新增轮岗或确认用途）、`deficient`（截止日前无可行组合）。

## 模块结构

- `apprenticeship/dates.py`：左闭右开区间与日期解析。
- `apprenticeship/models.py`：领域模型与 `Registry` 索引视图。
- `apprenticeship/loader.py`：CSV 读取、枚举/外键/容量结构校验（违例抛 `DataError`）。
- `apprenticeship/recognition.py`：证明账面、认定候选枚举、前置链与缺口。
- `apprenticeship/capacity.py`：席位与导师容量的半开区间事件检查。
- `apprenticeship/seating.py`：互换组状态机、协议阶段、投影可兑现性。
- `apprenticeship/planning.py`：单人轮岗组合与整组联合排席（无备选方向的学生优先）。
- `apprenticeship/events.py`：撤回重核、席位暂停/恢复（返回新 Registry，不改输入）。
- `apprenticeship/cli.py` / `run.py`：命令行入口。

## 命令行用法

全局参数 `--data`（资料目录，默认 `samples/`）、`--as-of YYYY-MM-DD`（评估基准日）、`--json`（机读输出）需放在子命令之前。

```bash
# 查学生各方向的认定候选与能力缺口（含已完成轮岗时数）
python3 -I run.py --as-of 2026-11-25 credit A1
# 证明账面：有效 / 已撤回 / 已被替代
python3 -I run.py --as-of 2026-11-25 ledger A1
# 互换承诺的分组签认状态、生效日与失效依据
python3 -I run.py --as-of 2026-11-25 swaps
# 毕业路径、单人轮岗组合与整组联合排席
python3 -I run.py --as-of 2026-11-25 plan
# 保留确认席位与假设互换通过两套投影的容量/前置/截止日检查
python3 -I run.py --as-of 2026-11-25 seats
# 模拟撤回证明，输出受影响方向、失效互换组与重核后的路径
python3 -I run.py --as-of 2026-11-25 withdraw P6
# 暂停/恢复尚未开始的席位交接（已完成轮岗拒绝暂停）
python3 -I run.py --as-of 2026-11-25 pause C2
```

`-I` 为隔离模式：忽略当前目录与环境变量中的模块，避免资料目录里被植入的 `json.py` 之类文件被解释器加载。`run.py` 会显式把项目根目录加入 `sys.path`。

## 检查演练资料

使用 Python 3.11.2 标准库，无需安装第三方依赖。在项目根目录运行下列命令可检查 CSV 读取、资料关联及样例记录完整性。

```bash
python3 -m unittest discover -s tests -v
# 隔离模式同样可用
python3 -I -m unittest discover -s tests -v
```

测试覆盖读取契约与坏资料拒绝、认定一次性时数/整套实作/撤回替代链、半开区间容量、互换组状态机、单人与整组规划、撤回重核与暂停锁定，以及全部 CLI 子命令的冒烟输出。
