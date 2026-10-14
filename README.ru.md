# Roblox UGC для Codex и Claude

[English](README.md)

Помогает создавать и проверять UGC для Marketplace: аксессуары, волосы, layered/classic clothing, обувь, тела, dynamic heads, makeup, emotes и animation packs. Внутри — официальная документация, практические инструкции, помощники Blender и проверка в Studio. Агент отвечает на вашем языке.

## Установка

**Codex CLI / Desktop** — выполните и начните новую сессию:

```bash
codex plugin marketplace add hiworld1231/roblox-ugc-skill
codex plugin add roblox-ugc@roblox-ugc-skill
```

**Claude Code 2.1.292+**:

```bash
claude plugin install roblox-ugc --marketplace hiworld1231/roblox-ugc-skill
```

Для предыдущих версий: `claude plugin marketplace add hiworld1231/roblox-ugc-skill`, затем `claude plugin install roblox-ugc@roblox-ugc-skill`.

**Claude Desktop / Chat / Cowork**: **Customize → Plugins → Add → Add marketplace → Add from a repository** → `hiworld1231/roblox-ugc-skill` → установите Roblox UGC. Другой вариант: загрузите [ZIP отдельного skill](https://github.com/hiworld1231/roblox-ugc-skill/releases/latest) через **Customize → Skills**. Доступность зависит от тарифа Claude и настроек организации.

## Примеры

- «Создай оригинальную low-poly шляпу для Roblox. Нужны Blender-проект, текстуры, FBX и preview».
- «Исправь cages этой куртки и покажи, что ещё нужно проверить».
- «Подготовь dynamic head / makeup / animation pack к публикации».

В Codex: `$roblox-ugc`. В Claude Code: `/roblox-ugc:roblox-ugc`. Автоматическое обнаружение включено.

Для базы знаний Blender/MCP не нужны. Помощники требуют **Python 3.10+**; создание и проверка 3D — **Blender**. Реальные импорт, примерка и Roblox validation требуют **Roblox Studio** или доступной интеграции. Для установки не нужны Roblox-пароль или платные сервисы.

## Покрытие и проверки

Зафиксированный официальный корпус: **360 документов/API**, **1 972 исключённых кандидатов с причинами**, отдельные списки изображений, шаблонов, видео и внешних источников. Цены, правила и eligibility перепроверяются перед использованием. Ссылки на видео учитываются отдельно: релиз **не заявляет**, что просмотрены все видео и все туториалы интернета.

[Покрытие и ограничения](docs/coverage.md) · [Результаты проверок](docs/validation.json) · [Инструменты](plugins/roblox-ugc/skills/roblox-ugc/references/authoring.md) · [Релизы](https://github.com/hiworld1231/roblox-ugc-skill/releases)

Собственный код и инструкции — MIT; документация Roblox — CC BY 4.0, примеры кода Roblox — MIT. [Источники и лицензии](plugins/roblox-ugc/skills/roblox-ugc/ATTRIBUTION.md). Неофициальный проект сообщества; offline-проверка не подтверждает модерацию или публикацию Roblox.
