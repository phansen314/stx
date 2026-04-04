```mermaid
erDiagram
    boards ||--o{ projects : ""
    boards ||--o{ columns : ""
    projects ||--o{ groups : ""
    groups |o--o{ groups : ""
    columns ||--o{ tasks : ""
    projects |o--o{ tasks : ""
    boards ||--o{ tasks : ""
    groups |o--o{ tasks : ""
    tasks ||--o{ task_dependencies : ""
    tasks ||--o{ task_dependencies : ""
    boards ||--o{ tags : ""
    tasks ||--o{ task_tags : ""
    tags ||--o{ task_tags : ""
    tasks ||--o{ task_history : ""

    boards {
        INTEGER id PK
        TEXT name
        INTEGER archived
        INTEGER created_at
    }

    projects {
        INTEGER id PK
        INTEGER board_id FK
        TEXT name
        TEXT description
        INTEGER archived
        INTEGER created_at
    }

    columns {
        INTEGER id PK
        INTEGER board_id FK
        TEXT name
        INTEGER position
        INTEGER archived
        INTEGER created_at
    }

    groups {
        INTEGER id PK
        INTEGER project_id FK
        INTEGER parent_id FK
        TEXT title
        INTEGER position
        INTEGER archived
        INTEGER created_at
    }

    tasks {
        INTEGER id PK
        INTEGER board_id FK
        INTEGER project_id FK
        TEXT title
        TEXT description
        INTEGER column_id FK
        INTEGER priority
        INTEGER due_date
        INTEGER position
        INTEGER archived
        INTEGER created_at
        INTEGER start_date
        INTEGER finish_date
        INTEGER group_id FK
    }

    task_dependencies {
        INTEGER task_id FK "PK"
        INTEGER depends_on_id FK "PK"
        INTEGER board_id FK
    }

    tags {
        INTEGER id PK
        INTEGER board_id FK
        TEXT name
        INTEGER archived
        INTEGER created_at
    }

    task_tags {
        INTEGER task_id FK "PK"
        INTEGER tag_id FK "PK"
        INTEGER board_id FK
    }

    task_history {
        INTEGER id PK
        INTEGER task_id FK
        TEXT field
        TEXT old_value
        TEXT new_value
        TEXT source
        INTEGER changed_at
    }

```
