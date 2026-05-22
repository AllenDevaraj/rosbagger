"""Schema subpackage — message -> backend-neutral table schema + Arrow build.

Re-exports the public API of the Phase 3 schema layer:

* :class:`~rosbagger_core.schema.model.ColumnDef` /
  :class:`~rosbagger_core.schema.model.TableSchema` — the backend-neutral table
  model (dotted columns, LIST / LIST-of-STRUCT, the four standard columns).
* :func:`~rosbagger_core.schema.flatten.build_table_schema` — build a
  ``TableSchema`` from a declared message type via the ``rosbags`` typestore.
* :func:`~rosbagger_core.schema.flatten.build_arrow_table` /
  :func:`~rosbagger_core.schema.flatten.flatten_message` — turn a stream of
  ``Message`` records into a typed ``pyarrow.Table`` (lazy heavy-blob ``include``
  seam; QURY-03/07).
* :func:`~rosbagger_core.schema.names.sanitize_table_name` /
  :class:`~rosbagger_core.schema.names.TableNameResolver` — topic -> table-name
  sanitization + collision resolution (QURY-01).
* :func:`~rosbagger_core.schema.identifiers.quote_ident` — SQL-injection-safe
  identifier quoting via ``sqlglot`` (the T-03-06 defense).

Note: re-exporting ``build_arrow_table`` / ``build_table_schema`` means
``import rosbagger_core.schema`` pulls in ``pyarrow`` and ``rosbags`` — that is
expected and fine (mirrors the ``reader`` subpackage convention). The
offline-guard invariant only requires that the TOP-LEVEL ``rosbagger_core``
package stays light: it does NOT import this subpackage, so ``import
rosbagger_core`` remains free of ``pyarrow``/``rosbags`` (Phase 1 decision;
``tests/test_offline_guard.py``). No ``import duckdb`` anywhere here (Phase 5).
"""

from .flatten import build_arrow_table, build_table_schema, flatten_message
from .identifiers import quote_ident
from .model import ColumnDef, TableSchema
from .names import TableNameResolver, sanitize_table_name

__all__ = [
    "ColumnDef",
    "TableSchema",
    "build_table_schema",
    "build_arrow_table",
    "flatten_message",
    "sanitize_table_name",
    "TableNameResolver",
    "quote_ident",
]
