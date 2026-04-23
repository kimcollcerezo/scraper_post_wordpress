# Project Context — Scraper Post WordPress

## Identitat

- Nom: `Scraper Post WordPress`
- Slug: `scraper-post-wordpress`
- Tipus: `worker`
- Descripció: Agent per extreure posts de WordPress o altres CMS i poder inserir en projectes

## Normativa

- Global: `~/.claude/CLAUDE.md`
- Local: `CLAUDE.md`

## Stack

- Python · worker · agents-prod-01 · Docker local

## Ordre de precedència

1. codi real
2. `PROJECT_CONTEXT.md`
3. `CLAUDE.md` (projecte)
4. `~/.claude/CLAUDE.md` (global)
5. docs Redmine

## Carpetes clau

- `src/` — lògica principal
- `docs_custom/` — decisions i documentació
- `scripts/` — scripts auxiliars

## Zones crítiques

- Connexió APIs externes (WordPress REST API, altres CMS)
- Autenticació i credencials (`.env`)
- Inserció de dades (idempotència, deduplicació)
- Rate limiting / backoff

## Bootstrap operatiu

- `AGENT_BOOTSTRAP.md` — ordre de lectura per agents
- `codex-start.sh` — inici de sessió
- Iniciar sessions via `./codex-start.sh`

## Bones pràctiques (referència)

Consultar sota demanda a `~/.claude/project-templates/python/bones-practiques/`:

- Agents Python · Resiliència · Chaos testing

## Security baseline

- secrets fora de codi (`.env`)
- credencials mai hardcodejades
- fail closed en errors
- validació de dades externes

## Redmine

- Projecte: `agent-scrapper-post-wordpress-cms`

## Servidor

- Deploy: `agents-prod-01` (178.104.54.56)
- SSH: `deploy@178.104.54.56`

## Lifecycle

- Estat: actiu
