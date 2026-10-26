"""卡片动作事件的来源验证与归一化。

这是整个审核闭环最关键的一段。规格要求：

- BE-IF-02：`applyDecision` **只接受已验证的飞书适配器调用**，校验组织、
  消息归属、审核人 allowlist、版本、摘要、PENDING 与有效期。
- BE-RULE-08：卡片 GET 预览无写副作用，只有可信审核动作才建立授权。
- BE-NFR-07：凭据不进模型上下文、卡片及普通日志。
- BE-IF-02 注：飞书协议接收成功不等于审核已批准。

所以本模块的职责是：把**平台送达的**回调载荷，转换成
**带可信操作者身份**的 `VerifiedReviewerContext` + `ReviewDecision`。
不可信或缺字段的一律拒绝，不做任何"尽力而为"的补全。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: 错误契约见 manual/specs/backend/approval-publishing.spec.md BE-ERR-01。
ERROR_UNAUTHORIZED = "UNAUTHORIZED"
ERROR_FORBIDDEN = "FORBIDDEN"
ERROR_STALE_REVIEW = "STALE_REVIEW"
ERROR_VALIDATION = "VALIDATION_ERROR"

#: 契约上限：ReviewDecision.feedback 的 maxLength。
FEEDBACK_MAX_LEN = 500


@dataclass
class VerifiedReviewerContext:
    """完成来源验证后的可信上下文。

    这些字段**只能**来自平台事件，不能由模型或调用方填入。
    """

    workspace_id: str
    tenant_key: str
    operator_open_id: str
    operator_user_id: str | None
    open_message_id: str
    open_chat_id: str
    preview_token: str | None = None


@dataclass
class ReviewDecision:
    """从已验证事件提取的内部决定输入。

    字段与 manual/contracts/cyber-sloth.schema.json 的 `ReviewDecision` 对应。
    """

    provider_event_id: str
    review_id: str
    expected_revision: int
    content_digest: str
    action: str
    feedback: str | None = None


@dataclass
class DecisionRejection:
    """来源验证不通过。"""

    code: str
    message: str
    hint: str = ""


def _get(payload: dict[str, Any], *path: str) -> Any:
    """安全地按路径取值，任何一层缺失都返回 None。"""
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def extract_operator(payload: dict[str, Any]) -> dict[str, Any] | None:
    """从回调载荷里取操作者与会话信息。

    载荷结构来自 `lark_oapi` 的 `P2CardActionTriggerData`：
        operator  -> tenant_key / user_id / open_id
        context   -> open_message_id / open_chat_id / preview_token
    缺任一必需项都返回 None——宁可拒绝，不可补全。
    """
    operator = _get(payload, "operator")
    context = _get(payload, "context")
    if not isinstance(operator, dict) or not isinstance(context, dict):
        return None

    open_id = operator.get("open_id")
    tenant_key = operator.get("tenant_key")
    open_message_id = context.get("open_message_id")
    open_chat_id = context.get("open_chat_id")
    if not all(isinstance(v, str) and v for v in (open_id, tenant_key, open_message_id, open_chat_id)):
        return None

    user_id = operator.get("user_id")
    preview_token = context.get("preview_token")

    return {
        "tenant_key": tenant_key,
        "open_id": open_id,
        "user_id": user_id if isinstance(user_id, str) and user_id else None,
        "open_message_id": open_message_id,
        "open_chat_id": open_chat_id,
        "preview_token": preview_token if isinstance(preview_token, str) and preview_token else None,
    }


def extract_action(payload: dict[str, Any]) -> dict[str, Any] | None:
    """取按钮动作、绑定值，以及可选的退回意见。"""
    action_obj = _get(payload, "action")
    if not isinstance(action_obj, dict):
        return None
    value = action_obj.get("value")
    if not isinstance(value, dict):
        return None

    name = value.get("action")
    if not isinstance(name, str) or name not in ("approve", "reject", "cancel"):
        return None

    # 退回意见：可能来自表单（form_value）或单个输入框（input_value）。
    # 两条都读，取到第一个字符串。卡片没有输入组件时恒为 None。
    raw_feedback: str | None = None
    form_value = action_obj.get("form_value")
    if isinstance(form_value, dict):
        candidate = form_value.get("feedback")
        if isinstance(candidate, str):
            raw_feedback = candidate
    if raw_feedback is None:
        candidate = action_obj.get("input_value")
        if isinstance(candidate, str):
            raw_feedback = candidate

    return {
        "action": name,
        "review_id": value.get("review_id"),
        "revision": value.get("revision"),
        "content_digest": value.get("content_digest"),
        "feedback": raw_feedback,
    }


def normalize(
    payload: dict[str, Any],
    *,
    workspace_id: str,
    expected_tenant_key: str | None,
    allowed_chat_ids: set[str],
    reviewer_allowlist: set[str],
    provider_event_id: str,
) -> tuple[VerifiedReviewerContext | None, ReviewDecision | None, DecisionRejection | None]:
    """把平台回调归一化为可信上下文与决定输入。

    返回三元组，成功时前两项有值；失败时第三项给出错误码与原因。
    校验顺序按 BE-ERR-01 的错误优先级：先来源/权限，再资源，再幂等，
    最后版本/状态。
    """
    operator = extract_operator(payload)
    if operator is None:
        return (
            None,
            None,
            DecisionRejection(
                code=ERROR_UNAUTHORIZED,
                message="回调缺少可验证的操作者或会话信息",
                hint="不补全身份；确认事件来自平台长连接而非外部构造。",
            ),
        )

    # 1. 组织校验：跨组织的动作不建立授权。
    if expected_tenant_key and operator["tenant_key"] != expected_tenant_key:
        return (
            None,
            None,
            DecisionRejection(
                code=ERROR_UNAUTHORIZED,
                message=f"事件组织不匹配：{operator['tenant_key']}",
                hint="只接受本应用所属组织的审核动作。",
            ),
        )

    # 2. 消息归属校验：只在配置的审核会话里生效。
    if operator["open_chat_id"] not in allowed_chat_ids:
        return (
            None,
            None,
            DecisionRejection(
                code=ERROR_FORBIDDEN,
                message=f"会话不在审核会话白名单：{operator['open_chat_id']}",
                hint="审核动作只认配置过的会话。",
            ),
        )

    # 3. 审核人 allowlist：模型提交的 JSON 不能创建可信审核身份。
    if operator["open_id"] not in reviewer_allowlist:
        return (
            None,
            None,
            DecisionRejection(
                code=ERROR_FORBIDDEN,
                message=f"操作者不在审核人白名单：{operator['open_id']}",
                hint="只有授权审核人能批准或退回。",
            ),
        )

    action = extract_action(payload)
    if action is None:
        return (
            None,
            None,
            DecisionRejection(
                code=ERROR_UNAUTHORIZED,
                message="回调缺少可识别的审核动作",
                hint="只认卡片上三个受支持的按钮。",
            ),
        )

    review_id = action["review_id"]
    revision_raw = action["revision"]
    digest = action["content_digest"]
    if not isinstance(review_id, str) or not review_id:
        return (
            None,
            None,
            DecisionRejection(
                code=ERROR_STALE_REVIEW,
                message="卡片动作未绑定审核 ID",
                hint="旧卡片或被改稿取消的审核应按 STALE_REVIEW 处理。",
            ),
        )
    try:
        revision = int(revision_raw)
    except (TypeError, ValueError):
        revision = -1
    if revision < 1 or not isinstance(digest, str) or not digest:
        return (
            None,
            None,
            DecisionRejection(
                code=ERROR_STALE_REVIEW,
                message="卡片动作的版本或摘要绑定无效",
                hint="使用当前版本重新送审后的卡片。",
            ),
        )

    # 退回意见的处理规则（契约：ReviewDecision.feedback）
    # - 批准 / 取消：必须为 null，即使输入框里有字也不采纳
    # - 退回：可选；纯空白视为未填写 → null；超长直接拒绝，不静默截断
    feedback: str | None = None
    if action["action"] == "reject":
        raw = action.get("feedback")
        if isinstance(raw, str) and raw.strip():
            text = raw.strip()
            if len(text) > FEEDBACK_MAX_LEN:
                return (
                    None,
                    None,
                    DecisionRejection(
                        code=ERROR_VALIDATION,
                        message=f"退回意见过长：{len(text)} 字，上限 {FEEDBACK_MAX_LEN} 字",
                        hint="缩短意见后重新提交；按契约不静默截断。",
                    ),
                )
            feedback = text

    context = VerifiedReviewerContext(
        workspace_id=workspace_id,
        tenant_key=operator["tenant_key"],
        operator_open_id=operator["open_id"],
        operator_user_id=operator["user_id"],
        open_message_id=operator["open_message_id"],
        open_chat_id=operator["open_chat_id"],
        preview_token=operator["preview_token"],
    )
    decision = ReviewDecision(
        provider_event_id=provider_event_id,
        review_id=review_id,
        expected_revision=revision,
        content_digest=digest,
        action=action["action"],
        feedback=feedback,
    )
    return context, decision, None
