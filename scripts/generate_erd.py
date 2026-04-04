"""Generate a Mermaid ER diagram from schema.sql."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "src" / "sticky_notes" / "schema.sql"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "erd.md"

# Patterns
TABLE_RE = re.compile(
    r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);", re.DOTALL
)
COL_RE = re.compile(
    r"^\s+(\w+)\s+(INTEGER|TEXT|REAL|BLOB)\b(.*)", re.MULTILINE
)
FK_RE = re.compile(r"REFERENCES\s+(\w+)\s*\(\s*(\w+)\s*\)")
PK_RE = re.compile(r"PRIMARY KEY")
UNIQUE_RE = re.compile(r"\bUNIQUE\b")

# Composite PK pattern (for junction tables)
COMPOSITE_PK_RE = re.compile(
    r"PRIMARY KEY\s*\(\s*([\w\s,]+)\s*\)", re.MULTILINE
)

# Table-level FOREIGN KEY pattern
TABLE_FK_RE = re.compile(
    r"FOREIGN KEY\s*\(\s*([\w\s,]+)\s*\)\s*REFERENCES\s+(\w+)\s*\(\s*([\w\s,]+)\s*\)"
    r"(?:\s*ON DELETE\s+(CASCADE|RESTRICT|SET NULL))?",
    re.MULTILINE,
)


def parse_schema(sql: str) -> list[dict]:
    tables = []
    for match in TABLE_RE.finditer(sql):
        table_name = match.group(1)
        body = match.group(2)
        columns = []
        fk_rels = []

        # Find composite PK columns
        composite_pk_cols: set[str] = set()
        for cpk in COMPOSITE_PK_RE.finditer(body):
            composite_pk_cols.update(
                c.strip() for c in cpk.group(1).split(",")
            )

        # Collect FK columns from table-level FOREIGN KEY clauses
        table_fk_cols: set[str] = set()
        for tfk in TABLE_FK_RE.finditer(body):
            child_cols = [c.strip() for c in tfk.group(1).split(",")]
            ref_table = tfk.group(2)
            for col in child_cols:
                table_fk_cols.add(col)
            # Use first column for the relationship line
            fk_rels.append((child_cols[0], ref_table, ""))

        for col_match in COL_RE.finditer(body):
            col_name = col_match.group(1)
            col_type = col_match.group(2)
            rest = col_match.group(3)

            is_pk = PK_RE.search(rest) or col_name in composite_pk_cols
            is_fk = col_name in table_fk_cols

            # Inline REFERENCES (simple single-column FKs)
            fk_match = FK_RE.search(rest)
            if fk_match:
                is_fk = True
                fk_rels.append((col_name, fk_match.group(1), fk_match.group(2)))

            is_uk = UNIQUE_RE.search(rest) and not is_pk

            # Mermaid allows only one marker; prefer FK for composite PK+FK
            # columns (relationship is more informative than PK in ERD),
            # otherwise PK > FK > UK
            if is_pk and is_fk:
                marker = "FK"
                comment = "PK"
            elif is_pk:
                marker = "PK"
                comment = ""
            elif is_fk:
                marker = "FK"
                comment = ""
            elif is_uk:
                marker = "UK"
                comment = ""
            else:
                marker = ""
                comment = ""

            columns.append((col_type, col_name, marker, comment))

        # Deduplicate relationship lines (composite FKs may add duplicates)
        seen: set[tuple[str, str]] = set()
        unique_rels = []
        for rel in fk_rels:
            key = (rel[0], rel[1])
            if key not in seen:
                seen.add(key)
                unique_rels.append(rel)

        tables.append(
            {"name": table_name, "columns": columns, "fk_rels": unique_rels}
        )
    return tables


def build_mermaid(tables: list[dict]) -> str:
    lines = ["erDiagram"]

    # Relationships
    for table in tables:
        for _col, ref_table, _ref_col in table["fk_rels"]:
            lines.append(f"    {ref_table} ||--o{{ {table['name']} : \"\"")

    lines.append("")

    # Entities
    for table in tables:
        lines.append(f"    {table['name']} {{")
        for col_type, col_name, marker, comment in table["columns"]:
            entry = f"        {col_type} {col_name}"
            if marker:
                entry += f" {marker}"
            if comment:
                entry += f' "{comment}"'
            lines.append(entry)
        lines.append("    }")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    schema_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SCHEMA_PATH
    sql = schema_path.read_text()
    tables = parse_schema(sql)
    mermaid = build_mermaid(tables)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(f"```mermaid\n{mermaid}\n```\n")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
