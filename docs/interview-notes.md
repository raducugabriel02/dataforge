# Interview Notes

Note construite pe parcurs, fază cu fază — nu retroactiv la final. Fiecare secțiune explică o decizie de arhitectură ca la un interviu tehnic: ce problemă rezolvă, ce alternative existau, de ce am ales asta.

## Faza 0 — Fundația

*(de completat)*

## Schema drift (după Faza 1)

**Problema:** un extras bancar e un CSV fără schemă impusă de nimeni. Dacă banca schimbă ordinea coloanelor, redenumește un header sau inversează sensul Debit/Credit, un parser bazat pe index de coloană ar citi silențios date greșite în alt câmp — o sumă de cheltuială ar putea fi interpretată ca venit, fără nicio eroare vizibilă în log.

**Soluția implementată:** fiecare `BankStatementParser` concret (`BTParser`, `BCRParser`, `INGParser`) declară explicit `_expected_header()`. La fiecare `parse()`, headerul citit din CSV e comparat exact cu cel așteptat — dacă nu se potrivesc, se ridică `SchemaDriftError` și **tot fișierul e respins**, nu doar rândurile afectate. Mesajul de eroare spune clar ce s-a așteptat vs. ce s-a găsit (`ingestion/parsers/base.py`).

**De ce fail-fast pe header, dar fail-per-rând pe date invalide?** O coloană lipsă sau redenumită înseamnă că *toate* rândurile din fișier ar putea fi interpretate greșit — nu poți avea încredere parțială într-un fișier cu schema greșită. O dată invalidă sau o sumă necitibilă, în schimb, e izolată la acel rând — restul fișierului rămâne de încredere. De aceea `parse()` întoarce `ParseResult(transactions, errors)`: rândurile bune intră în `raw`, cele corupte sunt logate explicit (linie + conținut brut, via loguru structurat), fișierul nu e aruncat în întregime pentru o singură linie proastă. Verificat practic: un CSV cu o dată invalidă pe linia 3 a produs 2 tranzacții valide + 1 eroare logată clar (`line_number: 3`, `raw_row: {...}`).

**Trade-off acceptat:** dacă banca doar adaugă o coloană nouă la final (backward-compatible), tot respingem fișierul, chiar dacă am fi putut ignora coloana în plus. Am ales strict peste permisiv: un fals pozitiv (respingem un fișier valid) e mult mai ieftin de investigat decât un fals negativ (ingerăm date corupte silențios într-un warehouse financiar).

## Idempotența end-to-end (după Faza 3)

**Problema:** un DAG zilnic va rula peste aceleași fișiere de mai multe ori — retry manual, restart de container, sau pur și simplu re-declanșare după un fix. Dacă orice pas din pipeline nu e idempotent, o rulare dublă înseamnă date duplicate în warehouse.

**Cum e garantată idempotența pe fiecare strat, capăt la capăt:**
- **`ingest`** (raw): `RawLoader` face dedup pe `_row_hash` (Faza 1) — task-ul de Airflow nu ține el evidența fișierelor deja procesate, se bazează complet pe loader să fie sigur la re-rulare. Verificat practic: al doilea `trigger` pe DAG a lăsat 149/149/149 rânduri per bancă, neschimbat.
- **`dbt_seed`**: re-încarcă seed-ul de categorii de fiecare dată (full refresh) — sigur, pentru că fișierul sursă e static; aceleași date in => aceleași date out.
- **`dbt_snapshot`**: strategia `timestamp` pe `updated_at` — dacă rândul nu s-a schimbat, snapshot-ul nu adaugă o versiune nouă. Așa se păstrează SCD Type 2 corect chiar dacă snapshot-ul rulează zilnic degeaba (fără schimbări reale de categorii).
- **`dbt_run`**: modelele marts sunt `table` (full refresh la fiecare rulare, nu incremental) — la volumul curent (sute de rânduri) recalcularea completă e mai simplă și mai sigură decât un `unique_key` incremental; ar deveni incremental abia la volum mare (v4+, out of scope acum).
- **`dbt_test`**: prin construcție n-are stare — doar validează, nu poate produce duplicate.

**Catchup controlat:** DAG-ul are `catchup=False` — la activare, Airflow programează o singură rulare pentru cel mai recent interval încheiat, nu una pentru fiecare zi de la `start_date`. Testat: la unpause a apărut exact un run `scheduled__...`, nu un backlog de rulări istorice. Dacă aș vrea reconstituire istorică explicită (ex. reprocesare completă după un bug), aș folosi `airflow dags backfill` manual, cu control explicit pe intervalul de date — nu las scheduler-ul s-o facă implicit.

**De ce task-urile dbt sunt separate (`seed`→`snapshot`→`run`→`test`), nu un singur `dbt build`:** graful din Airflow UI arată exact unde a picat pipeline-ul (ex. testul, nu seed-ul) fără să deschid loguri; fiecare pas are propriul istoric de retry/durată. Costul: 4 task-uri BashOperator în loc de unul, acceptabil la scara asta.

## Scalare 100x (după Faza 4)

**Întrebarea:** dacă în loc de un extras lunar personal aș avea 100x volumul (sute de mii de tranzacții/zi, mai multe surse, mai mulți useri) — ce s-ar schimba și ce n-ar trebui să se schimbe?

**Ce s-ar schimba:**
- **Postgres → warehouse columnar** (ex. Snowflake, BigQuery, ClickHouse). Postgres e un OLTP row-store; agregările pe `mart_monthly_spending` peste sute de milioane de rânduri ar deveni lente. Un columnar store scanează doar coloanele cerute de query, nu rândul întreg — exact profilul de citire al unui mart analitic.
- **Ingest → fișiere brute în object storage (S3/GCS), apoi `COPY`/bulk load în DWH**, nu `INSERT` rând-cu-rând din Python. La 100x volum, network round-trips per rând devin bottleneck-ul; fișierele batch + load nativ al warehouse-ului sunt cu ordine de mărime mai rapide.
- **Airflow local → managed (MWAA, Cloud Composer) sau Kubernetes executor** — `LocalExecutor` cu un singur worker nu paralelizează suficient la sute de task-uri concurente (multe surse × mulți useri); ai nevoie de scaling orizontal pe workeri.
- **`fact_financial_transactions` de la `table` (full refresh) la `incremental` cu `unique_key`** — recalcularea completă zilnică, ok la sute de rânduri, devine ineficientă/costisitoare la scară; modelul incremental procesează doar rândurile noi/schimbate.
- **Metabase H2 → Postgres/MySQL dedicat** — motivul din [Design Decisions](../README.md#design-decisions) pentru H2 (un singur user local, fără concurrency) dispare exact la 100x: mulți useri, dashboard-uri concurente, nevoie de HA.

**Ce NU s-ar schimba — și de ce ăsta e punctul tare:**
- **Modelarea dimensională Kimball** (grain-ul faptului, SCD Type 2 pe categorii, surrogate keys) — schema logică e independentă de motorul fizic. Migrezi `fact_financial_transactions` de pe Postgres pe Snowflake fără să rescrii logica de business, doar sintaxa SQL se poate ajusta marginal.
- **Testele dbt** (unique/not_null/relationships + testele custom de reconciliere sold) — validează *corectitudinea datelor*, nu infrastructura pe care rulează. Aceleași teste, aceeași încredere, indiferent de warehouse.
- **Principiul idempotenței** (dedup pe hash, incremental models, `catchup` controlat) — e un principiu de design, nu o implementare legată de Postgres/Airflow local; se aplică identic pe orice combinație de instrumente la orice scară.

**Concluzie de interviu:** separarea dintre *modelare* (dbt, teste, grain, SCD) și *infrastructură* (Postgres local, LocalExecutor, H2) e exact motivul pentru care proiectul ăsta, construit la scară personală, rămâne un argument valid pentru "știu să gândesc arhitectural", nu doar "am rulat niște containere".
