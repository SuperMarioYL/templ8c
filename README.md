<div align="right"><sub><a href="./README.en.md">English</a>&nbsp;&nbsp;⇄&nbsp;&nbsp;<b>简体中文</b></sub></div>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/hero-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/hero-light.svg">
  <img src="./assets/hero-light.svg" width="880" alt="templ8c — chat-template conformance checker">
</picture>

<p align="center"><sub>在国产模型部署前，捕获 chat-template tool-call 不一致的一致性检查器。</sub></p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/github/license/SuperMarioYL/templ8c" alt="license"></a>
  <a href="https://github.com/SuperMarioYL/templ8c/releases"><img src="https://img.shields.io/github/v/release/SuperMarioYL/templ8c" alt="release"></a>
  <a href="https://github.com/SuperMarioYL/templ8c/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/SuperMarioYL/templ8c/ci.yml?label=ci" alt="CI"></a>
  <img src="https://img.shields.io/static/v1?label=python&message=3.12%2B&color=306998" alt="python">
</p>

> 部署前一行命令验证 chat template 的 tool-call 格式——PASS/FAIL + 结构化 diff，精确指出模板哪里与参考 spec 不一致。

<h2><img src="https://api.iconify.design/tabler:topology-star-3.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 架构</h2>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/atlas-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/atlas-light.svg">
  <img src="./assets/atlas-light.svg" width="880" alt="架构：CLI 到 Checker 到 TemplateLoader 与 Renderer 到 Comparator，由 ConformanceSpec 提供预期格式">
</picture>

单进程、单 CLI 入口。`Checker` 加载 Jinja2 chat template（来自 `tokenizer_config.json` 或内置参考模板），用规范测试消息渲染，再由 `Comparator` 逐字段对比 `ConformanceSpec`，输出 `TemplateDiff` 列表。不指定 `--server` 时只检查模板本身渲染是否正确；ServerProbe（m3）之后接入 vLLM/SGLang 实测。

核心原语 **ConformanceSpec**：一个声明式数据结构，定义“某个模型的 chat template 应该产出什么样的 tool-call 格式”——把散落在文档与 issue 里的隐性知识变成显式、可执行的 spec。

<h2><img src="https://api.iconify.design/tabler:bulb.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 为什么需要</h2>

国产模型（GLM-5.3-Flash、Qwen3.8-Flash-Next、DeepSeek-V4）发布周期从季度压缩到周/双周级，每次发布都可能更新 chat template。而 inference server（vLLM、SGLang、llama.cpp）把模板当配置文件加载，不验证它是否“正确”——因为“正确”需要参考实现来对比，server 自己就是被检查对象，不能既当裁判又当运动员。结果是 tool-calling 静默失败：模型输出的 tool-call JSON 与 server 期望的格式不匹配，agent 链路中断，却没有任何部署前检查器能发现。templ8c 补上这个空白——发布后几分钟内确认模板适配是否正确，而不是在 agent 跑挂之后手工排查。

<h2><img src="https://api.iconify.design/tabler:rocket.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 快速开始</h2>

```bash
pip install templ8c
templ8c check --model glm-5.3-flash
# PASS/FAIL + 结构化 diff 指出模板哪里与参考 spec 不一致
```

<details><summary>示例输出</summary>

```
templ8c v0.1.0 — chat template conformance checker
Model: glm-5.3
Template source: bundled reference (tokenizer_config.json)

  Field              Expected        Actual       Status
  system_marker      role token      found        PASS
  user_marker        role token      found        PASS
  tool_call_wrapper  [CALL_TOOL]     found        PASS
  tool_call_schema   get_weather     all present  PASS
  assistant_marker   role token      found        PASS
  tool_call_wrapper  [CALL_TOOL]     found        PASS
  tool_call_schema   get_weather     all present  PASS
  tool_marker        role token      found        PASS

PASS: all fields conform to the reference spec.
```
</details>

<h2><img src="https://api.iconify.design/tabler:terminal-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 用法</h2>

```bash
# 渲染单条消息经过模型 chat template 后的完整 prompt
templ8c render --model glm-5.3-flash --message "What's the weather in SF?"

# 一致性检查（m1 仅检查模板渲染本身）
templ8c check --model qwen3.8

# 列出支持的模型家族
templ8c models
```

编程 API 见 [`examples/render_example.py`](./examples/render_example.py)：

```python
from templ8c.checker import Checker

checker = Checker()
print(checker.render("glm-5.3-flash", "What's the weather in SF?"))
result = checker.check("glm-5.3-flash")
print(result.passed, result.failed_count)
```

<h2><img src="https://api.iconify.design/tabler:photo.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Demo</h2>

![demo](assets/demo.gif)

<h2><img src="https://api.iconify.design/tabler:map-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 路线图</h2>

- [x] **m1** — 加载并渲染 chat template（GLM-5.3 / Qwen3.8 / DeepSeek-V4）+ ConformanceSpec / comparator，输出 PASS/FAIL + 结构化 diff
- [ ] **m2** — 每家模型独立 spec 文件 + rich 彩色 diff 输出
- [ ] **m3** — ServerProbe：通过 vLLM / SGLang API 实测 server 渲染的 template
- [ ] 未来 — CI/CD 集成（GitHub Action step）、更多 CN 模型与 inference server

<h2><img src="https://api.iconify.design/tabler:license.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 许可证</h2>

MIT — 见 [`LICENSE`](./LICENSE)。欢迎提 issue 或 PR。

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
