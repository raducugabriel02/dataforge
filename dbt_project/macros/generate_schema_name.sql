{#
    Without this override, a model with +schema: marts would be materialized
    into "<target_schema>_marts" (dbt's default: prefix, not replace). We want
    the medallion schema names literally: staging, marts — not staging_marts.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
