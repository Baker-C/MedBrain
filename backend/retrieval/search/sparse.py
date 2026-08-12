"""Sparse search: Postgres full-text ranking over the generated `tsv` column.

`websearch_to_tsquery` because it accepts what users actually type — quoted
phrases, `or`, leading `-` — without raising on punctuation the way `to_tsquery`
does. Ranking is `ts_rank`, which is deliberately **not** BM25: it has no
document-length normalization or term saturation. See DESIGN.md's known debt.
"""

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from persistence.rows import ChunkRow
from retrieval.search.chunk_rows import CHUNK_COLUMNS, fetch_chunks

# The tsquery is built once in the FROM clause and reused by both the match and the
# rank. `id` breaks ts_rank ties so repeated eval runs order identically.
SPARSE_SEARCH = sql.SQL(
    "select {columns} from chunks, websearch_to_tsquery('english', %s) query"
    " where tsv @@ query order by ts_rank(tsv, query) desc, id limit %s"
).format(columns=CHUNK_COLUMNS)


def run_sparse_search(
    conn: psycopg.Connection[TupleRow], query: str, limit: int
) -> list[ChunkRow]:
    """Adapter: the top `limit` chunks by ts_rank, best first.

    A query whose terms are all stopwords, or that matches nothing, returns no rows —
    fusion treats that as an empty leg rather than an error.
    """
    return fetch_chunks(conn, SPARSE_SEARCH, (query, limit))
