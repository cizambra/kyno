# Kyno documentation

The [project README](../README.md) tells you what Kyno is and gets you running.
These pages hold everything else, for when you're wiring Kyno into a real
system and want the full detail. I ordered them the way I'd read them,
but each one stands alone.

1. [Direction at runtime](direction.md). The primitive, its relationship to
   tasks and policies, and an example of direction changing independently.
2. [Writing constitutions](constitutions.md). The file, its fields, how
   edits carry forward, and running several constitutions side by side.
3. [The MCP contract](contract.md). Every tool Kyno serves, the compact
   and full reads, and subscriptions.
4. [The adapters in depth](adapters.md). What the binder does on every
   pull, the failure postures, and application-owned verification. The
   [CrewAI](crewai.md) and [LangGraph](langgraph.md) guides cover framework-specific setup.
5. [Build your own adapter](integrating.md). How to build one for any
   framework or language, in five stages with a checker.
6. [Publishing your constitution](publishing.md). The public page, the
   colors, and your own templates.
7. [Operating Kyno](operating.md). Storage, auth, remote mode, deploying,
   and testing.
8. [Best practices](best-practices.md). The operating sequence once real
   agents depend on the store: review, CI, rehearsal, and repair.
9. [Recovering earlier direction](recovery.md). Read reviewed content,
   apply it as a new version, and assess work done under incorrect direction.

## 💬 Questions?

[Ask one](https://github.com/cizambra/kyno/issues/new?template=question.yml)
and I'll answer there, so the next person finds it too.
