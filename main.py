from fastmcp import FastMCP, get_context
import asyncpg
import os
from typing import Optional
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

mcp = FastMCP("ExpenseTracker")

# ------------------------------------------------------------------
# Auth helper
# ------------------------------------------------------------------

def require_user():
    ctx = get_context()
    if not ctx.user:
        raise RuntimeError("Authentication required")
    return ctx.user.id  # Supabase UUID

# ------------------------------------------------------------------
# Database helpers
# ------------------------------------------------------------------

async def get_conn():
    return await asyncpg.connect(DATABASE_URL)

# ------------------------------------------------------------------
# MCP Resource: Categories (shared, read-only)
# ------------------------------------------------------------------

@mcp.resource("expense://categories", mime_type="application/json")
async def categories():
    conn = await get_conn()
    try:
        rows = await conn.fetch("""
            SELECT c.name AS category, s.name AS subcategory
            FROM categories c
            LEFT JOIN subcategories s ON s.category_id = c.id
            ORDER BY c.name, s.name
        """)

        result = {}
        for r in rows:
            result.setdefault(r["category"], []).append(r["subcategory"])

        return result
    finally:
        await conn.close()

# ------------------------------------------------------------------
# MCP Tool: Add Expense (WRITE, AUTH REQUIRED)
# ------------------------------------------------------------------

@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: Optional[str] = None,
    note: str = ""
):
    user_id = require_user()

    conn = await get_conn()
    try:
        cat = await conn.fetchrow(
            "SELECT id FROM categories WHERE name = $1",
            category
        )
        if not cat:
            return {"error": f"Invalid category: {category}"}

        category_id = cat["id"]
        subcategory_id = None

        if subcategory:
            sub = await conn.fetchrow(
                """
                SELECT id FROM subcategories
                WHERE name = $1 AND category_id = $2
                """,
                subcategory,
                category_id
            )
            if not sub:
                return {"error": f"Invalid subcategory '{subcategory}' for '{category}'"}
            subcategory_id = sub["id"]

        try:
            date = datetime.strptime(date, "%d-%m-%Y").date()
        except ValueError:
            try:
                date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                return {"error": "Invalid date format. Use DD-MM-YYYY or YYYY-MM-DD."}

        expense_id = await conn.fetchval(
            """
            INSERT INTO expenses
                (user_id, expense_date, amount, category_id, subcategory_id, note)
            VALUES
                ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            user_id,
            date,
            amount,
            category_id,
            subcategory_id,
            note
        )

        return {"status": "ok", "id": expense_id}

    finally:
        await conn.close()

# ------------------------------------------------------------------
# MCP Tool: List Expenses (READ, AUTH REQUIRED)
# ------------------------------------------------------------------

@mcp.tool()
async def list_expenses(start_date: str, end_date: str):
    user_id = require_user()

    try:
        start_date = datetime.strptime(start_date, "%d-%m-%Y").date()
        end_date = datetime.strptime(end_date, "%d-%m-%Y").date()
    except ValueError:
        try:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "Invalid date format."}

    conn = await get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT
                e.id,
                e.expense_date,
                e.amount,
                c.name AS category,
                s.name AS subcategory,
                e.note
            FROM expenses e
            JOIN categories c ON e.category_id = c.id
            LEFT JOIN subcategories s ON e.subcategory_id = s.id
            WHERE e.user_id = $1
              AND e.expense_date BETWEEN $2 AND $3
            ORDER BY e.expense_date ASC
            """,
            user_id,
            start_date,
            end_date
        )

        return [dict(r) for r in rows]

    finally:
        await conn.close()

# ------------------------------------------------------------------
# MCP Tool: Summarize Expenses (READ, AUTH REQUIRED)
# ------------------------------------------------------------------

@mcp.tool()
async def summarize(
    start_date: str,
    end_date: str,
    category: Optional[str] = None,
    subcategory: Optional[str] = None
):
    user_id = require_user()

    try:
        start_date = datetime.strptime(start_date, "%d-%m-%Y").date()
        end_date = datetime.strptime(end_date, "%d-%m-%Y").date()
    except ValueError:
        try:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "Invalid date format."}

    conn = await get_conn()
    try:
        query = """
            SELECT
                c.name AS category,
                s.name AS subcategory,
                SUM(e.amount) AS total_amount
            FROM expenses e
            JOIN categories c ON e.category_id = c.id
            LEFT JOIN subcategories s ON e.subcategory_id = s.id
            WHERE e.user_id = $1
              AND e.expense_date BETWEEN $2 AND $3
        """
        params = [user_id, start_date, end_date]

        if category:
            query += " AND c.name = $4"
            params.append(category)

        if subcategory:
            query += " AND s.name = $5"
            params.append(subcategory)

        query += """
            GROUP BY c.name, s.name
            ORDER BY total_amount DESC
        """

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    finally:
        await conn.close()

# ------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
