"""领域模型：实作证明、轮岗席位、席位协议与外部签认。

状态取值集中在这里，避免业务代码里散落字符串字面量。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .dates import overlaps

# 证明状态
PROOF_CONFIRMED = "confirmed"
PROOF_WITHDRAWN = "withdrawn"

# 协议状态
AGR_CONFIRMED = "confirmed"   # 已确认、当前持有的席位
AGR_PROPOSED = "proposed"     # 互换提议，等待签认

# 签认状态
ACK_ACCEPTED = "accepted"
ACK_DECLINED = "declined"
ACK_PENDING = "pending"

# 有签认权的角色
PARTY_LEARNER = "learner"
PARTY_SCHOOL = "school"
PARTY_FIRM = "firm"


@dataclass(frozen=True)
class Requirement:
    """某毕业方向（mode）下一项能力的公布口径。"""
    mode: str
    competency: str
    min_hours: int
    prerequisite: str | None      # precedes 列：本能力的前置能力
    version: int
    active_from: date


@dataclass(frozen=True)
class Person:
    learner: str
    mode_options: tuple[str, ...]
    deadline: date


@dataclass(frozen=True)
class Proof:
    proof: str
    learner: str
    hours: int
    uses: tuple[str, ...]         # 可认定的候选能力
    group: str | None             # 非空表示必须整套共同认定
    completed: date
    mentor: str
    state: str                    # confirmed / withdrawn
    replaces: str | None          # 本证明替代的旧证明
    received: date

    @property
    def is_withdrawn(self) -> bool:
        return self.state == PROOF_WITHDRAWN


@dataclass(frozen=True)
class Slot:
    slot: str
    firm: str
    mentor: str
    start: date
    end: date
    requires: tuple[str, ...]     # 入场前必须已具备的能力
    offers: str                   # 完成后可认定的能力
    hours: int
    seats: int
    mentor_limit: int

    def overlaps(self, other: "Slot") -> bool:
        return overlaps(self.start, self.end, other.start, other.end)

    def finishes_by(self, deadline: date) -> bool:
        # 左闭右开：end 当日学员已离开，end <= deadline 即按期完成
        return self.end <= deadline


@dataclass(frozen=True)
class Agreement:
    agreement: str
    learner: str
    slot: str
    status: str                   # confirmed / proposed
    group: str | None             # 非空表示属于同一个互换承诺
    replaces: str | None          # 生效后被替换的旧协议
    recorded: date


@dataclass(frozen=True)
class Acknowledgement:
    entry: str
    agreement: str
    party: str                    # learner / school / firm
    state: str                    # accepted / declined / pending
    source_id: str | None         # 本行依据（学生、证明或企业标识）
    recorded: date


@dataclass
class Registry:
    """一整学期资料的内存视图，按外键建立索引。"""
    requirements: list[Requirement]
    people: list[Person]
    proofs: list[Proof]
    slots: list[Slot]
    agreements: list[Agreement]
    acknowledgements: list[Acknowledgement]
    paused_agreements: frozenset[str] = frozenset()

    proofs_by_id: dict[str, Proof] = field(init=False, default_factory=dict)
    slots_by_id: dict[str, Slot] = field(init=False, default_factory=dict)
    agreements_by_id: dict[str, Agreement] = field(init=False, default_factory=dict)
    people_by_id: dict[str, Person] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.proofs_by_id = {p.proof: p for p in self.proofs}
        self.slots_by_id = {s.slot: s for s in self.slots}
        self.agreements_by_id = {a.agreement: a for a in self.agreements}
        self.people_by_id = {p.learner: p for p in self.people}

    def proofs_for(self, learner: str) -> list[Proof]:
        return [p for p in self.proofs if p.learner == learner]

    def agreements_for(self, learner: str) -> list[Agreement]:
        return [a for a in self.agreements if a.learner == learner]

    def acks_for(self, agreement_id: str) -> list[Acknowledgement]:
        return [k for k in self.acknowledgements if k.agreement == agreement_id]

    def slot_of(self, agreement_id: str) -> Slot:
        return self.slots_by_id[self.agreements_by_id[agreement_id].slot]
