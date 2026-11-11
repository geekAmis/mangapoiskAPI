# Roadmap

## 1.0.0 (released)

- [x] Microservices + shared contracts
- [x] MangaPoisk adapter end-to-end
- [x] React web + Android Compose clients
- [x] Library, progress, bookmarks
- [x] CBZ/PDF/HTML exports
- [x] Six themes and responsive design
- [x] Docker Compose, CI, docs

## 1.1

- [ ] Alembic migrations and zero-downtime upgrade path
- [ ] Redis-backed rate limiting and response cache
- [ ] S3-compatible storage for media/exports
- [ ] Full-text search with PostgreSQL `tsvector` + `pg_trgm`
- [ ] More verified sources (MangaLib pages, MangaDex)
- [ ] Web push notifications
- [ ] Reader bookmarks (per page), reading lists
- [ ] Import by URL from the UI

## 1.2

- [ ] Offline Android downloads with WorkManager + Room
- [ ] Sync progress between web and Android in real time
- [ ] Comments/reactions (moderated, optional)
- [ ] Admin panel for source health and featured titles
- [ ] Prometheus metrics + Grafana dashboard
- [ ] OpenAPI client generation for Kotlin/TypeScript

## Ideas

- Recommendation engine based on genres/history.
- Public read-only catalogue API without rate limits for small clients.
- EPUB export for novels.
- Discord/Telegram bot commands.
