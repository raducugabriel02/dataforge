with monthly_spending as (
    select * from {{ ref('mart_monthly_spending') }}
),

balances as (
    select
        month_start,
        sum(balance_eom_filled) as net_worth_eom
    from {{ ref('mart_account_balances') }}
    group by month_start
),

joined as (
    select
        monthly_spending.*,
        balances.net_worth_eom,
        row_number() over (order by monthly_spending.month_start) as month_index
    from monthly_spending
    left join balances
        on monthly_spending.month_start = balances.month_start
),

with_metrics as (
    select
        joined.*,
        case
            when joined.total_income > 0
                then round(joined.net_cashflow / joined.total_income, 4)
        end as savings_rate,
        joined.net_worth_eom - lag(joined.net_worth_eom, 3) over (
            order by joined.month_start
        ) as net_worth_trend_3m,
        -- Regresie liniara simpla (metoda celor mai mici patrate) peste
        -- ultimele 6 luni de cheltuieli: regr_slope/regr_intercept sunt
        -- functii agregat standard in Postgres, utilizabile si ca window
        -- functions cu OVER — nu e nevoie de Python/ML pentru un trend
        -- simplu. Cu sub 2 luni distincte de date, Postgres le returneaza
        -- NULL automat (nu are ce panta sa calculeze) — nu ascundem
        -- limitarea forecast-ului cand nu exista istoric, apare direct ca
        -- NULL in date, nu ca o valoare inventata.
        regr_slope(joined.total_spending, joined.month_index) over (
            order by joined.month_start rows between 5 preceding and current row
        ) as spending_trend_slope,
        regr_intercept(joined.total_spending, joined.month_index) over (
            order by joined.month_start rows between 5 preceding and current row
        ) as spending_trend_intercept
    from joined
)

select
    month_start,
    total_spending,
    total_income,
    net_cashflow,
    rolling_3_month_avg,
    delta_vs_previous_month,
    cast(net_worth_eom as numeric(14, 2)) as net_worth_eom,
    cast(net_worth_trend_3m as numeric(14, 2)) as net_worth_trend_3m,
    cast(savings_rate as numeric(10, 4)) as savings_rate,
    cast(
        spending_trend_intercept + spending_trend_slope * (month_index + 1) as numeric(14, 2)
    ) as forecast_next_month_spending
from with_metrics
order by month_start
