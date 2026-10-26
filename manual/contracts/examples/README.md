# 候选契约示例

这些文件只用于理解数据结构和检查 Schema。账号、UUID、图片摘要和 manifest 摘要均为虚构值，不可作为真实素材、授权或发布证据。

| 文件 | `$defs` 定义 | 预期结构校验 |
| --- | --- | --- |
| [create-draft.request.json](create-draft.request.json) | CreateDraftRequest | 通过 |
| [review-request.pending.json](review-request.pending.json) | ReviewRequest | 通过 |
| [review-decision.approve.json](review-decision.approve.json) | ReviewDecision | 通过，但不代表来源已验证 |
| [publish-job.result-unknown.json](publish-job.result-unknown.json) | PublishJob | 通过 |
| [invalid.create-draft.empty-assets.json](invalid.create-draft.empty-assets.json) | CreateDraftRequest | 拒绝，assets 不能为空 |

JSON Schema 不能证明图片文件存在、摘要与字节相符、审核人身份真实或状态转换合法。后续契约测试和真实集成分别验证这些约束。
