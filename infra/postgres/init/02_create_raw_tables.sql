-- _row_hash as primary key: two rows with identical (bank, date, description,
-- amount, balance_after) ARE the same economic event, so this doubles as the
-- idempotency key. _source_file is metadata only, deliberately excluded from
-- the hash, so re-ingesting the same transactions from a differently-named
-- re-export still dedupes correctly.
CREATE TABLE IF NOT EXISTS raw.bank_transactions (
    _row_hash TEXT PRIMARY KEY,
    source_bank TEXT NOT NULL,
    txn_date DATE NOT NULL,
    description TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    balance_after NUMERIC(12, 2) NOT NULL,
    _source_file TEXT NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bank_transactions_txn_date ON raw.bank_transactions (txn_date);
CREATE INDEX IF NOT EXISTS idx_bank_transactions_source_bank ON raw.bank_transactions (source_bank);
