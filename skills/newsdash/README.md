# Page Skill｜书童Skill

**The maintainer-side agent skill for [Relevance](../../README.md).**
Open your Relevance repo in Claude Code / Codex and the skill turns setup and
maintenance into a conversation: it interviews you, writes your config,
classifies new sources, and walks you through every GitHub Secret — without
ever touching a secret value.

Your deployed site nudges you here: on its first successful load it shows a
one-time setup tutorial whose checklist links back to this README. From a cloned
repo, the skill runs a **guided four-step workflow** — (1) **Source Studio**, a
local HTML editor for curating sources into a plan; (2) **Test & report**,
health-checking each source into a shareable freshness chart; (3) **Priority**,
tuning keyword `interests`, per-source `weight`, and the homepage-variety
`ranking` knob; (4) **Categories**, grouping sources into named nav tabs with
bilingual labels. Prefer that hands-on flow when working in a clone; the kickoff
prompt below is the quick chat-only alternative.

## Kickoff prompt

```text
Use Page Skill for Relevance. Interview me first: which preset packs I want
(ai-news, general-news, academic-datavis, academic-techcomm), my interest keywords,
my theme and timezone, and whether the site should be public or private. Then classify
any extra sources I give you as Open, Private, or Optional. Walk me through every
GitHub secret step by step — but never ask me to paste a secret value into the chat,
and never commit tokens or passphrases into the repo.
```

## Why "Page｜书童"?

A 书童 is the scholar's study attendant in classical China: he fetches the
day's readings, sorts the correspondence — and never breaks the seal on a
private letter. "Page" carries the same triple
duty in English: the page boy who attends, the pages you read, and the GitHub
Pages he sweeps every two hours. Where ai-news-radar's 伯乐 (Scout) judged
horses, the 书童 carries your books.

## What it will and won't do

| Will | Won't |
|---|---|
| Interview you and edit `config/` for you | Ask you to paste a passphrase or token into chat |
| Tell you the exact secret name + settings URL + terminal one-liner | Echo, store, or commit any secret value |
| Classify new sources (Open / Private / Optional) and write the config entry | Add a capability URL to the repo (the schema blocks it anyway) |
| Run the validators and watch the deploy | Print your decrypted private sections into a log |

---

# 中文说明

**Page Skill｜书童Skill** 是及君（Relevance）内置的维护侧智能体技能。
在 Claude Code / Codex 中打开你的仓库，它会以对话的方式完成配置：先访谈你的需求，
替你修改 `config/`，为新信源分类，并一步步指导你在 GitHub 上添加各个 Secret——
但绝不经手任何密钥的值。

你部署的站点首次成功加载时，会弹出一次性的设置教程，其清单链接回到本页。在克隆的
仓库中，本技能提供**四步引导流程**：（1）**Source Studio** 本地 HTML 编辑器整理信源
生成方案；（2）**测试与报告** 健康检查各信源并生成可分享的新鲜度图表；（3）**优先级**
调校关键词 `interests`、逐信源 `weight` 与首页多样性 `ranking`；（4）**分类** 将信源
归入带中英标签的自定义导航标签页。在克隆仓库中优先使用该流程；下方启动提示词是纯对话的
快捷替代。

**为什么叫「书童」？** 书童是书斋里的伴读小童：管先生的日程、取当日的书报、
理往来的信件——却从不拆先生的私信。英文 "Page" 恰好一语三关：伴读的书童（page boy）、
你读的页面（pages）、还有他每两小时洒扫一遍的 GitHub Pages。ai-news-radar 的
伯乐相马，及君的书童捧书。

**启动提示词**（粘贴给你的智能体即可，中文交流亦可）：见上方 Kickoff prompt。
