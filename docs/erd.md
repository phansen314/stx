# Entity-Relationship Diagram

> **v2 (legacy).** ERD of the Python app's workspace→group→task schema. The v3 Kotlin daemon uses a different model — see [v3-architecture.md](v3-architecture.md) for the v3 ERD.

```mermaid
erDiagram
    workspaces ||--o{ statuses : ""
    workspaces ||--o{ groups : ""
    groups ||--o{ groups : "parent_id"
    statuses ||--o{ tasks : ""
    workspaces ||--o{ tasks : ""
    groups ||--o{ tasks : ""
    workspaces ||--o{ edges : ""
    workspaces ||--o{ journal : ""

    workspaces {
        INTEGER id PK
        TEXT name
        INTEGER archived
        INTEGER created_at
        TEXT metadata
        INTEGER version
    }

    statuses {
        INTEGER id PK
        INTEGER workspace_id FK
        TEXT name
        INTEGER archived
        INTEGER created_at
        INTEGER is_terminal
        INTEGER version
    }

    groups {
        INTEGER id PK
        INTEGER workspace_id FK
        INTEGER parent_id FK
        TEXT title
        TEXT description
        INTEGER archived
        INTEGER created_at
        TEXT metadata
        INTEGER done
        INTEGER version
    }

    tasks {
        INTEGER id PK
        INTEGER workspace_id FK
        TEXT title
        TEXT description
        INTEGER status_id FK
        INTEGER priority
        INTEGER due_date
        INTEGER archived
        INTEGER created_at
        INTEGER start_date
        INTEGER finish_date
        INTEGER group_id FK
        TEXT metadata
        INTEGER done
        INTEGER version
    }

    edges {
        TEXT from_type PK "task|group|workspace|status"
        INTEGER from_id PK
        TEXT to_type PK "task|group|workspace|status"
        INTEGER to_id PK
        TEXT kind PK
        INTEGER workspace_id FK
        INTEGER acyclic
        TEXT metadata
        INTEGER archived
        INTEGER version
    }

    journal {
        INTEGER id PK
        TEXT entity_type
        INTEGER entity_id
        INTEGER workspace_id FK
        TEXT field
        TEXT old_value
        TEXT new_value
        TEXT source
        INTEGER changed_at
    }
```
