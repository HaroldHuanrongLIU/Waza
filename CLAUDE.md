# Waza

Skill collection for engineering workflows. 8 skills: `think` / `design` / `check` / `hunt` / `write` / `learn` / `read` / `health`.

## 启动前

- 全局规则在 `~/.claude/CLAUDE.md`（写作 / 提交 / 安全 / 验证 / 响应风格）。
- 仓库地图、Skill vs Script 判定、Skill Design Rules、Distribution Rules、Adding Or Changing A Skill、Verification、Commit And Release 全在 `AGENTS.md`。
- 改 skill 前先看 `skills/RESOLVER.md` 的路由表。

## 常用命令

```bash
make test                       # 改 skill 行为 / packaging / scripts / marketplace 前必跑
make package                    # 构建 Claude Desktop 分发 ZIP
./scripts/verify-skills.sh      # 验证 skill 元数据一致性
```

## 项目独有硬规则

- 改任何 skill 的 description / trigger / scope 时，**同步更新** `skills/RESOLVER.md` 和 `.claude-plugin/marketplace.json`，三个地方必须一致。
- 保持 Waza 通用：不要硬编个人 home 路径、私有凭证或本机工作流。项目特异性应当从公开 repo context 在运行时提取。
- 加新 skill 不要在仓库根添加 `SKILL.md`，会阻止嵌套 skill 发现。
- 大段实现不要塞在 Makefile heredoc 或 shell heredoc 里；放到 `tests/test_*.sh` 或可导入的 `.py` 文件，再用薄 shell wrapper 调用。
- 一次性的 review 报告不要直接进仓库长期文档；只把稳定规则沉淀到 `AGENTS.md`、`rules/`、`skills/*/references/` 或校验脚本。
- 从具体项目复盘 Waza 时，只抽象可迁移的工作流规则；项目命令、路径、安全边界和 release 细节留在该项目自己的公开上下文。
- 本地未跟踪的 agent 指令只能做私有 overlay；需要未来 agent 或贡献者遵守的规则必须进入已跟踪、可分发的文档或 skill/rule 文件。
- 发版完成后给 GitHub release 加 6 个正向反应（`+1` / `laugh` / `heart` / `hooray` / `rocket` / `eyes`），通过 `gh api` 操作。**永远不加** `-1` / `confused`。
- README 顶部不堆长文（English Coaching 等推广段）。README 的目的是让人 30 秒读完知道 Waza 是什么，详细规则归到对应 `skills/<name>/SKILL.md` 和 `rules/*.md`。
