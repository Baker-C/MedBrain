"""Sparse search: Postgres full-text ranking over the generated `tsv` column.

`websearch_to_tsquery` because it accepts what users actually type — quoted
phrases, `or`, leading `-` — without raising on punctuation the way `to_tsquery`
does. Ranking is `ts_rank`, which is deliberately **not** BM25: it has no
document-length normalization or term saturation. See DESIGN.md's known debt.

**The lexemes are OR-ed, not AND-ed.** `websearch_to_tsquery` joins bare terms
with `&`, which asks for a chunk containing *every* word of the question —
`'trazodon' & 'label' & 'say' & 'priapism'` matches nothing, though twelve
chunks contain `priapism`. Against natural-language questions that is a leg that
never returns a row, and the query rewriter makes it worse by producing longer
questions with more conjuncts. Rewriting the operators to `|` asks the question
a keyword leg is meant to ask — which chunks share the most terms — and leaves
`ts_rank` to order them.

The rewrite is textual, on the compiled tsquery rather than the user's string, so
phrase operators (`<->`) pass through intact and an explicit `or` is unchanged.
**Negation does not survive in meaning**: `'bleed' & !'warfarin'` becomes
`'bleed' | !'warfarin'`, and a disjunct of "any chunk without warfarin" matches
almost the whole table, so a leading `-` stops excluding. Accepted rather than
fixed, because the string reaching this leg is the rewriter's output — generated
prose that carries no `-term` and no quotes. Honouring exclusion under
disjunction means parsing the tsquery into `(a | b) & !c`, which is a parser this
corpus has no caller for.
"""

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from persistence.rows import ChunkRow
from retrieval.search.chunk_rows import CHUNK_COLUMNS, fetch_chunks

# The tsquery is built once in the FROM clause and reused by both the match and the
# rank. `id` breaks ts_rank ties so repeated eval runs order identically.
SPARSE_SEARCH = sql.SQL(
    "select {columns} from chunks,"
    " (select replace(websearch_to_tsquery('english', %s)::text, '&', '|')::tsquery)"
    " as search(query)"
    " where tsv @@ search.query order by ts_rank(tsv, search.query) desc, id limit %s"
).format(columns=CHUNK_COLUMNS)


def run_sparse_search(
    conn: psycopg.Connection[TupleRow], query: str, limit: int
) -> list[ChunkRow]:
    """Adapter: the top `limit` chunks by ts_rank, best first.

    A query whose terms are all stopwords, or that matches nothing, returns no rows —
    fusion treats that as an empty leg rather than an error.
    """
    return fetch_chunks(conn, SPARSE_SEARCH, (query, limit))
