# Roblox UGC for Codex & Claude

[Русский](README.ru.md)

Create, validate and troubleshoot Roblox Marketplace avatar items: accessories, hair, layered/classic clothing, shoes, bodies, dynamic heads, makeup, emotes and animation packs. Includes official documentation, practical workflows, Blender helpers and optional Studio validation. The agent replies in your language.

## Install

**Codex CLI / Desktop** — run, then start a new session:

```bash
codex plugin marketplace add hiworld1231/roblox-ugc-skill
codex plugin add roblox-ugc@roblox-ugc-skill
```

**Claude Code 2.1.292+**:

```bash
claude plugin install roblox-ugc --marketplace hiworld1231/roblox-ugc-skill
```

Older versions: `claude plugin marketplace add hiworld1231/roblox-ugc-skill`, then `claude plugin install roblox-ugc@roblox-ugc-skill`.

**Claude Desktop / Chat / Cowork**: **Customize → Plugins → Add → Add marketplace → Add from a repository** → enter `hiworld1231/roblox-ugc-skill` → install Roblox UGC. Alternatively, upload the [standalone skill ZIP](https://github.com/hiworld1231/roblox-ugc-skill/releases/latest) through **Customize → Skills**. Plugin/skill availability depends on your Claude plan and organization settings.

## Use

- “Create an original low-poly Roblox hat. Deliver the Blender project, textures, FBX and preview.”
- “Fix this jacket's cages and explain which validation checks remain.”
- “Prepare my dynamic head / makeup / animation pack for Marketplace publication.”

Codex: `$roblox-ugc`. Claude Code: `/roblox-ugc:roblox-ugc`. Automatic discovery is enabled.

Knowledge works without Blender or an MCP server. Helpers need **Python 3.10+**; 3D creation/checks need **Blender**. Actual import, fitting and Roblox validation need **Roblox Studio** or an available Studio integration. No Roblox credentials or paid services are required to install.

## Coverage & verification

Pinned official corpus: **360 included documents/APIs**, **1,972 excluded candidates with reasons**, plus image/template/video and external-source inventories. Fees, policies and eligibility are rechecked live when needed. Video links are tracked separately; this release does **not** claim every video or internet tutorial was reviewed.

[Coverage and limitations](docs/coverage.md) · [Validation evidence](docs/validation.json) · [Tools and workflows](plugins/roblox-ugc/skills/roblox-ugc/references/authoring.md) · [Releases](https://github.com/hiworld1231/roblox-ugc-skill/releases)

Original code/instructions: MIT. Roblox documentation: CC BY 4.0; upstream code samples: MIT. [Attribution](plugins/roblox-ugc/skills/roblox-ugc/ATTRIBUTION.md). Unofficial community project; Roblox approval and publication are separate from offline preflight.
