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

## Extensibilitatea arhitecturii pe o a doua sursă (după Faza 5)

**Întrebarea din CLAUDE.md la Faza 5:** "aici verificăm dacă arhitectura chiar e extensibilă" — adică: cât din ce am construit la Faza 1-2 (o singură sursă, CSV local) se reutilizează neschimbat pentru o a doua sursă (API paginat, cu rate limiting), și unde chiar trebuie o decizie nouă?

**Ce s-a reutilizat identic:**
- Pattern-ul `ParseResult`/`RowParseError` (Faza 1) → `ExtractResult[T]`/`RecordParseError` la GitHub, generic în loc de trei clase separate (Python 3.12, PEP 695).
- Dynamic task mapping în Airflow (`ingest.expand(source=sources)` în `bank_pipeline`) → identic în `github_pipeline` (`ingest_commits_and_pull_requests.expand(repo_full_name=repos)`) — un task per unitate de lucru, în paralel, fără să știi dinainte câte sunt.
- Convenția dbt: `stg_<sursă>__<entitate>`, tag-uri per sursă în `dbt_project.yml`, teste standard (unique/not_null/relationships) + minim un test `dbt_expectations`.

**Ce a trebuit gândit din nou, nu copiat:**
- **Idempotența.** `raw.bank_transactions` deduplică pe un hash de conținut, pentru că un extras CSV n-are nicio cheie naturală — două rânduri identice *sunt* aceeași tranzacție. GitHub are chei naturale reale (`sha`, `repo_id`, `pr_id`), dar asta a scos la iveală o distincție pe care bank n-o avea: unele entități sunt **imuabile** (un commit nu se schimbă niciodată — dedup pe cheie, la fel ca bank) și altele **mutabile** (un PR trece open→merged, un repo capătă un `pushed_at` nou — aici trebuie `UPSERT`, nu `ON CONFLICT DO NOTHING`, altfel `raw` ar îngheța prima stare văzută și ar minți despre starea curentă). Aceeași "idempotență", două implementări SQL diferite, alese pe baza semanticii sursei, nu aplicate mecanic.
- **Grain-ul faptelor.** `fact_financial_transactions` și `fact_daily_productivity` sunt amândouă *sparse* (o tranzacție reală / o zi cu activitate reală), consistent Kimball. Dar mart-ul combinat (`mart_daily_finance_productivity`) trebuia să fie *dense* — o zi fără commit-uri și fără cheltuieli e totuși un punct de date valid pentru o corelație, nu un rând care lipsește. Am aflat asta abia încercând să răspund la întrebarea "există corelații amuzante?" din promptul de proiect: fără zile de zero explicit, orice grafic spending-vs-commits ar fi fost mut pe exact zilele interesante.
- **Ce dimensiune ia SCD2 și ce rămâne Type-1.** `dim_expense_category` are SCD2 (Faza 2) pentru că "ce categorie avea o tranzacție *atunci*" contează pentru orice raport istoric. `dim_repository` a rămas Type-1 (ultima stare, fără istoric) — nu pentru că ar fi imposibil de făcut SCD2, ci pentru că istoricul unui `language`/`pushed_at` de repo nu răspunde la nicio întrebare analitică din acest proiect. SCD2 nu e "mai corect" implicit — e un cost (mai multe rânduri, join-uri pe interval de valabilitate) plătit doar când istoricul chiar e folosit.
- **O singură abstracție nouă, și abia când a apărut duplicarea reală.** `dags/common.py` (alerta Discord + comanda dbt cu tag-uri) a fost extras din `bank_pipeline.py` abia când `github_pipeline.py` a avut nevoie de exact același cod — nu preventiv la Faza 3. E genul de decizie pe care o poți justifica concret: "am dus-o în comun pentru că a doua utilizare a dovedit că era generică, nu pentru că părea o idee bună dinainte".

**Un bug real prins prin testare, nu ipotetic:** cu `GITHUB_TOKEN` setat dar gol în `.env` (variabilă prezentă, valoare goală — nu lipsă), `os.environ["GITHUB_TOKEN"]` nu ridică `KeyError`; eroarea apărea abia mult mai târziu, în `httpx`, ca `LocalProtocolError: Illegal header value b'Bearer '` — tehnic explicită (nimic nu trece silențios), dar inutilă pentru depanare. `GitHubConfig.from_env()` validează acum explicit și golul, nu doar lipsa — aceeași filozofie "fail fast, mesaj clar" ca `SchemaDriftError` de la Faza 1, aplicată de data asta la configurare, nu la parsare.

**Concluzie de interviu:** arhitectura a rezistat — nimic din Faza 1-2 n-a trebuit rescris, doar extins. Dar "extensibil" n-a însemnat "totul identic": punctele unde sursa a doua chiar diferă (mutabilitate, grain, nevoie de istoric) au cerut decizii explicite, nu aplicarea mecanică a patternului de la bank. Ăsta e exact semnul unei abstracții bune: reutilizare acolo unde problema e aceeași, decizie nouă acolo unde nu e.

## Alerte best-effort vs. eșec dur (după feature-ul de alerte financiare)

**De ce am adăugat asta:** planul din CLAUDE.md se oprea la Faza 6 (Strava/Google Fit). Dar autorul nu folosește Strava/Google Fit — o sursă de fitness n-ar fi adus nicio valoare reală, doar un talking point ieftin de "am integrat încă un API". Am ales în schimb să investesc timpul într-un feature pe care chiar îl folosesc: să fiu anunțat când depășesc un buget, am soldul mic sau fac o tranzacție neobișnuit de mare. E și un talking point mai bun, pentru că forțează o distincție pe care un proiect "de portofoliu" pur ar putea s-o rateze.

**Problema de proiectat:** unde pun linia dintre "o eroare aici trebuie să oprească pipeline-ul" și "o eroare aici e doar un eșec izolat, restul rulării rămâne valid"? Proiectul avea deja un precedent — alerta Discord de eșec (`notify_discord_failure`, Faza 3) — dar acolo alerta anunța un eșec *deja produs*; aici alerta e ea însăși partea care poate eșua, în timp ce pipeline-ul de bază (ingest → dbt) a reușit deja.

**Decizia:** `check_alerts` rulează *după* `dbt_test`, nu în paralel și nu înainte — datele trebuie să fie deja validate înainte să verific praguri peste ele, altfel aș putea alerta pe date suspecte. `EmailSender.send()` prinde orice `Exception` (SMTP jos, credențiale greșite, timeout) și doar loghează — task-ul Airflow raportează tot `SUCCESS`. `AlertConfig.from_env()` nu ridică `ValueError` pe SMTP necompletat, spre deosebire de `GitHubConfig.from_env()` (Faza 5), care *chiar* trebuie să oprească ingestul dacă tokenul lipsește.

**De ce nu tratez la fel un test dbt picat și un email netrimis:** un test dbt picat înseamnă că datele din warehouse ar putea fi greșite — soldul nu se reconciliază, o categorie n-are cheie validă. A continua peste asta ar propaga eroarea în orice raportează pe urmă. Un email netrimis nu spune nimic despre corectitudinea datelor — spune doar că eu, utilizatorul, n-am fost anunțat de data asta. Gravitatea diferă, deci și reacția pipeline-ului trebuie să difere; a trata orice eroare la fel de dur ("orice excepție oprește DAG-ul") ar fi mai simplu de scris, dar ar opri un pipeline sănătos din cauza unei probleme de SMTP care n-are nicio legătură cu calitatea datelor.

**Verificat live, nu doar cu teste unitare:** `docker compose --profile airflow up -d --build` (imagine rebuild-uită ca să includă modulul nou), `airflow dags list-import-errors` → none, `airflow tasks list bank_pipeline --tree` → `check_alerts` apare corect după `dbt_test`, `airflow tasks test bank_pipeline check_alerts <data>` → `SUCCESS`, conectat la Postgres-ul real, log structurat JSON, "0 alerte declanșate" (corect — datele sintetice n-au rânduri pe data curentă).

**Concluzie de interviu:** "best-effort" nu e o scuză pentru cod neglijent — e o decizie explicită, cu un motiv (alertarea nu e o precondiție a corectitudinii datelor) și cu o implementare care chiar respectă asta (excepție prinsă explicit, nu propagată din întâmplare). Diferența dintre `dbt_test` (trebuie să oprească pipeline-ul) și `check_alerts` (nu trebuie) nu e "unul e mai important" — e că eșecurile lor înseamnă lucruri fundamental diferite.
