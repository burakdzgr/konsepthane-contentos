\# Konsepthane ContentOS - Agent Memory Protocol



This repository uses two complementary memory systems:



1\. Codebase Memory MCP for structural/code intelligence.

2\. Repository documentation for persistent product, architecture and project memory.



\## Session startup rule



At the beginning of every coding session:



1\. Read `docs/memory/CURRENT\_STATE.md`.

2\. Read `docs/memory/PROJECT\_MEMORY.md`.

3\. Read only the documentation directly relevant to the current task.

4\. Use Codebase Memory MCP to inspect architecture, symbols, dependencies and impact.

5\. Do NOT scan the entire repository file-by-file unless Codebase Memory cannot answer the question.



\## Code exploration rule



Before using broad grep, recursive file reads or full repository scans:



\- query Codebase Memory MCP first;

\- inspect architecture or relevant symbols;

\- read only the files needed for the task.



The goal is to avoid repeatedly rediscovering the codebase and wasting context.



\## Persistent memory rule



Important product or engineering knowledge must not live only in chat history.



Persist important knowledge in the repository.



Use:



\- `docs/PROJECT.md`

&#x20; Product purpose, scope and system boundaries.



\- `docs/ARCHITECTURE.md`

&#x20; Current high-level technical architecture.



\- `docs/WORKFLOW.md`

&#x20; Editorial and system workflows.



\- `docs/EDITORIAL\_POLICY.md`

&#x20; Content quality, research, copyright and publishing rules.



\- `docs/memory/PROJECT\_MEMORY.md`

&#x20; Stable facts and decisions that future agents must remember.



\- `docs/memory/CURRENT\_STATE.md`

&#x20; Current implementation status, active phase, known blockers and next work.



\- `docs/memory/GLOSSARY.md`

&#x20; Project-specific terms and definitions.



\- `docs/adr/`

&#x20; Architecture Decision Records for important technical decisions.



\## ADR rule



Create an ADR when making an important decision that would otherwise be

questioned or rediscovered later.



Examples:



\- database choice

\- queue technology

\- AI provider abstraction

\- publishing API boundary

\- authentication model

\- auto-publish governance

\- crawler architecture



Do not create ADRs for trivial implementation details.



\## End-of-task memory update



After meaningful work:



1\. Update `docs/memory/CURRENT\_STATE.md`.

2\. Update `docs/memory/PROJECT\_MEMORY.md` only if a durable fact or decision changed.

3\. Create/update ADRs when an architectural decision was made.

4\. Update architecture/workflow docs when implementation changes them.

5\. Ensure documentation reflects reality before declaring the task complete.



\## Important principles



\- Documentation must reflect the implemented system, not imagined future code.

\- Do not duplicate the same information across many files unnecessarily.

\- Keep CURRENT\_STATE concise and operational.

\- Keep PROJECT\_MEMORY stable and durable.

\- Prefer querying Codebase Memory over rereading large portions of the repository.

\- Never assume chat history will be available in the next session.

