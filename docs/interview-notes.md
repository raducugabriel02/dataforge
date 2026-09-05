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

*(de completat)*

## Scalare 100x (după Faza 4)

*(de completat)*
