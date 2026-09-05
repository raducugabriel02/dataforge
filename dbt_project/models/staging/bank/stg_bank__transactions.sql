with source as (
    select * from {{ source('raw', 'bank_transactions') }}
),

renamed as (
    select
        _row_hash as transaction_id,
        source_bank,
        txn_date,
        description,
        amount,
        balance_after,
        _source_row_number,
        _source_file,
        _loaded_at
    from source
)

select * from renamed
