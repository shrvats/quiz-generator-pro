import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import VectorDatabase

async def run_migrations():
    vector_db = VectorDatabase()
    await vector_db.initialize()
    print("Database tables created successfully")
    await vector_db.close()

if __name__ == "__main__":
    asyncio.run(run_migrations())
