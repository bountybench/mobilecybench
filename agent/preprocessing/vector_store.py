import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import lancedb
import pandas as pd
from langchain_openai import OpenAIEmbeddings

from utils.logger import logger


@dataclass
class CodeChunk:
    id: str  # Unique ID (e.g., file_path:start_line)
    text: str  # Code content
    vector: List[float]  # Embedding vector
    metadata: Dict[str, Any]  # Metadata (file_path, line, type, etc.)


class VectorStore:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Resolve absolute path relative to project root
            base_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            db_path = os.path.join(base_dir, "cache", "lancedb")

        self.db_path = db_path
        self.db = lancedb.connect(db_path)
        self.table_name = "codebase_vectors"
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

        # Initialize table if needed
        self._init_table()

    def _init_table(self):
        """Initialize the vectors table if it doesn't exist."""
        if self.table_name not in self.db.table_names():
            pass

    def add_chunks(self, chunks: List[Dict[str, Any]]) -> bool:
        """
        Add code chunks to the vector store.
        chunks: List of dicts with keys: id, text, metadata
        """
        if not chunks:
            return False

        try:
            # Generate embeddings
            texts = [chunk["text"] for chunk in chunks]
            vectors = self.embeddings.embed_documents(texts)

            # Prepare data for LanceDB
            data = []
            for i, chunk in enumerate(chunks):
                record = {
                    "id": chunk["id"],
                    "text": chunk["text"],
                    "vector": vectors[i],
                    **chunk["metadata"],  # Flatten metadata for querying
                }
                data.append(record)

            df = pd.DataFrame(data)

            if self.table_name in self.db.table_names():
                tbl = self.db.open_table(self.table_name)
                tbl.add(df)
            else:
                self.db.create_table(self.table_name, df)

            logger.info(f"Added {len(chunks)} chunks to vector store")
            return True
        except Exception as e:
            logger.error(f"Error adding chunks to vector store: {e}")
            return False

    def search(
        self, query: str, limit: int = 5, filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic search with optional metadata filtering.

        Args:
            query: Search query
            limit: Max results
            filter: Metadata filter (e.g. {"file_path": "apps/owncloud"})
                    Currently implements simple substring matching on key collision.
        """
        try:
            if self.table_name not in self.db.table_names():
                logger.warning("Vector store is empty")
                return []

            query_vector = self.embeddings.embed_query(query)
            tbl = self.db.open_table(self.table_name)

            # Start search query
            search_query = tbl.search(query_vector).limit(limit)

            # Apply filter if provided
            if filter:
                # Construct where clause for LanceDB
                # LanceDB supports SQL filters: "column = 'value'" or "column LIKE '%value%'"
                # We want prefix matching for paths: "file_path LIKE 'apps/owncloud%'"

                conditions = []
                for key, value in filter.items():
                    # Sanitize value simply
                    safe_value = str(value).replace("'", "''")

                    if key == "file_path":
                        # Prefix match for paths to allow "apps/owncloud" to match "apps/owncloud/MainActivity.java"
                        conditions.append(f"{key} LIKE '{safe_value}%'")
                    else:
                        # Exact match for other metadata
                        conditions.append(f"{key} = '{safe_value}'")

                if conditions:
                    where_clause = " AND ".join(conditions)
                    search_query = search_query.where(where_clause)

            results = search_query.to_pandas()
            return results.to_dict(orient="records")
        except Exception as e:
            logger.error(f"Error searching vector store: {e}")
            return []

    def clear(self):
        if self.table_name in self.db.table_names():
            self.db.drop_table(self.table_name)


# singleton pattern
_vector_store = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
