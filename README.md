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

## 检查演练资料

使用 Python 3.11.2 标准库，无需安装第三方依赖。在项目根目录运行下列命令可检查 CSV 读取、资料关联及样例记录完整性。

```bash
python3 -m unittest discover -s tests -v
```
