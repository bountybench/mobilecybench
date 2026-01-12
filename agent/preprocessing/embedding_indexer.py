from pathlib import Path
from typing import List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent.preprocessing.tree_sitter_indexer import CodebaseIndexer
from agent.preprocessing.vector_store import get_vector_store
from utils.logger import logger


def embed_files_to_vector_store(
    file_paths: List[str], indexer: Optional[CodebaseIndexer] = None, codebase_root: Optional[str] = None
) -> None:
    """
    Embed files into VectorStore.

    Strategies:
    1. Java/Kotlin: Use 'indexer' (Tree-sitter) for Guided Method Chunking (Semantic).
    2. Polyglot/Other: Use Text Splitting (Fallback).

    Args:
        file_paths: List of absolute file paths
        indexer: Optional tree-sitter indexer for guided chunking
        codebase_root: Optional codebase root path for relativizing paths
    """
    logger.info(f"[VectorStore] Embedding {len(file_paths)} files...")
    vector_store = get_vector_store()

    # Infer codebase_root from first file if not provided
    if codebase_root is None and file_paths:
        # Find /codebase/ in path and use everything before it
        first_path = file_paths[0]
        if "/codebase/" in first_path:
            codebase_root = first_path.split("/codebase/")[0] + "/codebase"
        elif "\\codebase\\" in first_path:  # Windows
            codebase_root = first_path.split("\\codebase\\")[0] + "\\codebase"

    # TODO: remove this after proper incremental updates and caching are implemented.
    # this should be long term memory.
    vector_store.clear()

    def to_relative_path(abs_path: str) -> str:
        """Convert absolute path to relative path from codebase root."""
        if codebase_root and abs_path.startswith(codebase_root):
            rel = abs_path[len(codebase_root):]
            # Remove leading slash
            return rel.lstrip("/").lstrip("\\")
        return abs_path

    # Separate Native (Java/Kotlin) vs Polyglot (JS, etc.)
    # Tree-sitter indexer supports both Java and Kotlin now.
    native_extensions = {".java", ".kt"}
    polyglot_files = [f for f in file_paths if Path(f).suffix not in native_extensions]

    chunks = []
    count_methods = 0

    # 1. Guided Chunking (Java/Kotlin) via Tree-sitter
    if indexer:
        logger.info(
            "[VectorStore] Using Tree-sitter Guided Chunking for Java/Kotlin..."
        )
        for method_name, symbols in indexer.methods.items():
            for symbol in symbols:
                # Only process if this file is in our target list (consistency check)
                if symbol.file_path in file_paths:
                    content = _read_file_segment(
                        symbol.file_path, symbol.line_start, symbol.line_end
                    )
                    if content:
                        # Store RELATIVE path so agent can use it with container paths
                        relative_path = to_relative_path(symbol.file_path)
                        chunk = {
                            "id": f"{relative_path}:{symbol.line_start}-{symbol.line_end}",
                            "text": content,
                            "metadata": {
                                "file_path": relative_path,
                                "start_line": symbol.line_start,
                                "type": "method",
                                "name": symbol.name,
                                "language": "java",
                            },
                        }
                        chunks.append(chunk)
                        count_methods += 1
        logger.info(f"[VectorStore] Generated {count_methods} Method Chunks (Guided).")
    else:
        logger.warning(
            "[VectorStore] No indexer provided! Java/Kotlin will fallback to Text Chunking (Suboptimal)."
        )
        # If no indexer, add Java/Kt back to polyglot list for text chunking
        polyglot_files = file_paths

    # 2. Text Chunking (Polyglot + Fallbacks)
    if polyglot_files:
        logger.info(
            f"[VectorStore] Processing {len(polyglot_files)} files with Text Splitting..."
        )

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=[
                "\nfunction ",
                "\nclass ",
                "\nexport ",
                "\n<template>",
                "\n<script>",
                "\n\n",
                "\n",
                " ",
            ],
        )

        processed_count = 0
        for file_path in polyglot_files:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                splits = splitter.create_documents([content])

                # Store RELATIVE path so agent can use it with container paths
                relative_path = to_relative_path(file_path)
                for i, split in enumerate(splits):
                    chunk = {
                        "id": f"{relative_path}:chunk_{i}",
                        "text": split.page_content,
                        "metadata": {
                            "file_path": relative_path,
                            "start_line": 0,
                            "type": "text_chunk",
                            "name": f"{Path(file_path).name}_chunk_{i}",
                            "language": Path(file_path).suffix[1:],
                        },
                    }
                    chunks.append(chunk)
                processed_count += 1
            except Exception as e:
                logger.warning(f"Failed to process {file_path}: {e}")

        text_chunks_count = len(chunks) - count_methods
        logger.info(f"[VectorStore] Generated {text_chunks_count} Text Chunks.")

    logger.info(f"[VectorStore] Total Chunks to Upsert: {len(chunks)}")

    BATCH_SIZE = 100
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        vector_store.add_chunks(batch)


def _read_file_segment(path: str, start_line: int, end_line: int) -> str:
    """Read lines from file (1-indexed)."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            # Adjust strict bounds
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            return "".join(lines[start_idx:end_idx])
    except Exception:
        return ""
