import asyncio
import os
import sys
import asyncpg

# Database URL from environment or argument
DATABASE_URL = os.environ.get('DATABASE_URL') or sys.argv[1]

async def setup_pgvector():
    # Connect to the database
    print(f"Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)
    
    try:
        # Create vector extension
        print("Creating vector extension...")
        await conn.execute('CREATE EXTENSION IF NOT EXISTS vector;')
        
        # Create tables
        print("Creating tables...")
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id SERIAL PRIMARY KEY,
                file_hash TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                total_pages INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                metadata JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id SERIAL PRIMARY KEY,
                question_id TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                text TEXT NOT NULL,
                options JSONB,
                correct_answer TEXT,
                explanation TEXT,
                embedding vector(384),
                metadata JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        
        # Create index
        print("Creating vector index...")
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS questions_embedding_idx 
            ON questions USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        ''')
        
        print("Database setup completed successfully!")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    if not DATABASE_URL:
        print("Usage: python setup_pgvector.py DATABASE_URL")
        sys.exit(1)
        
    asyncio.run(setup_pgvector())
