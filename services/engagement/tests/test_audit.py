"""审计日志的测试。"""

from __future__ import annotations

from engagement.audit import AuditLog
from engagement.models import ReplyCandidate, make_record
from engagement.policy import assess


def cand(reply: str = "谢谢支持") -> ReplyCandidate:
    return ReplyCandidate(
        event_id="evt-1",
        oid="413402056",
        rpid=318247075745,
        comment_type="draw",
        author_name="某人",
        author_mid="392014397",
        source_text="原来的评论",
        reply_text=reply,
    )


def test_append_and_read(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    c = cand()
    log.append(make_record(c, assess(c), outcome="sent", platform_rpid=321952387456))

    records = log.read_all()
    assert len(records) == 1
    r = records[0]
    assert r["event_id"] == "evt-1"
    assert r["outcome"] == "sent"
    assert r["platform_rpid"] == 321952387456
    # 判定依据必须留下来
    assert r["rule"]
    assert r["reason"]
    assert r["risk"] and r["route"]


def test_already_handled(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    c = cand()
    assert log.already_handled("evt-1") is False
    log.append(make_record(c, assess(c), outcome="sent"))
    assert log.already_handled("evt-1") is True
    assert log.already_handled("evt-2") is False


def test_bad_line_is_skipped(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    c = cand()
    log.append(make_record(c, assess(c), outcome="sent"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{ 这不是 json\n")
    log.append(make_record(cand("是的"), assess(cand("是的")), outcome="sent"))

    records = log.read_all()
    assert len(records) == 2


def test_holds_record_no_platform_id(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    c = cand("加我微信私聊")
    record = make_record(c, assess(c), outcome="held", detail="需人工确认")
    log.append(record)
    r = log.read_all()[0]
    assert r["outcome"] == "held"
    assert r["platform_rpid"] is None
    assert r["route"] == "single"


def test_missing_file_returns_empty(tmp_path):
    assert AuditLog(tmp_path / "nope.jsonl").read_all() == []
