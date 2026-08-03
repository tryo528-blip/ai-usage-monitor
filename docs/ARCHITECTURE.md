# Architecture Overview

AI Usage Monitor follows a layered design:

1. PySide6 UI shell and provider cards
2. CollectorManager with worker-based refresh orchestration
3. Official API and local bridge collectors
4. SQLite snapshot persistence and keyring-backed secret storage
