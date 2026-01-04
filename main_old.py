from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("LocalNotes+Postgres", host="0.0.0.0", port=8000)

# -----------------------------
# Notes file tools
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
NOTES_FILE = BASE_DIR / "notes.txt"

@mcp.tool()
def add_note(content: str) -> str:
    """Append one note line to notes.txt (normalized newline)."""
    note = (content or "").strip()
    if not note:
        return "Error: content is empty"

    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with NOTES_FILE.open("a", encoding="utf-8", newline="\n") as f:
        f.write(note + "\n")
    return f"OK: appended to {NOTES_FILE}"

@mcp.tool()
def read_notes(max_chars: int = 20000) -> str:
    """Read notes.txt (truncated to max_chars)."""
    if not NOTES_FILE.exists():
        return f"Error: file not found: {NOTES_FILE}"

    data = NOTES_FILE.read_text(encoding="utf-8")
    if len(data) > max_chars:
        return data[:max_chars] + f"\n\n[TRUNCATED: {max_chars} of {len(data)} chars]"
    return data


# -----------------------------
# Postgres connection setup
# -----------------------------
load_dotenv(BASE_DIR / ".env")

def _env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return v

# Prefer libpq-style vars
PGHOST = _env("PGHOST")
PGPORT = int(os.getenv("PGPORT", "5432"))
PGDATABASE = _env("PGDATABASE")
PGUSER = _env("PGUSER")
PGPASSWORD = _env("PGPASSWORD")
PGSSLMODE = os.getenv("PGSSLMODE", "prefer")

# Optional: limit dangerous tools
ENABLE_DANGEROUS = os.getenv("ENABLE_DANGEROUS", "false").lower() == "true"

# Pool for concurrency + performance
POOL = ConnectionPool(
    conninfo=f"host={PGHOST} port={PGPORT} dbname={PGDATABASE} user={PGUSER} password={PGPASSWORD} sslmode={PGSSLMODE}",
    min_size=1,
    max_size=5,
    kwargs={"row_factory": dict_row},
)

def _fetch_all(sql: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
    with POOL.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
            return list(rows)

def _fetch_one(sql: str, params: Optional[Tuple[Any, ...]] = None) -> Dict[str, Any]:
    with POOL.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            return dict(row) if row else {}

def _execute(sql: str, params: Optional[Tuple[Any, ...]] = None) -> str:
    """Execute a query and return status message."""
    with POOL.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            conn.commit()
            return f"OK: executed successfully, rows affected: {cur.rowcount}"

def _execute_autocommit(sql: str) -> str:
    """Execute a query with autocommit (for database operations)."""
    with POOL.connection() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
            return f"OK: executed successfully"


# -----------------------------
# Basic Postgres "admin" tools
# -----------------------------
@mcp.tool()
def pg_health() -> Dict[str, Any]:
    """Basic connectivity + identity check."""
    row = _fetch_one(
        """
        SELECT
          now()                           AS server_time,
          current_database()              AS database,
          current_user                    AS user,
          inet_server_addr()::text        AS server_ip,
          inet_server_port()              AS server_port,
          version()                       AS version
        """
    )
    return row

@mcp.tool()
def pg_list_schemas() -> List[Dict[str, Any]]:
    """List non-system schemas."""
    return _fetch_all(
        """
        SELECT nspname AS schema
        FROM pg_namespace
        WHERE nspname NOT IN ('pg_catalog','information_schema')
        ORDER BY 1
        """
    )

@mcp.tool()
def pg_list_tables(schema: str = "public") -> List[Dict[str, Any]]:
    """List tables in a schema."""
    schema = (schema or "public").strip()
    return _fetch_all(
        """
        SELECT tablename AS table
        FROM pg_catalog.pg_tables
        WHERE schemaname = %s
        ORDER BY 1
        """,
        (schema,),
    )

@mcp.tool()
def pg_describe_table(schema: str, table: str) -> List[Dict[str, Any]]:
    """Describe columns (name, type, nullable, default)."""
    schema = (schema or "").strip()
    table = (table or "").strip()
    if not schema or not table:
        return [{"error": "schema and table are required"}]

    return _fetch_all(
        """
        SELECT
          column_name,
          data_type,
          is_nullable,
          column_default
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )

@mcp.tool()
def pg_show_setting(name: str) -> Dict[str, Any]:
    """Show a single server setting."""
    name = (name or "").strip()
    if not name:
        return {"error": "setting name required"}
    return _fetch_one("SELECT name, setting, unit, context, source FROM pg_settings WHERE name = %s", (name,))


# -----------------------------
# Database Operations
# -----------------------------
@mcp.tool()
def pg_list_databases() -> List[Dict[str, Any]]:
    """List all non-template databases with size information."""
    return _fetch_all(
        """
        SELECT 
          datname AS database,
          pg_size_pretty(pg_database_size(datname)) AS size,
          pg_database_size(datname) AS size_bytes,
          (SELECT count(*) FROM pg_stat_activity WHERE datname = d.datname) AS connections
        FROM pg_database d
        WHERE datistemplate = false
        ORDER BY pg_database_size(datname) DESC
        """
    )

@mcp.tool()
def pg_database_stats(database: str = None) -> Dict[str, Any]:
    """Get detailed statistics for current or specified database."""
    db = database or PGDATABASE
    return _fetch_one(
        """
        SELECT 
          datname AS database,
          pg_size_pretty(pg_database_size(datname)) AS size,
          pg_database_size(datname) AS size_bytes,
          (SELECT count(*) FROM pg_stat_activity WHERE datname = d.datname) AS active_connections,
          datconnlimit AS connection_limit,
          age(datfrozenxid) AS transaction_age
        FROM pg_database d
        WHERE datname = %s
        """,
        (db,)
    )

@mcp.tool()
def pg_create_database(database: str, owner: str = None, encoding: str = "UTF8") -> str:
    """
    Create a new database.
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Database creation requires ENABLE_DANGEROUS=true in environment"
    
    database = (database or "").strip()
    if not database:
        return "Error: database name is required"
    
    # Validate database name (alphanumeric and underscore only)
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', database):
        return "Error: invalid database name (use alphanumeric and underscore only)"
    
    try:
        sql = f'CREATE DATABASE "{database}"'
        if owner:
            sql += f' OWNER "{owner}"'
        sql += f" ENCODING '{encoding}'"
        
        return _execute_autocommit(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_drop_database(database: str, force: bool = False) -> str:
    """
    Drop a database.
    Requires ENABLE_DANGEROUS=true in environment.
    Set force=true to terminate connections before dropping.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Database deletion requires ENABLE_DANGEROUS=true in environment"
    
    database = (database or "").strip()
    if not database:
        return "Error: database name is required"
    
    # Safety check - don't drop current database
    if database == PGDATABASE:
        return "Error: cannot drop the current database"
    
    try:
        if force:
            # Terminate all connections first
            _execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid != pg_backend_pid()
                """,
                (database,)
            )
        
        sql = f'DROP DATABASE "{database}"'
        return _execute_autocommit(sql)
    except Exception as e:
        return f"Error: {str(e)}"


# -----------------------------
# Schema Management
# -----------------------------
@mcp.tool()
def pg_create_schema(schema: str, authorization: str = None) -> str:
    """
    Create a new schema.
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Schema creation requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    if not schema:
        return "Error: schema name is required"
    
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', schema):
        return "Error: invalid schema name"
    
    try:
        sql = f'CREATE SCHEMA "{schema}"'
        if authorization:
            sql += f' AUTHORIZATION "{authorization}"'
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_drop_schema(schema: str, cascade: bool = False) -> str:
    """
    Drop a schema.
    Requires ENABLE_DANGEROUS=true in environment.
    Set cascade=true to drop all contained objects.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Schema deletion requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    if not schema:
        return "Error: schema name is required"
    
    # Safety check
    if schema in ('public', 'pg_catalog', 'information_schema'):
        return f"Error: cannot drop system schema '{schema}'"
    
    try:
        sql = f'DROP SCHEMA "{schema}"'
        if cascade:
            sql += ' CASCADE'
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"


# -----------------------------
# Table Operations & Statistics
# -----------------------------
@mcp.tool()
def pg_table_size(schema: str = "public", table: str = None) -> List[Dict[str, Any]]:
    """Get size information for tables in a schema."""
    schema = (schema or "public").strip()
    
    if table:
        table = table.strip()
        return _fetch_all(
            """
            SELECT
              schemaname AS schema,
              tablename AS table,
              pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
              pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
              pg_size_pretty(pg_indexes_size(schemaname||'.'||tablename)) AS indexes_size,
              pg_total_relation_size(schemaname||'.'||tablename) AS total_bytes
            FROM pg_tables
            WHERE schemaname = %s AND tablename = %s
            """,
            (schema, table)
        )
    else:
        return _fetch_all(
            """
            SELECT
              schemaname AS schema,
              tablename AS table,
              pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
              pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
              pg_size_pretty(pg_indexes_size(schemaname||'.'||tablename)) AS indexes_size,
              pg_total_relation_size(schemaname||'.'||tablename) AS total_bytes
            FROM pg_tables
            WHERE schemaname = %s
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            """,
            (schema,)
        )

@mcp.tool()
def pg_table_stats(schema: str, table: str) -> Dict[str, Any]:
    """Get detailed statistics for a specific table."""
    schema = (schema or "").strip()
    table = (table or "").strip()
    if not schema or not table:
        return {"error": "schema and table are required"}
    
    return _fetch_one(
        """
        SELECT
          schemaname AS schema,
          relname AS table,
          n_live_tup AS live_rows,
          n_dead_tup AS dead_rows,
          n_tup_ins AS inserts,
          n_tup_upd AS updates,
          n_tup_del AS deletes,
          last_vacuum,
          last_autovacuum,
          last_analyze,
          last_autoanalyze
        FROM pg_stat_user_tables
        WHERE schemaname = %s AND relname = %s
        """,
        (schema, table)
    )

@mcp.tool()
def pg_bloat_check(schema: str = "public") -> List[Dict[str, Any]]:
    """Check for table bloat in a schema."""
    schema = (schema or "public").strip()
    return _fetch_all(
        """
        SELECT
          schemaname AS schema,
          tablename AS table,
          pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
          n_dead_tup AS dead_rows,
          n_live_tup AS live_rows,
          ROUND(n_dead_tup * 100.0 / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_ratio
        FROM pg_stat_user_tables
        WHERE schemaname = %s AND n_dead_tup > 0
        ORDER BY n_dead_tup DESC
        LIMIT 20
        """,
        (schema,)
    )

@mcp.tool()
def pg_create_table(schema: str, table: str, columns: str) -> str:
    """
    Create a new table.
    Requires ENABLE_DANGEROUS=true in environment.
    
    Example columns: "id SERIAL PRIMARY KEY, name VARCHAR(100), created_at TIMESTAMP DEFAULT NOW()"
    """
    if not ENABLE_DANGEROUS:
        return "Error: Table creation requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    table = (table or "").strip()
    columns = (columns or "").strip()
    
    if not schema or not table or not columns:
        return "Error: schema, table, and columns are required"
    
    try:
        sql = f'CREATE TABLE "{schema}"."{table}" ({columns})'
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_drop_table(schema: str, table: str, cascade: bool = False) -> str:
    """
    Drop a table.
    Requires ENABLE_DANGEROUS=true in environment.
    Set cascade=true to drop dependent objects.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Table deletion requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    table = (table or "").strip()
    
    if not schema or not table:
        return "Error: schema and table are required"
    
    try:
        sql = f'DROP TABLE "{schema}"."{table}"'
        if cascade:
            sql += ' CASCADE'
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_alter_table(schema: str, table: str, alteration: str) -> str:
    """
    Alter a table.
    Requires ENABLE_DANGEROUS=true in environment.
    
    Example alterations:
    - "ADD COLUMN email VARCHAR(255)"
    - "DROP COLUMN old_field"
    - "RENAME COLUMN old_name TO new_name"
    - "ALTER COLUMN id TYPE BIGINT"
    """
    if not ENABLE_DANGEROUS:
        return "Error: Table alteration requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    table = (table or "").strip()
    alteration = (alteration or "").strip()
    
    if not schema or not table or not alteration:
        return "Error: schema, table, and alteration are required"
    
    try:
        sql = f'ALTER TABLE "{schema}"."{table}" {alteration}'
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_truncate_table(schema: str, table: str, cascade: bool = False, restart_identity: bool = False) -> str:
    """
    Truncate a table (remove all rows quickly).
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Table truncation requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    table = (table or "").strip()
    
    if not schema or not table:
        return "Error: schema and table are required"
    
    try:
        sql = f'TRUNCATE TABLE "{schema}"."{table}"'
        if restart_identity:
            sql += ' RESTART IDENTITY'
        if cascade:
            sql += ' CASCADE'
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"


# -----------------------------
# Index Operations
# -----------------------------
@mcp.tool()
def pg_list_indexes(schema: str, table: str = None) -> List[Dict[str, Any]]:
    """List indexes for a table or all tables in schema."""
    schema = (schema or "").strip()
    if not schema:
        return [{"error": "schema is required"}]
    
    if table:
        table = table.strip()
        return _fetch_all(
            """
            SELECT
              schemaname AS schema,
              tablename AS table,
              indexname AS index,
              indexdef AS definition
            FROM pg_indexes
            WHERE schemaname = %s AND tablename = %s
            ORDER BY tablename, indexname
            """,
            (schema, table)
        )
    else:
        return _fetch_all(
            """
            SELECT
              schemaname AS schema,
              tablename AS table,
              indexname AS index,
              indexdef AS definition
            FROM pg_indexes
            WHERE schemaname = %s
            ORDER BY tablename, indexname
            """,
            (schema,)
        )

@mcp.tool()
def pg_index_usage(schema: str = "public") -> List[Dict[str, Any]]:
    """Show index usage statistics."""
    schema = (schema or "public").strip()
    return _fetch_all(
        """
        SELECT
          schemaname AS schema,
          tablename AS table,
          indexname AS index,
          idx_scan AS scans,
          idx_tup_read AS rows_read,
          idx_tup_fetch AS rows_fetched,
          pg_size_pretty(pg_relation_size(indexrelid)) AS size
        FROM pg_stat_user_indexes
        WHERE schemaname = %s
        ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC
        """,
        (schema,)
    )

@mcp.tool()
def pg_unused_indexes(schema: str = "public") -> List[Dict[str, Any]]:
    """Find potentially unused indexes (0 scans)."""
    schema = (schema or "public").strip()
    return _fetch_all(
        """
        SELECT
          schemaname AS schema,
          tablename AS table,
          indexname AS index,
          pg_size_pretty(pg_relation_size(indexrelid)) AS size,
          idx_scan AS scans
        FROM pg_stat_user_indexes
        WHERE schemaname = %s 
          AND idx_scan = 0
          AND indexrelid::regclass::text NOT LIKE '%_pkey'
        ORDER BY pg_relation_size(indexrelid) DESC
        """,
        (schema,)
    )

@mcp.tool()
def pg_create_index(schema: str, table: str, index_name: str, columns: str, unique: bool = False, method: str = "btree") -> str:
    """
    Create an index.
    Requires ENABLE_DANGEROUS=true in environment.
    
    Example:
    - columns: "email"
    - columns: "lower(email)"
    - columns: "created_at DESC"
    - method: "btree", "hash", "gist", "gin", "brin"
    """
    if not ENABLE_DANGEROUS:
        return "Error: Index creation requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    table = (table or "").strip()
    index_name = (index_name or "").strip()
    columns = (columns or "").strip()
    
    if not all([schema, table, index_name, columns]):
        return "Error: schema, table, index_name, and columns are required"
    
    try:
        unique_clause = "UNIQUE " if unique else ""
        sql = f'CREATE {unique_clause}INDEX "{index_name}" ON "{schema}"."{table}" USING {method} ({columns})'
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_drop_index(schema: str, index_name: str, cascade: bool = False) -> str:
    """
    Drop an index.
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Index deletion requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    index_name = (index_name or "").strip()
    
    if not schema or not index_name:
        return "Error: schema and index_name are required"
    
    try:
        sql = f'DROP INDEX "{schema}"."{index_name}"'
        if cascade:
            sql += ' CASCADE'
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_reindex(schema: str, table: str = None, index: str = None) -> str:
    """
    Rebuild indexes.
    Requires ENABLE_DANGEROUS=true in environment.
    Specify either table (rebuilds all indexes) or index (rebuilds specific index).
    """
    if not ENABLE_DANGEROUS:
        return "Error: Reindexing requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    if not schema:
        return "Error: schema is required"
    
    try:
        if index:
            sql = f'REINDEX INDEX "{schema}"."{index}"'
        elif table:
            sql = f'REINDEX TABLE "{schema}"."{table}"'
        else:
            return "Error: either table or index must be specified"
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"


# -----------------------------
# Schema Introspection
# -----------------------------
@mcp.tool()
def pg_list_views(schema: str = "public") -> List[Dict[str, Any]]:
    """List views in a schema."""
    schema = (schema or "public").strip()
    return _fetch_all(
        """
        SELECT
          schemaname AS schema,
          viewname AS view,
          viewowner AS owner
        FROM pg_views
        WHERE schemaname = %s
        ORDER BY viewname
        """,
        (schema,)
    )

@mcp.tool()
def pg_view_definition(schema: str, view: str) -> Dict[str, Any]:
    """Get the SQL definition of a view."""
    schema = (schema or "").strip()
    view = (view or "").strip()
    if not schema or not view:
        return {"error": "schema and view are required"}
    
    return _fetch_one(
        """
        SELECT
          schemaname AS schema,
          viewname AS view,
          definition
        FROM pg_views
        WHERE schemaname = %s AND viewname = %s
        """,
        (schema, view)
    )

@mcp.tool()
def pg_list_functions(schema: str = "public") -> List[Dict[str, Any]]:
    """List functions/procedures in a schema."""
    schema = (schema or "public").strip()
    return _fetch_all(
        """
        SELECT
          n.nspname AS schema,
          p.proname AS function,
          pg_get_function_result(p.oid) AS returns,
          pg_get_function_arguments(p.oid) AS arguments,
          CASE p.prokind
            WHEN 'f' THEN 'function'
            WHEN 'p' THEN 'procedure'
            WHEN 'a' THEN 'aggregate'
            WHEN 'w' THEN 'window'
          END AS type
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = %s
        ORDER BY p.proname
        """,
        (schema,)
    )

@mcp.tool()
def pg_table_constraints(schema: str, table: str) -> List[Dict[str, Any]]:
    """List all constraints for a table (PK, FK, unique, check)."""
    schema = (schema or "").strip()
    table = (table or "").strip()
    if not schema or not table:
        return [{"error": "schema and table are required"}]
    
    return _fetch_all(
        """
        SELECT
          tc.constraint_name AS constraint,
          tc.constraint_type AS type,
          kcu.column_name AS column,
          ccu.table_schema AS foreign_schema,
          ccu.table_name AS foreign_table,
          ccu.column_name AS foreign_column
        FROM information_schema.table_constraints tc
        LEFT JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
          AND tc.table_schema = kcu.table_schema
        LEFT JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
          AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = %s AND tc.table_name = %s
        ORDER BY tc.constraint_type, tc.constraint_name
        """,
        (schema, table)
    )

@mcp.tool()
def pg_foreign_keys(schema: str = "public") -> List[Dict[str, Any]]:
    """List all foreign key relationships in a schema."""
    schema = (schema or "public").strip()
    return _fetch_all(
        """
        SELECT
          tc.table_schema AS schema,
          tc.table_name AS table,
          kcu.column_name AS column,
          ccu.table_schema AS foreign_schema,
          ccu.table_name AS foreign_table,
          ccu.column_name AS foreign_column,
          tc.constraint_name AS constraint
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
          AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
          AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s
        ORDER BY tc.table_name, kcu.column_name
        """,
        (schema,)
    )


# -----------------------------
# User & Permission Management
# -----------------------------
@mcp.tool()
def pg_list_users() -> List[Dict[str, Any]]:
    """List all database users/roles."""
    return _fetch_all(
        """
        SELECT
          rolname AS username,
          rolsuper AS is_superuser,
          rolinherit AS inherit_privileges,
          rolcreaterole AS can_create_roles,
          rolcreatedb AS can_create_db,
          rolcanlogin AS can_login,
          rolconnlimit AS connection_limit,
          rolvaliduntil AS valid_until
        FROM pg_roles
        ORDER BY rolname
        """
    )

@mcp.tool()
def pg_user_permissions(username: str) -> List[Dict[str, Any]]:
    """Show permissions for a specific user."""
    username = (username or "").strip()
    if not username:
        return [{"error": "username is required"}]
    
    return _fetch_all(
        """
        SELECT
          schemaname AS schema,
          tablename AS table,
          privilege_type
        FROM information_schema.table_privileges
        WHERE grantee = %s
        ORDER BY schemaname, tablename, privilege_type
        """,
        (username,)
    )

@mcp.tool()
def pg_table_permissions(schema: str, table: str) -> List[Dict[str, Any]]:
    """Show all permissions granted on a specific table."""
    schema = (schema or "").strip()
    table = (table or "").strip()
    if not schema or not table:
        return [{"error": "schema and table are required"}]
    
    return _fetch_all(
        """
        SELECT
          grantee AS user,
          privilege_type AS privilege,
          is_grantable
        FROM information_schema.table_privileges
        WHERE table_schema = %s AND table_name = %s
        ORDER BY grantee, privilege_type
        """,
        (schema, table)
    )

@mcp.tool()
def pg_create_user(username: str, password: str, superuser: bool = False, createdb: bool = False, 
                   createrole: bool = False, login: bool = True) -> str:
    """
    Create a new user/role.
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: User creation requires ENABLE_DANGEROUS=true in environment"
    
    username = (username or "").strip()
    if not username:
        return "Error: username is required"
    
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', username):
        return "Error: invalid username"
    
    try:
        options = []
        if superuser:
            options.append("SUPERUSER")
        if createdb:
            options.append("CREATEDB")
        if createrole:
            options.append("CREATEROLE")
        if login:
            options.append("LOGIN")
        
        options_str = " ".join(options)
        sql = f"CREATE USER \"{username}\" WITH {options_str} PASSWORD %s"
        
        return _execute(sql, (password,))
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_alter_user(username: str, password: str = None, superuser: bool = None, 
                  createdb: bool = None, createrole: bool = None, login: bool = None) -> str:
    """
    Alter user attributes.
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: User alteration requires ENABLE_DANGEROUS=true in environment"
    
    username = (username or "").strip()
    if not username:
        return "Error: username is required"
    
    try:
        alterations = []
        
        if password is not None:
            alterations.append(("PASSWORD %s", password))
        if superuser is not None:
            alterations.append((("SUPERUSER" if superuser else "NOSUPERUSER"), None))
        if createdb is not None:
            alterations.append((("CREATEDB" if createdb else "NOCREATEDB"), None))
        if createrole is not None:
            alterations.append((("CREATEROLE" if createrole else "NOCREATEROLE"), None))
        if login is not None:
            alterations.append((("LOGIN" if login else "NOLOGIN"), None))
        
        if not alterations:
            return "Error: no alterations specified"
        
        # Build SQL with parameters
        sql_parts = []
        params = []
        for alt, param in alterations:
            sql_parts.append(alt)
            if param is not None:
                params.append(param)
        
        sql = f"ALTER USER \"{username}\" WITH {' '.join(sql_parts)}"
        
        return _execute(sql, tuple(params) if params else None)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_drop_user(username: str) -> str:
    """
    Drop a user/role.
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: User deletion requires ENABLE_DANGEROUS=true in environment"
    
    username = (username or "").strip()
    if not username:
        return "Error: username is required"
    
    try:
        sql = f'DROP USER "{username}"'
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_grant_privileges(username: str, privileges: str, schema: str, table: str = None) -> str:
    """
    Grant privileges to a user.
    Requires ENABLE_DANGEROUS=true in environment.
    
    Examples:
    - privileges: "SELECT, INSERT, UPDATE"
    - privileges: "ALL PRIVILEGES"
    - table: specific table name, or None for all tables in schema
    """
    if not ENABLE_DANGEROUS:
        return "Error: Granting privileges requires ENABLE_DANGEROUS=true in environment"
    
    username = (username or "").strip()
    privileges = (privileges or "").strip()
    schema = (schema or "").strip()
    
    if not all([username, privileges, schema]):
        return "Error: username, privileges, and schema are required"
    
    try:
        if table:
            sql = f'GRANT {privileges} ON TABLE "{schema}"."{table}" TO "{username}"'
        else:
            sql = f'GRANT {privileges} ON ALL TABLES IN SCHEMA "{schema}" TO "{username}"'
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_revoke_privileges(username: str, privileges: str, schema: str, table: str = None) -> str:
    """
    Revoke privileges from a user.
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Revoking privileges requires ENABLE_DANGEROUS=true in environment"
    
    username = (username or "").strip()
    privileges = (privileges or "").strip()
    schema = (schema or "").strip()
    
    if not all([username, privileges, schema]):
        return "Error: username, privileges, and schema are required"
    
    try:
        if table:
            sql = f'REVOKE {privileges} ON TABLE "{schema}"."{table}" FROM "{username}"'
        else:
            sql = f'REVOKE {privileges} ON ALL TABLES IN SCHEMA "{schema}" FROM "{username}"'
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"


# -----------------------------
# Performance & Monitoring
# -----------------------------
@mcp.tool()
def pg_active_queries(include_idle: bool = False) -> List[Dict[str, Any]]:
    """Show currently running queries."""
    where_clause = "" if include_idle else "AND state != 'idle'"
    
    return _fetch_all(
        f"""
        SELECT
          pid,
          usename AS user,
          application_name AS application,
          client_addr AS client,
          state,
          query_start,
          state_change,
          wait_event_type,
          wait_event,
          LEFT(query, 200) AS query
        FROM pg_stat_activity
        WHERE pid != pg_backend_pid()
          {where_clause}
        ORDER BY query_start DESC
        LIMIT 50
        """
    )

@mcp.tool()
def pg_long_running_queries(min_seconds: int = 60) -> List[Dict[str, Any]]:
    """Find queries running longer than specified seconds."""
    return _fetch_all(
        """
        SELECT
          pid,
          usename AS user,
          application_name AS application,
          state,
          EXTRACT(EPOCH FROM (now() - query_start))::int AS duration_seconds,
          query_start,
          LEFT(query, 200) AS query
        FROM pg_stat_activity
        WHERE state = 'active'
          AND pid != pg_backend_pid()
          AND query_start < now() - interval '%s seconds'
        ORDER BY query_start
        """,
        (min_seconds,)
    )

@mcp.tool()
def pg_blocking_queries() -> List[Dict[str, Any]]:
    """Find queries that are blocking other queries."""
    return _fetch_all(
        """
        SELECT
          blocked_locks.pid AS blocked_pid,
          blocked_activity.usename AS blocked_user,
          blocking_locks.pid AS blocking_pid,
          blocking_activity.usename AS blocking_user,
          blocked_activity.query AS blocked_query,
          blocking_activity.query AS blocking_query,
          blocked_activity.state AS blocked_state,
          blocking_activity.state AS blocking_state
        FROM pg_catalog.pg_locks blocked_locks
        JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
        JOIN pg_catalog.pg_locks blocking_locks 
          ON blocking_locks.locktype = blocked_locks.locktype
          AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
          AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
          AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
          AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
          AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
          AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
          AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
          AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
          AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
          AND blocking_locks.pid != blocked_locks.pid
        JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
        WHERE NOT blocked_locks.granted
        """
    )

@mcp.tool()
def pg_connection_stats() -> Dict[str, Any]:
    """Get connection statistics."""
    return _fetch_one(
        """
        SELECT
          count(*) AS total_connections,
          count(*) FILTER (WHERE state = 'active') AS active,
          count(*) FILTER (WHERE state = 'idle') AS idle,
          count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction,
          max(EXTRACT(EPOCH FROM (now() - query_start))::int) AS longest_query_seconds
        FROM pg_stat_activity
        WHERE pid != pg_backend_pid()
        """
    )

@mcp.tool()
def pg_locks_summary() -> List[Dict[str, Any]]:
    """Get summary of current locks."""
    return _fetch_all(
        """
        SELECT
          locktype,
          mode,
          count(*) AS count
        FROM pg_locks
        GROUP BY locktype, mode
        ORDER BY count DESC
        """
    )

@mcp.tool()
def pg_cache_hit_ratio() -> Dict[str, Any]:
    """Show cache hit ratio for the database."""
    return _fetch_one(
        """
        SELECT
          sum(heap_blks_read) AS heap_read,
          sum(heap_blks_hit) AS heap_hit,
          ROUND(sum(heap_blks_hit) * 100.0 / NULLIF(sum(heap_blks_hit) + sum(heap_blks_read), 0), 2) AS cache_hit_ratio
        FROM pg_statio_user_tables
        """
    )

@mcp.tool()
def pg_slowest_queries(limit: int = 20) -> List[Dict[str, Any]]:
    """Get slowest queries from pg_stat_statements (if extension is enabled)."""
    return _fetch_all(
        """
        SELECT
          LEFT(query, 200) AS query,
          calls,
          ROUND(total_exec_time::numeric, 2) AS total_time_ms,
          ROUND(mean_exec_time::numeric, 2) AS mean_time_ms,
          ROUND(max_exec_time::numeric, 2) AS max_time_ms,
          rows AS total_rows
        FROM pg_stat_statements
        ORDER BY total_exec_time DESC
        LIMIT %s
        """,
        (limit,)
    )

@mcp.tool()
def pg_kill_query(pid: int) -> str:
    """
    Terminate a running query by its PID.
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Killing queries requires ENABLE_DANGEROUS=true in environment"
    
    if not pid:
        return "Error: pid is required"
    
    try:
        result = _fetch_one("SELECT pg_terminate_backend(%s) AS terminated", (pid,))
        if result.get('terminated'):
            return f"OK: terminated query with PID {pid}"
        else:
            return f"Error: could not terminate query with PID {pid}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_cancel_query(pid: int) -> str:
    """
    Cancel a running query by its PID (gentler than kill).
    Requires ENABLE_DANGEROUS=true in environment.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Canceling queries requires ENABLE_DANGEROUS=true in environment"
    
    if not pid:
        return "Error: pid is required"
    
    try:
        result = _fetch_one("SELECT pg_cancel_backend(%s) AS cancelled", (pid,))
        if result.get('cancelled'):
            return f"OK: cancelled query with PID {pid}"
        else:
            return f"Error: could not cancel query with PID {pid}"
    except Exception as e:
        return f"Error: {str(e)}"


# -----------------------------
# Maintenance Operations
# -----------------------------
@mcp.tool()
def pg_vacuum_stats() -> List[Dict[str, Any]]:
    """Show when tables were last vacuumed and analyzed."""
    return _fetch_all(
        """
        SELECT
          schemaname AS schema,
          relname AS table,
          last_vacuum,
          last_autovacuum,
          last_analyze,
          last_autoanalyze,
          n_dead_tup AS dead_rows,
          n_live_tup AS live_rows
        FROM pg_stat_user_tables
        ORDER BY last_autovacuum NULLS FIRST, n_dead_tup DESC
        LIMIT 50
        """
    )

@mcp.tool()
def pg_vacuum_table(schema: str, table: str, full: bool = False, analyze: bool = True) -> str:
    """
    Vacuum a table to reclaim space and update statistics.
    Requires ENABLE_DANGEROUS=true in environment.
    Set full=true for VACUUM FULL (locks table, reclaims more space).
    """
    if not ENABLE_DANGEROUS:
        return "Error: Vacuum operations require ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    table = (table or "").strip()
    
    if not schema or not table:
        return "Error: schema and table are required"
    
    try:
        full_clause = "FULL " if full else ""
        analyze_clause = "ANALYZE " if analyze else ""
        sql = f'VACUUM {full_clause}{analyze_clause}"{schema}"."{table}"'
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_analyze_table(schema: str, table: str = None) -> str:
    """
    Analyze table(s) to update statistics for query planner.
    Requires ENABLE_DANGEROUS=true in environment.
    If table is None, analyzes all tables in schema.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Analyze operations require ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    if not schema:
        return "Error: schema is required"
    
    try:
        if table:
            sql = f'ANALYZE "{schema}"."{table}"'
        else:
            # Analyze all tables in schema
            tables = pg_list_tables(schema)
            for t in tables:
                _execute(f'ANALYZE "{schema}"."{t["table"]}"')
            return f"OK: analyzed {len(tables)} tables in schema {schema}"
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_replication_status() -> List[Dict[str, Any]]:
    """Show replication status (if replication is configured)."""
    return _fetch_all(
        """
        SELECT
          client_addr,
          state,
          sync_state,
          replay_lag,
          write_lag,
          flush_lag
        FROM pg_stat_replication
        """
    )


# -----------------------------
# Data Manipulation (DML)
# -----------------------------
@mcp.tool()
def pg_insert_data(schema: str, table: str, columns: str, values: str) -> str:
    """
    Insert data into a table.
    Requires ENABLE_DANGEROUS=true in environment.
    
    Example:
    - columns: "name, email, age"
    - values: "'John Doe', 'john@example.com', 30"
    """
    if not ENABLE_DANGEROUS:
        return "Error: Data insertion requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    table = (table or "").strip()
    columns = (columns or "").strip()
    values = (values or "").strip()
    
    if not all([schema, table, columns, values]):
        return "Error: schema, table, columns, and values are required"
    
    try:
        sql = f'INSERT INTO "{schema}"."{table}" ({columns}) VALUES ({values})'
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_update_data(schema: str, table: str, set_clause: str, where_clause: str = None) -> str:
    """
    Update data in a table.
    Requires ENABLE_DANGEROUS=true in environment.
    
    Example:
    - set_clause: "status = 'active', updated_at = NOW()"
    - where_clause: "id = 123" (optional, but recommended to avoid updating all rows)
    """
    if not ENABLE_DANGEROUS:
        return "Error: Data updates require ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    table = (table or "").strip()
    set_clause = (set_clause or "").strip()
    
    if not all([schema, table, set_clause]):
        return "Error: schema, table, and set_clause are required"
    
    try:
        sql = f'UPDATE "{schema}"."{table}" SET {set_clause}'
        if where_clause:
            sql += f' WHERE {where_clause}'
        
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_delete_data(schema: str, table: str, where_clause: str) -> str:
    """
    Delete data from a table.
    Requires ENABLE_DANGEROUS=true in environment.
    
    IMPORTANT: where_clause is REQUIRED to prevent accidental deletion of all rows.
    Use pg_truncate_table if you want to delete all rows.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Data deletion requires ENABLE_DANGEROUS=true in environment"
    
    schema = (schema or "").strip()
    table = (table or "").strip()
    where_clause = (where_clause or "").strip()
    
    if not all([schema, table, where_clause]):
        return "Error: schema, table, and where_clause are required (use pg_truncate_table to delete all rows)"
    
    try:
        sql = f'DELETE FROM "{schema}"."{table}" WHERE {where_clause}'
        return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"


# -----------------------------
# Safe Query Execution
# -----------------------------
_DISALLOWED = re.compile(
    r"\b(?:insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|copy|call|do|execute|vacuum|analyze|reindex)\b",
    re.IGNORECASE,
)

@mcp.tool()
def pg_query(sql: str, max_rows: int = 1000) -> List[Dict[str, Any]]:
    """
    Execute a SELECT query safely (read-only).
    Blocks any DML/DDL operations for safety.
    """
    sql = (sql or "").strip()
    if not sql:
        return [{"error": "SQL query is required"}]
    
    # Safety check
    if _DISALLOWED.search(sql):
        return [{"error": "Only SELECT queries are allowed. DML/DDL operations are blocked. Use specific admin tools instead."}]
    
    # Ensure it starts with SELECT
    if not sql.upper().startswith("SELECT"):
        return [{"error": "Query must start with SELECT"}]
    
    try:
        # Add LIMIT if not present
        if "limit" not in sql.lower():
            sql = f"{sql} LIMIT {max_rows}"
        
        results = _fetch_all(sql)
        return results if results else [{"message": "Query executed successfully but returned no rows"}]
    except Exception as e:
        return [{"error": f"Query execution failed: {str(e)}"}]

@mcp.tool()
def pg_execute_sql(sql: str) -> str:
    """
    Execute arbitrary SQL (DML/DDL).
    Requires ENABLE_DANGEROUS=true in environment.
    
    WARNING: Use with extreme caution. Prefer specific admin tools when available.
    """
    if not ENABLE_DANGEROUS:
        return "Error: Direct SQL execution requires ENABLE_DANGEROUS=true in environment"
    
    sql = (sql or "").strip()
    if not sql:
        return "Error: SQL is required"
    
    try:
        # Check if it's a database-level operation that needs autocommit
        if re.search(r'\b(CREATE|DROP)\s+DATABASE\b', sql, re.IGNORECASE):
            return _execute_autocommit(sql)
        else:
            return _execute(sql)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_explain_query(sql: str, analyze: bool = False) -> List[Dict[str, Any]]:
    """
    Get query execution plan using EXPLAIN.
    Set analyze=True to run EXPLAIN ANALYZE (actually executes the query).
    """
    sql = (sql or "").strip()
    if not sql:
        return [{"error": "SQL query is required"}]
    
    # Safety check for EXPLAIN ANALYZE
    if analyze and _DISALLOWED.search(sql):
        return [{"error": "EXPLAIN ANALYZE cannot be used with DML/DDL operations"}]
    
    try:
        explain_sql = f"EXPLAIN (FORMAT JSON, ANALYZE {analyze}, BUFFERS, VERBOSE) {sql}"
        result = _fetch_all(explain_sql)
        return result
    except Exception as e:
        return [{"error": f"EXPLAIN failed: {str(e)}"}]


# -----------------------------
# Export Operations
# -----------------------------
@mcp.tool()
def pg_export_table_csv(schema: str, table: str, limit: int = 10000) -> str:
    """Export table data as CSV format (limited rows for safety)."""
    schema = (schema or "").strip()
    table = (table or "").strip()
    if not schema or not table:
        return "Error: schema and table are required"
    
    try:
        rows = _fetch_all(f'SELECT * FROM "{schema}"."{table}" LIMIT %s', (limit,))
        if not rows:
            return "No data found"
        
        # Convert to CSV format
        import io
        import csv
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        
        return output.getvalue()
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def pg_backup_table_sql(schema: str, table: str) -> str:
    """
    Generate SQL dump of a table (structure + data).
    Returns SQL commands to recreate the table.
    """
    schema = (schema or "").strip()
    table = (table or "").strip()
    if not schema or not table:
        return "Error: schema and table are required"
    
    try:
        # Get table structure
        columns = pg_describe_table(schema, table)
        
        # Get constraints
        constraints = pg_table_constraints(schema, table)
        
        # Get data
        rows = _fetch_all(f'SELECT * FROM "{schema}"."{table}"')
        
        # Build CREATE TABLE statement
        col_defs = []
        for col in columns:
            col_def = f'  "{col["column_name"]}" {col["data_type"]}'
            if col["is_nullable"] == "NO":
                col_def += " NOT NULL"
            if col["column_default"]:
                col_def += f" DEFAULT {col['column_default']}"
            col_defs.append(col_def)
        
        create_sql = f'CREATE TABLE "{schema}"."{table}" (\n'
        create_sql += ",\n".join(col_defs)
        create_sql += "\n);\n\n"
        
        # Build INSERT statements
        insert_sqls = []
        if rows:
            for row in rows:
                values = []
                for v in row.values():
                    if v is None:
                        values.append("NULL")
                    elif isinstance(v, str):
                        values.append(f"'{v.replace("'", "''")}'")
                    else:
                        values.append(str(v))
                
                cols = '", "'.join(row.keys())
                vals = ", ".join(values)
                insert_sqls.append(f'INSERT INTO "{schema}"."{table}" ("{cols}") VALUES ({vals});')
        
        return create_sql + "\n".join(insert_sqls)
    except Exception as e:
        return f"Error: {str(e)}"


# -----------------------------
# System Information
# -----------------------------
@mcp.tool()
def pg_server_settings(pattern: str = "") -> List[Dict[str, Any]]:
    """List server settings, optionally filtered by pattern."""
    pattern = (pattern or "").strip()
    
    if pattern:
        return _fetch_all(
            """
            SELECT name, setting, unit, category, short_desc
            FROM pg_settings
            WHERE name ILIKE %s
            ORDER BY name
            """,
            (f"%{pattern}%",)
        )
    else:
        return _fetch_all(
            """
            SELECT name, setting, unit, category, short_desc
            FROM pg_settings
            ORDER BY category, name
            LIMIT 100
            """
        )

@mcp.tool()
def pg_extensions() -> List[Dict[str, Any]]:
    """List installed extensions."""
    return _fetch_all(
        """
        SELECT
          extname AS extension,
          extversion AS version,
          nspname AS schema,
          extrelocatable AS relocatable,
          extconfig::text AS configuration
        FROM pg_extension e
        JOIN pg_namespace n ON e.extnamespace = n.oid
        ORDER BY extname
        """
    )

@mcp.tool()
def pg_tablespaces() -> List[Dict[str, Any]]:
    """List available tablespaces."""
    return _fetch_all(
        """
        SELECT
          spcname AS tablespace,
          pg_tablespace_location(oid) AS location,
          pg_size_pretty(pg_tablespace_size(spcname)) AS size
        FROM pg_tablespace
        ORDER BY spcname
        """
    )

@mcp.tool()
def pg_database_activity_summary() -> Dict[str, Any]:
    """Get overall database activity summary."""
    return _fetch_one(
        """
        SELECT
          (SELECT count(*) FROM pg_stat_activity) AS total_connections,
          (SELECT count(*) FROM pg_stat_activity WHERE state = 'active') AS active_queries,
          (SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction') AS idle_in_transaction,
          (SELECT pg_size_pretty(pg_database_size(current_database()))) AS database_size,
          (SELECT count(*) FROM pg_stat_user_tables) AS total_tables,
          (SELECT sum(n_live_tup) FROM pg_stat_user_tables) AS total_rows,
          (SELECT sum(n_dead_tup) FROM pg_stat_user_tables) AS dead_rows
        """
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")