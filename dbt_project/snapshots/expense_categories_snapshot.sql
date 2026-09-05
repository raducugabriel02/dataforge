{% snapshot expense_categories_snapshot %}

{{
    config(
        target_schema='staging',
        unique_key='category_name',
        strategy='timestamp',
        updated_at='updated_at',
    )
}}

select * from {{ ref('expense_categories_seed') }}

{% endsnapshot %}
