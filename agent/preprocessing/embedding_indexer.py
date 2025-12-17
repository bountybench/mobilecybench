from pathlib import Path
from typing import List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent.preprocessing.tree_sitter_indexer import CodebaseIndexer
from agent.preprocessing.vector_store import get_vector_store
from utils.logger import logger


def embed_files_to_vector_store(file_paths: List[str], indexer: Optional[CodebaseIndexer] = None) -> None:
    """
    Embed files into VectorStore.
    
    Strategies:
    1. Java/Kotlin: Use 'indexer' (Tree-sitter) for Guided Method Chunking (Semantic).
    2. Polyglot/Other: Use Text Splitting (Fallback).
    """
    logger.info(f"[VectorStore] Embedding {len(file_paths)} files...")
    vector_store = get_vector_store()
    
    # TODO: remove this after proper incremental updates and caching are implemented.
    # this should be long term memory.
    vector_store.clear()
    
    # Separate Native (Java/Kotlin) vs Polyglot (JS, etc.)
    # Tree-sitter indexer supports both Java and Kotlin now.
    native_extensions = {".java", ".kt"}
    polyglot_files = [f for f in file_paths if Path(f).suffix not in native_extensions]
    
    chunks = []
    
    # 1. Guided Chunking (Java/Kotlin) via Tree-sitter
    if indexer:
        logger.info("[VectorStore] Using Tree-sitter Guided Chunking for Java/Kotlin...")
        # Iterate all methods found by the indexer
        count_methods = 0
        for method_name, symbols in indexer.methods.items():
            for symbol in symbols:
                # Only process if this file is in our target list (consistency check)
                if symbol.file_path in file_paths:
                    content = _read_file_segment(symbol.file_path, symbol.line_start, symbol.line_end)
                    if content:
                        chunk = {
                            "id": f"{symbol.file_path}:{symbol.line_start}-{symbol.line_end}",
                            "text": content,
                            "metadata": {
                                "file_path": symbol.file_path,
                                "start_line": symbol.line_start,
                                "type": "method",
                                "name": symbol.name,
                                "type": "method",
                                "name": symbol.name,
                                "language": "java"
                            }
                        }
                        chunks.append(chunk)
                        count_methods += 1
        logger.info(f"[VectorStore] Generated {count_methods} Method Chunks (Guided).")
    else:
        logger.warning("[VectorStore] No indexer provided! Java/Kotlin will fallback to Text Chunking (Suboptimal).")
        # If no indexer, add Java/Kt back to polyglot list for text chunking
        polyglot_files = file_paths

    # 2. Text Chunking (Polyglot + Fallbacks)
    if polyglot_files:
        logger.info(f"[VectorStore] Processing {len(polyglot_files)} files with Text Splitting...")
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\nfunction ", "\nclass ", "\nexport ", "\n<template>", "\n<script>", "\n\n", "\n", " "]
        )
        
        processed_count = 0
        for file_path in polyglot_files:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    
                splits = splitter.create_documents([content])
                
                for i, split in enumerate(splits):
                    chunk = {
                        "id": f"{file_path}:chunk_{i}",
                        "text": split.page_content,
                        "metadata": {
                            "file_path": file_path,
                            "start_line": 0,
                            "type": "text_chunk",
                            "name": f"{Path(file_path).name}_chunk_{i}",
                            "language": Path(file_path).suffix[1:]
                        }
                    }
                    chunks.append(chunk)
                processed_count += 1
            except Exception as e:
                logger.warning(f"Failed to process {file_path}: {e}")
                
        logger.info(f"[VectorStore] Generated {len(chunks) -  (count_methods if indexer else 0)} Text Chunks.")

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
