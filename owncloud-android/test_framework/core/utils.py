# utils.py (or database_utils.py)


import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional, Set
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/debug.log', mode='a'),
        logging.StreamHandler()
    ]
)


class DatabaseUtils:
    """
    Utility class for comparing SQLite databases, especially for testing file sync behaviors.
    Designed to be extended with other utilities (e.g., snapshot, file diff, etc.).
    """

    @staticmethod
    def get_table_schema(conn: sqlite3.Connection, table_name: str) -> List[str]:
        """Return list of column names for the table."""
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name});")
        return [row[1] for row in cursor.fetchall()]

    @staticmethod
    def get_table_data(conn: sqlite3.Connection, table_name: str) -> Dict[Any, Tuple[tuple, Optional[str]]]:
        """
        Extract all rows from table, keyed by '_id', and return local_path if available.
        Returns: { _id: (full_row, local_path), ... }
        """
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table_name};")
        rows = cursor.fetchall()
        columns = DatabaseUtils.get_table_schema(conn, table_name)

        if '_id' not in columns:
            raise ValueError(f"Table '{table_name}' does not have '_id' column.")

        id_idx = columns.index('_id')
        path_idx = columns.index('local_path') if 'local_path' in columns else None

        data = {}
        for row in rows:
            key = row[id_idx]
            local_path = row[path_idx] if path_idx is not None else None
            data[key] = (row, local_path)

        return data

    @staticmethod
    def compare_table(
        before_db_path: Path,
        after_db_path: Path,
        table_name: str = "list_of_uploads"
    ) -> Dict[str, Any]:
        """
        Compare a specific table between two SQLite databases and return structured diff.

        Returns:
            {
                "summary": { "added_count", "removed_count", "modified_count" },
                "changes": { "added", "removed", "modified" },
                "metadata": { "before_db", "after_db", "table", "timestamp" }
            }
        """
        before_path = Path(before_db_path)
        after_path = Path(after_db_path)

        if not before_path.exists():
            raise FileNotFoundError(f"Before database not found: {before_db_path}")
        if not after_path.exists():
            raise FileNotFoundError(f"After database not found: {after_db_path}")

        try:
            before_conn = sqlite3.connect(before_path)
            after_conn = sqlite3.connect(after_path)
        except sqlite3.Error as e:
            raise ConnectionError(f"Failed to connect to databases: {e}")

        try:
            # Validate table exists
            def table_exists(conn, tbl):
                cur = conn.cursor()
                cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (tbl,))
                return cur.fetchone() is not None

            if not table_exists(before_conn, table_name):
                raise ValueError(f"Table '{table_name}' not found in 'before' database.")
            if not table_exists(after_conn, table_name):
                raise ValueError(f"Table '{table_name}' not found in 'after' database.")

            # Load data
            before_data = DatabaseUtils.get_table_data(before_conn, table_name)
            after_data = DatabaseUtils.get_table_data(after_conn, table_name)

            before_keys = set(before_data.keys())
            after_keys = set(after_data.keys())

            # Find changes
            added = {str(k): after_data[k][1] for k in after_keys - before_keys}
            removed = {str(k): before_data[k][1] for k in before_keys - after_keys}

            modified = {}
            for k in before_keys & after_keys:
                if before_data[k][0] != after_data[k][0]:  # full row differs
                    modified[str(k)] = {
                        "before": before_data[k][1],
                        "after": after_data[k][1]
                    }

            # Build result
            result = {
                "summary": {
                    "added_count": len(added),
                    "removed_count": len(removed),
                    "modified_count": len(modified)
                },
                "changes": {
                    "added": added,
                    "removed": removed,
                    "modified": modified
                },
                "metadata": {
                    "before_db": str(before_path),
                    "after_db": str(after_path),
                    "table": table_name,
                    "timestamp": datetime.now().isoformat()
                }
            }

            return result

        finally:
            before_conn.close()
            after_conn.close()

    @staticmethod
    def save_diff_to_json(diff_data: Dict[str, Any], output_path: Path) -> None:
        """Save the comparison result to a JSON file."""
        output_path = Path(output_path)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(diff_data, f, indent=2, ensure_ascii=False)
        logging.info(f"Database diff saved to {output_path}")


class FilesystemUtils:
    """
    Utility class for comparing filesystem snapshots (e.g., from instrumentation tests).
    Designed to work alongside DatabaseUtils in a test analysis suite.
    """

    @staticmethod
    def load_snapshot(path: Path) -> Dict[str, Any]:
        """Load a JSON snapshot file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot file not found: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def get_files_with_meta(
        snapshot: Dict[str, Any],
        extension: Optional[str] = ".txt"
    ) -> Dict[str, Any]:
        """
        Extract files with metadata by extension.
        If extension is None, returns all files.
        """
        meta = snapshot.get("file_metadata", {})
        if extension is None:
            return meta
        ext = extension.lower()
        return {
            path: info for path, info in meta.items()
            if path.lower().endswith(ext)
        }

    @staticmethod
    def compare_files(before_meta: Dict[str, Any], after_meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compare two metadata dictionaries and detect created, deleted, and modified files.

        Modification is based on:
        - mtime mismatch
        - sha256 hash mismatch (if both exist)
        """
        before_paths: Set[str] = set(before_meta.keys())
        after_paths: Set[str] = set(after_meta.keys())

        created: List[str] = sorted(after_paths - before_paths)
        deleted: List[str] = sorted(before_paths - after_paths)
        common: Set[str] = before_paths & after_paths

        modified: List[str] = []
        for path in common:
            b_info = before_meta[path]
            a_info = after_meta[path]
            # Check modification via mtime or hash
            if (a_info.get('mtime') != b_info.get('mtime') or
                (a_info.get('sha256') and b_info.get('sha256') and a_info['sha256'] != b_info['sha256'])):
                modified.append(path)

        return {
            "summary": {
                "created_count": len(created),
                "deleted_count": len(deleted),
                "modified_count": len(modified)
            },
            "changes": {
                "created": created,
                "deleted": deleted,
                "modified": modified
            }
        }

    @staticmethod
    def compare_snapshots(
        before_snapshot_path: Path,
        after_snapshot_path: Path,
        extension: Optional[str] = ".txt",
        output_json: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Full comparison between two snapshots.

        Args:
            before_snapshot_path: Path to 'before' JSON snapshot
            after_snapshot_path:  Path to 'after' JSON snapshot
            extension: File extension to filter by (e.g., '.txt'), or None for all
            output_json: Optional path to save the diff as JSON

        Returns:
            Dictionary with summary and detailed changes
        """
        extension = None
        # Load snapshots
        before_data = FilesystemUtils.load_snapshot(before_snapshot_path)
        after_data = FilesystemUtils.load_snapshot(after_snapshot_path)

        # Extract filtered files
        before_files = FilesystemUtils.get_files_with_meta(before_data, extension)
        after_files = FilesystemUtils.get_files_with_meta(after_data, extension)

        # Compare
        diff = FilesystemUtils.compare_files(before_files, after_files)

        # Add metadata
        diff["metadata"] = {
            "before_snapshot": str(before_snapshot_path),
            "after_snapshot": str(after_snapshot_path),
            "filtered_extension": extension,
            "timestamp": __import__('datetime').datetime.now().isoformat()
        }

        # Save to file if requested
        if output_json:
            output_path = Path(output_json)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(diff, f, indent=2, ensure_ascii=False)
            logging.info(f"Filesystem diff saved to {output_path}")

        return diff
