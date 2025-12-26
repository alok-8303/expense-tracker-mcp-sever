import json
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

# print(DATABASE_URL)

conn = psycopg2.connect(DATABASE_URL)

with open("categories.json", "r", encoding="utf-8") as f:
    data = json.load(f)

with conn:
    with conn.cursor() as cur:
        for category, subs in data.items():

            # Insert category (or fetch existing)
            cur.execute(
                """
                INSERT INTO categories (name)
                VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                RETURNING id
                """,
                (category,)
            )

            row = cur.fetchone()
            if row:
                category_id = row[0]
            else:
                cur.execute(
                    "SELECT id FROM categories WHERE name = %s",
                    (category,)
                )
                category_id = cur.fetchone()[0]

            # Insert subcategories
            for sub in subs:
                cur.execute(
                    """
                    INSERT INTO subcategories (category_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (category_id, name) DO NOTHING
                    """,
                    (category_id, sub)
                )

conn.close()

print("✅ Categories & subcategories seeded successfully.")
