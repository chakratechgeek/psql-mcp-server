# PostgreSQL Admin MCP Server - Complete Edition

Complete PostgreSQL administration toolkit with comprehensive admin capabilities for database management, user management, maintenance operations, and more.

## 🔒 Safety Features

### ENABLE_DANGEROUS Flag
All write operations (CREATE, ALTER, DROP, INSERT, UPDATE, DELETE, GRANT, REVOKE, etc.) are protected by the `ENABLE_DANGEROUS` environment variable:

```bash
# In your .env file
ENABLE_DANGEROUS=true  # Enable admin write operations
ENABLE_DANGEROUS=false # Disable admin write operations (read-only)
```

**Default**: `false` (read-only mode for safety)

### Error Handling
- All tools include comprehensive error handling
- SQL syntax errors are caught and returned with details
- Invalid operations are blocked with clear error messages
- Connection errors are handled gracefully

## 📋 Complete Tool Reference

### 🗄️ Database Management

#### Read Operations (Always Available)
- **pg_list_databases()** - List all databases with sizes and connections
- **pg_database_stats(database)** - Detailed stats for a database
- **pg_database_activity_summary()** - Overall database activity summary

#### Write Operations (Requires ENABLE_DANGEROUS=true)
- **pg_create_database(database, owner?, encoding?)** - Create new database
  ```python
  # Example: Create database with UTF8 encoding
  pg_create_database("myapp_prod", owner="app_user", encoding="UTF8")
  ```

- **pg_drop_database(database, force?)** - Drop database
  ```python
  # Example: Force drop (terminates connections first)
  pg_drop_database("old_database", force=True)
  ```

### 📁 Schema Management

#### Read Operations
- **pg_list_schemas()** - List all non-system schemas

#### Write Operations (Requires ENABLE_DANGEROUS=true)
- **pg_create_schema(schema, authorization?)** - Create schema
- **pg_drop_schema(schema, cascade?)** - Drop schema and optionally all contents

### 📊 Table Operations

#### Read Operations
- **pg_list_tables(schema)** - List tables in schema
- **pg_describe_table(schema, table)** - Column details
- **pg_table_size(schema, table?)** - Size information
- **pg_table_stats(schema, table)** - Detailed statistics
- **pg_bloat_check(schema)** - Check for table bloat
- **pg_table_constraints(schema, table)** - List all constraints
- **pg_foreign_keys(schema)** - List foreign key relationships

#### Write Operations (Requires ENABLE_DANGEROUS=true)
- **pg_create_table(schema, table, columns)** - Create table
  ```python
  # Example: Create users table
  pg_create_table(
      schema="public",
      table="users",
      columns="id SERIAL PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL, created_at TIMESTAMP DEFAULT NOW()"
  )
  ```

- **pg_alter_table(schema, table, alteration)** - Alter table
  ```python
  # Examples of alterations:
  pg_alter_table("public", "users", "ADD COLUMN phone VARCHAR(20)")
  pg_alter_table("public", "users", "DROP COLUMN old_field")
  pg_alter_table("public", "users", "RENAME COLUMN name TO full_name")
  pg_alter_table("public", "users", "ALTER COLUMN id TYPE BIGINT")
  ```

- **pg_drop_table(schema, table, cascade?)** - Drop table
- **pg_truncate_table(schema, table, cascade?, restart_identity?)** - Remove all rows

### 🔍 Index Management

#### Read Operations
- **pg_list_indexes(schema, table?)** - List indexes
- **pg_index_usage(schema)** - Index usage statistics
- **pg_unused_indexes(schema)** - Find unused indexes (0 scans)

#### Write Operations (Requires ENABLE_DANGEROUS=true)
- **pg_create_index(schema, table, index_name, columns, unique?, method?)** - Create index
  ```python
  # Examples:
  pg_create_index("public", "users", "idx_users_email", "email", unique=True)
  pg_create_index("public", "users", "idx_users_name_lower", "lower(name)")
  pg_create_index("public", "logs", "idx_logs_created", "created_at DESC", method="btree")
  ```

- **pg_drop_index(schema, index_name, cascade?)** - Drop index
- **pg_reindex(schema, table?, index?)** - Rebuild indexes

### 👥 User & Permission Management

#### Read Operations
- **pg_list_users()** - List all users/roles
- **pg_user_permissions(username)** - Show user's permissions
- **pg_table_permissions(schema, table)** - Show table permissions

#### Write Operations (Requires ENABLE_DANGEROUS=true)
- **pg_create_user(username, password, superuser?, createdb?, createrole?, login?)** - Create user
  ```python
  # Example: Create app user with database creation privilege
  pg_create_user(
      username="app_user",
      password="secure_password_here",
      createdb=True,
      login=True
  )
  ```

- **pg_alter_user(username, password?, superuser?, createdb?, createrole?, login?)** - Modify user
- **pg_drop_user(username)** - Drop user
- **pg_grant_privileges(username, privileges, schema, table?)** - Grant permissions
  ```python
  # Examples:
  pg_grant_privileges("app_user", "SELECT, INSERT, UPDATE", "public", "users")
  pg_grant_privileges("app_user", "ALL PRIVILEGES", "public")  # All tables in schema
  ```

- **pg_revoke_privileges(username, privileges, schema, table?)** - Revoke permissions

### 📈 Performance & Monitoring

#### Query Monitoring
- **pg_active_queries(include_idle?)** - Show running queries
- **pg_long_running_queries(min_seconds?)** - Find slow queries
- **pg_blocking_queries()** - Find blocking queries
- **pg_connection_stats()** - Connection statistics
- **pg_locks_summary()** - Lock summary
- **pg_cache_hit_ratio()** - Cache hit ratio
- **pg_slowest_queries(limit?)** - Slowest queries (requires pg_stat_statements)

#### Query Control (Requires ENABLE_DANGEROUS=true)
- **pg_cancel_query(pid)** - Cancel query (gentle)
- **pg_kill_query(pid)** - Terminate query (force)
  ```python
  # Example: Find and kill long-running query
  long_queries = pg_long_running_queries(300)  # > 5 minutes
  for q in long_queries:
      pg_kill_query(q['pid'])
  ```

### 🔧 Maintenance Operations

#### Read Operations
- **pg_vacuum_stats()** - Show vacuum/analyze history

#### Write Operations (Requires ENABLE_DANGEROUS=true)
- **pg_vacuum_table(schema, table, full?, analyze?)** - Vacuum table
  ```python
  # Regular vacuum with analyze
  pg_vacuum_table("public", "users", full=False, analyze=True)
  
  # Full vacuum (locks table, reclaims more space)
  pg_vacuum_table("public", "large_table", full=True, analyze=True)
  ```

- **pg_analyze_table(schema, table?)** - Update statistics
  ```python
  # Analyze specific table
  pg_analyze_table("public", "users")
  
  # Analyze all tables in schema
  pg_analyze_table("public")
  ```

### 💾 Data Manipulation (DML)

All DML operations require ENABLE_DANGEROUS=true:

- **pg_insert_data(schema, table, columns, values)** - Insert data
  ```python
  pg_insert_data(
      schema="public",
      table="users",
      columns="name, email, age",
      values="'John Doe', 'john@example.com', 30"
  )
  ```

- **pg_update_data(schema, table, set_clause, where_clause?)** - Update data
  ```python
  pg_update_data(
      schema="public",
      table="users",
      set_clause="status = 'active', updated_at = NOW()",
      where_clause="id = 123"
  )
  ```

- **pg_delete_data(schema, table, where_clause)** - Delete data
  ```python
  # WHERE clause is REQUIRED to prevent accidental deletion
  pg_delete_data(
      schema="public",
      table="users",
      where_clause="created_at < NOW() - INTERVAL '1 year' AND status = 'inactive'"
  )
  ```

### 🔍 Query Execution

- **pg_query(sql, max_rows?)** - Execute SELECT (read-only, always available)
  ```python
  pg_query("SELECT * FROM users WHERE status = 'active'", max_rows=100)
  ```

- **pg_execute_sql(sql)** - Execute any SQL (Requires ENABLE_DANGEROUS=true)
  ```python
  # Use with extreme caution!
  pg_execute_sql("CREATE INDEX CONCURRENTLY idx_users_email ON users(email)")
  ```

- **pg_explain_query(sql, analyze?)** - Get query execution plan
  ```python
  pg_explain_query("SELECT * FROM users WHERE email = 'test@example.com'", analyze=True)
  ```

### 💼 Export & Backup

- **pg_export_table_csv(schema, table, limit?)** - Export to CSV
- **pg_backup_table_sql(schema, table)** - Generate SQL dump
  ```python
  # Get SQL dump of table structure + data
  sql_dump = pg_backup_table_sql("public", "users")
  # Save to file or use for backup
  ```

### 🔎 Schema Introspection

- **pg_list_views(schema)** - List views
- **pg_view_definition(schema, view)** - Get view SQL
- **pg_list_functions(schema)** - List functions/procedures

### ⚙️ System Information

- **pg_health()** - Basic connectivity check
- **pg_show_setting(name)** - Show specific setting
- **pg_server_settings(pattern?)** - List server settings
- **pg_extensions()** - List installed extensions
- **pg_tablespaces()** - List tablespaces
- **pg_replication_status()** - Replication status

## 🚀 Quick Start

### 1. Setup Environment

Create `.env` file:
```bash
# PostgreSQL connection
PGHOST=localhost
PGPORT=5432
PGDATABASE=postgres
PGUSER=postgres
PGPASSWORD=your_password_here
PGSSLMODE=prefer

# Safety: Enable write operations
ENABLE_DANGEROUS=false  # Set to 'true' to enable admin operations
```

### 2. Install Dependencies

```bash
pip install fastmcp psycopg psycopg-pool python-dotenv
```

### 3. Run the Server

```bash
python postgres_admin_complete.py
```

## 📚 Common Use Cases

### 1. Database Health Check
```python
# Check connectivity and version
health = pg_health()

# Get activity summary
summary = pg_database_activity_summary()

# Check cache performance
cache = pg_cache_hit_ratio()

# Find long-running queries
long_queries = pg_long_running_queries(60)
```

### 2. Performance Optimization
```python
# Find unused indexes
unused = pg_unused_indexes("public")

# Check table bloat
bloat = pg_bloat_check("public")

# Get slowest queries
slow = pg_slowest_queries(20)

# Check index usage
usage = pg_index_usage("public")
```

### 3. User Management Workflow
```python
# Create new application user
pg_create_user("app_user", "secure_password", createdb=False, login=True)

# Grant necessary permissions
pg_grant_privileges("app_user", "SELECT, INSERT, UPDATE, DELETE", "public")

# Verify permissions
permissions = pg_user_permissions("app_user")
```

### 4. Table Maintenance
```python
# Check vacuum status
vacuum_stats = pg_vacuum_stats()

# Vacuum and analyze table with high dead rows
pg_vacuum_table("public", "users", full=False, analyze=True)

# Rebuild indexes if needed
pg_reindex("public", table="users")
```

### 5. Emergency Operations
```python
# Find and kill blocking queries
blockers = pg_blocking_queries()
for blocker in blockers:
    pg_kill_query(blocker['blocking_pid'])

# Terminate idle connections
idle_queries = pg_active_queries(include_idle=True)
for query in idle_queries:
    if query['state'] == 'idle' and query['duration'] > 3600:
        pg_kill_query(query['pid'])
```

## ⚠️ Safety Guidelines

1. **Always test in development first** - Never run untested admin operations in production
2. **Use ENABLE_DANGEROUS=false by default** - Only enable when needed
3. **Backup before major changes** - Use pg_backup_table_sql() before DROP/ALTER operations
4. **Monitor active connections** - Check pg_active_queries() before database operations
5. **Use WHERE clauses** - Always use WHERE in UPDATE/DELETE to prevent accidents
6. **Check dependencies** - Use CASCADE carefully when dropping objects
7. **Vacuum during off-hours** - VACUUM FULL locks tables
8. **Test EXPLAIN first** - Use pg_explain_query() before running complex queries

## 🔐 Security Best Practices

1. **Limit permissions** - Don't use superuser accounts in .env
2. **Use strong passwords** - Generate secure passwords for new users
3. **Restrict network access** - Use pg_hba.conf to limit connections
4. **Monitor user activity** - Regular audits with pg_user_permissions()
5. **Rotate credentials** - Regularly update passwords with pg_alter_user()
6. **Principle of least privilege** - Grant minimum required permissions

## 🐛 Error Handling

All tools return error messages in a consistent format:

```python
# Success
{"status": "OK: executed successfully"}

# Error
{"error": "Database creation requires ENABLE_DANGEROUS=true"}

# SQL Error
{"error": "Query execution failed: syntax error at or near 'SELCT'"}
```

## 📝 Notes Tool

The server also includes a simple notes tool:

- **add_note(content)** - Append to notes.txt
- **read_notes(max_chars?)** - Read notes.txt

## 🔄 Difference from Original

**New Admin Capabilities Added:**

✅ Database create/drop
✅ Schema create/drop  
✅ Table create/alter/drop/truncate
✅ Index create/drop/reindex
✅ User create/alter/drop
✅ Grant/revoke privileges
✅ INSERT/UPDATE/DELETE operations
✅ Query kill/cancel
✅ Vacuum/analyze execution
✅ Direct SQL execution (pg_execute_sql)
✅ Enhanced backup helpers
✅ Activity summary dashboard

**Safety Improvements:**

✅ All write operations protected by ENABLE_DANGEROUS flag
✅ Enhanced error messages with details
✅ WHERE clause requirement for DELETE operations
✅ Automatic LIMIT for queries without one
✅ Prevention of dropping current database
✅ System schema protection

## 📊 Monitoring Dashboard Example

```python
def dashboard():
    """Get comprehensive database status"""
    return {
        "health": pg_health(),
        "activity": pg_database_activity_summary(),
        "connections": pg_connection_stats(),
        "cache_hit_ratio": pg_cache_hit_ratio(),
        "long_queries": pg_long_running_queries(300),
        "blocking": pg_blocking_queries(),
        "bloated_tables": pg_bloat_check("public"),
        "unused_indexes": pg_unused_indexes("public")
    }
```

## 🎯 Next Steps

1. Review and configure your `.env` file
2. Set `ENABLE_DANGEROUS` based on your needs
3. Test read-only operations first
4. Create backup procedures
5. Document your admin workflows
6. Set up monitoring alerts
7. Plan maintenance windows

## 📞 Support

For issues or questions:
- Check error messages carefully
- Review the safety guidelines
- Test in development environment first
- Verify ENABLE_DANGEROUS setting
- Check PostgreSQL logs for details

---

**Remember**: With great power comes great responsibility. Always test admin operations in a safe environment first!