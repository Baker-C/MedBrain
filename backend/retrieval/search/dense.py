"""Dense search: the nearest chunks to a query vector, by cosine distance.

`<=>` is pgvector's cosine-distance operator, matching the HNSW index built with
`vector_cosine_ops`.
"""

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from persistence.rows import ChunkRow
from retrieval.search.chunk_rows import CHUNK_COLUMNS, fetch_chunks

# The order-by is left bare — adding a tie-break column would force a sort on top
# of the scan and cost the HNSW index.
DENSE_SEARCH = sql.SQL(
    "select {columns} from chunks order by embedding <=> %s::vector limit %s"
).format(columns=CHUNK_COLUMNS)


def run_dense_search(
    conn: psycopg.Connection[TupleRow], embedding: list[float], limit: int
) -> list[ChunkRow]:
    """Adapter: the top `limit` chunks by cosine distance, nearest first.

    pgvector's text input format is exactly Python's list repr, so the vector goes
    over as a parameter and is cast in the query rather than interpolated.
    """
    return fetch_chunks(conn, DENSE_SEARCH, (str(embedding), limit))
