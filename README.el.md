<div align="center">
  <img src="media/logos/full_logo_multiple.png" alt="DiagFlow Logo" width="300" />
</div>

# 🏥 DiagFlow — Αυτοματοποιημένη Μηχανή Ανάθεσης Αναφορών CT/MRI

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/Database-SQLite%20%2F%20MSSQL-003B57.svg)](https://www.sqlite.org/)
[![OR-Tools](https://img.shields.io/badge/Optimization-Google%20OR--Tools-4285F4.svg)](https://developers.google.com/optimization)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)](#-άδεια-χρήσης)

Το **DiagFlow** είναι μια ευφυής μηχανή ανάθεσης διαγνωστικών εξετάσεων και υποστήριξης αποφάσεων, αναπτυγμένη για την **Κοσμοϊατρική**. Αυτοματοποιεί την πολύπλοκη διαδικασία ανάθεσης αναφορών απεικόνισης CT και MRI από το σύστημα Slis της Infomed σε διαγνωστές, χρησιμοποιώντας μια 4-σταδιακή μηχανή κανόνων, δυναμικές δρομολογήσεις, σταθμισμένη πολυπαραγοντική βαθμολόγηση, εξισορρόπηση φορτίου για ισοπαλίες και τον solver CP-SAT της Google OR-Tools για ομαδική βελτιστοποίηση.

> 💡 **Φιλοσοφία Σχεδιασμού:** *Πρότεινε, μην αποφασίζεις.*
> Κάθε πρόταση ανάθεσης συνοδεύεται από πλήρη διαφάνεια — ποιοι κανόνες ενεργοποιήθηκαν, ανάλυση βαθμολογίας ανά παράγοντα και πλήρης ορατότητα των αποκλεισμένων υποψηφίων με ανθρώπινα αναγνώσιμο λόγο απόρριψης. Οι χειριστές της γραμματείας διατηρούν πλήρη εξουσία να επιβεβαιώσουν ή να παρακάμψουν τις προτάσεις με ένα κλικ.

---

## 📋 Πίνακας Περιεχομένων

- [✨ Βασικά Χαρακτηριστικά](#-βασικά-χαρακτηριστικά)
- [🏗️ Αρχιτεκτονική Συστήματος](#️-αρχιτεκτονική-συστήματος)
- [⚙️ Ανάλυση Μηχανής](#️-ανάλυση-μηχανής)
  - [4-Σταδιακή Αγωγός Κανόνων](#1-4-σταδιακή-αγωγός-κανόνων)
  - [Σύστημα Αυτόματης Ανάθεσης](#2-σύστημα-αυτόματης-ανάθεσης)
  - [Αρχιτεκτονική Διπλής Βάσης Δεδομένων](#3-αρχιτεκτονική-διπλής-βάσης-δεδομένων)
  - [Υπηρεσία Αμφίδρομης Συγχρονισμού Slis](#4-υπηρεσία-αμφίδρομης-συγχρονισμού-slis)
- [💻 Διεπαφές Χρήστη](#-διεπαφές-χρήστη)
- [🛠️ Προαπαιτούμενα](#️-προαπαιτούμενα)
- [🚀 Οδηγός Εγκατάστασης και Ρύθμισης](#-οδηγός-εγκατάστασης-και-ρύθμισης)
  - [Επιλογή Α: Εκτέλεση ως Εφαρμογή Web](#επιλογή-α-εκτέλεση-ως-εφαρμογή-web)
  - [Επιλογή Β: Δημιουργία και Εκτέλεση Αυτόνομου Desktop EXE](#επιλογή-β-δημιουργία-και-εκτέλεση-αυτόνομου-desktop-exe)
  - [📦 Ανάπτυξη σε Άλλο PC](#-ανάπτυξη-σε-άλλο-pc)
- [📊 Αρχιτεκτονική Βάσης Δεδομένων και Σχήματα](#-αρχιτεκτονική-βάσης-δεδομένων-και-σχήματα)
- [⚙️ Ρύθμιση και Περιβαλλοντικές Παράμετροι](#️-ρύθμιση-και-περιβαλλοντικές-παράμετροι)
- [📡 Αναφορά API](#-αναφορά-api)
- [📁 Δομή Έργου](#-δομή-έργου)
- [📐 Διαγράμματα Αρχιτεκτονικής PlantUML](#-διαγράμματα-αρχιτεκτονικής-plantuml)
- [📸 Στιγμιότυπα Οθόνης](#-στιγμιότυπα-οθόνης)
- [📄 Άδεια Χρήσης](#-άδεια-χρήσης)

---

## ✨ Βασικά Χαρακτηριστικά

| Τομέας | Χαρακτηριστικό | Περιγραφή |
|--------|----------------|-----------|
| ⚙️ **Μηχανή Κανόνων** | **4-Σταδιακή Αγωγός Αποφάσεων** | Σκληρά φίλτρα → σταθμισμένη βαθμολόγηση → εξισορρόπηση ισοπαλιών → αγωγός solver με 100% διαφάνεια αποφάσεων. |
| 📋 **Ομαδοποίηση Εντολών** | **Συνοχή Ιδίας Εντολής** | Προτείνει τον ίδιο διαγνώστη για όλες τις εξετάσεις που ανήκουν στην ίδια Εντολή (`extracode`) για διαγνωστική συνοχή. |
| 🧮 **Βελτιστοποίηση** | **Google OR-Tools CP-SAT** | Παγκόσμιος solver περιορισμών για ομαδικές αναθέσεις, μεγιστοποιώντας τη βαθμολογία ενώ επιβάλλει καθημερινές χωρητικότητες. |
| ⚖️ **Εξισορρόπηση Φορτίου** | **Εναλλαγή Ισοπαλιών** | Υποψήφιοι εντός ρυθμιζόμενης ανοχής βαθμολογίας (προεπιλογή 5%) κατατάσσονται ανά φόρτο εργασίας. |
| 🔄 **Offset Συνεδρίας** | **Παρακολούθηση Φορτίου σε Πραγματικό Χρόνο** | Παρακολουθεί μη επιβεβαιωμένες προτάσεις εντός ενεργής συνεδρίας για ισοκατανομή φορτίου. |
| ⚡ **Αυτόματες Αναθέσεις** | **Δυναμικοί Κανόνες Δρομολόγησης** | Αναθέτει αυτόματα αποκλειστικές συνεργασίες γιατρού-διαγνωστή, συγκεκριμένους κωδικούς εξετάσεων και τον on-call του Παμμακαρίστου. |
| 🛡️ **Σκληροί Περιορισμοί** | **Δυναμικές Ποσοστώσεις και Εργαστήρια** | Επιβάλλει άδειες, ημερήσιες ποσοστώσεις, όρια CT/MRI, αποκλειστικές αναθέσεις εργαστηρίου και εξειδικεύσεις. |
| 🔄 **Συγχρονισμός Slis** | **Αμφίδρομη Ενσωμάτωση** | Αντλεί μη ανατεθείσες εξετάσεις (τελευταίες 3 ημέρες), ωθεί επιβεβαιωμένες αναθέσεις πίσω, και εκτελεί ημερήσιο cron στις 3 ΠΜ. |
| 🖥️ **Dashboard Γραμματείας** | **Διεπαφή 4 Καρτελών** | Dashboard με καρτέλες εκκρεμών, ανατεθέντων, dashboard και αναζήτησης Slis (εύρος ημερομηνιών [7 μέρες προεπιλογή] & επανάθεση ανά Εντολή, Ασθενή, Γιατρό, Διαγνώστη), άμεσες προτάσεις και ομαδικές ενέργειες. |
| 🔐 **Admin Panel** | **Διαχείριση Ρυθμίσεων** | Πιστοποιημένη διεπαφή για διαχείριση διαγνωστών, εξειδικεύσεων, καταλόγου εξετάσεων & ομαδικής ανάθεσης δεξιοτήτων (καρτέλα Εξετάσεις), συνεργασιών, κανόνων δρομολόγησης και βαρών βαθμολόγησης. |
| 📜 **Ίχνος Ελέγχου** | **Καταγραφή Αποφάσεων** | Πλήρες ιστορικό αναθέσεων, παρακάμψεων και λόγων. |
| 📦 **Desktop App** | **Αυτόνομο EXE** | PyInstaller bundle FastAPI και pywebview για εκτέλεση χωρίς browser. |

---

## 🏗️ Αρχιτεκτονική Συστήματος

Το DiagFlow ακολουθεί αποσυνδεδεμένη, αρθρωτή αρχιτεκτονική που συνδέει τη βάση Slis της Infomed με έναν υψηλής απόδοσης Python FastAPI server, μηχανή βελτιστοποίησης OR-Tools και καθαρές διεπαφές web.

```
                      ┌────────────────────────────────────────┐
                      │    Slis Production DB (MSSQL)          │  <- Παραγωγή (pyodbc)
                      │    mock_slis.db (SQLite)               │  <- Ανάπτυξη
                      └───────────────────┬────────────────────┘
                                   pull / │ \ push
                       ───────────────────┼────────────────────
                                          ▼
                      ┌────────────────────────────────────────┐
                      │        DiagFlow FastAPI Server         │
                      │                                        │
                      │  ┌──────────────────┐  ┌────────────┐  │
                      │  │  Slis Sync Svc   │<─┤APScheduler │  │ (Ημερήσιο Cron 3 ΠΜ)
                      │  └──────────────────┘  └────────────┘  │
                      │  ┌──────────────────────────────────┐  │
                      │  │ Υπηρεσία Ανάθεσης               │  │
                      │  │ Υπηρεσία Διαγνωστή              │  │
                      │  │ Scheduler Παμμακαρίστου          │  │
                      │  └────────────────┬─────────────────┘  │
                      │                   │                    │
                      │  ┌────────────────▼─────────────────┐  │
                      │  │       Αγωγός Μηχανής Κανόνων     │  │
                      │  │ Στάδιο 0: Αποκλειστικά & Routing │  │
                      │  │ Στάδιο 1: Σκληρά Φίλτρα         │  │
                      │  │ Στάδιο 2: Σταθμισμένη Βαθμολογία│  │
                      │  │ Στάδιο 3: Εξισορρόπηση Ισοπαλιών│  │
                      │  │ Στάδιο 4: CP-SAT / Greedy Solver │  │
                      │  └──────────────────────────────────┘  │
                      │  ┌──────────────────────────────────┐  │
                      │  │ diagflow.db (SQLite Config)       │  │
                      │  └──────────────────────────────────┘  │
                      └───────────────────┬────────────────────┘
                                          │ REST API (/api/*)
                                          │ Στατικά Αρχεία (/)
                                          ▼
                      ┌────────────────────────────────────────┐
                      │       Επίπεδο Διεπαφής Χρήστη         │
                      │  • Dashboard Γραμματείας (index.html)  │
                      │  • Admin Panel (admin.html)            │
                      │  • Παράθυρο Desktop (pywebview EXE)   │
                      └────────────────────────────────────────┘
```

---

## ⚙️ Ανάλυση Μηχανής

### 1. 4-Σταδιακή Αγωγός Κανόνων

```
Εκκρεμής Εξέταση
    │
    ├─ Στάδιο 0: Αποκλειστική Συνεργασία ή Κανόνας Δρομολόγησης; ──ναι──► Αυτόματη Ανάθεση
    │
    ▼
Στάδιο 1: Σκληρά Φίλτρα (Διαθεσιμότητα → Χωρητικότητα → Ποσοστώσεις → Υπηρεσία → Εξειδικεύσεις → Αποκλειστικά Εργαστήρια)
    │
    ▼
Στάδιο 2: Σταθμισμένη Βαθμολόγηση (Συνεργασία + Ιστορικό Ασθενή + Bonus Εξειδίκευσης + Προτίμηση Εργαστηρίου + Αναλογία Χωρητικότητας)
    │
    ▼
Στάδιο 3: Εξισορρόπηση Ισοπαλιών (Ομάδα ανοχής βαθμολογίας → ταξινόμηση ανά φόρτο + offset συνεδρίας)
    │
    ▼
Στάδιο 4: Solver (Greedy για μεμονωμένη εξέταση, CP-SAT για ομαδική βελτιστοποίηση)
    │
    ▼
Πρόταση Ανάθεσης + Ανάλυση Βαθμολογίας + Λίστα Εναλλακτικών + Καταγραφή Ελέγχου
```

#### Στάδιο 0: Άμεση Δρομολόγηση και Αποκλειστικές Συνεργασίες
Εξετάσεις που εκδίδονται από γιατρούς με **ενεργή αποκλειστική συνεργασία** ή που ταιριάζουν σε **δυναμικό κανόνα δρομολόγησης** παρακάμπτουν τη βαθμολόγηση και ανατίθενται άμεσα στον διαγνωστή-στόχο.

#### Στάδιο 1: Σκληρά Φίλτρα (Υποχρεωτική Επιτυχία)
Υποψήφιοι που αποτυγχάνουν σε οποιοδήποτε φίλτρο σημειώνονται ως **αποκλεισμένοι**. *Σημαντικό: ΔΕΝ κρύβονται* — εμφανίζονται με κόκκινο πλαίσιο και αναγνώσιμο λόγο απόρριψης.

| Φίλτρο | Περιγραφή | Παράδειγμα Λόγου Απόρριψης |
|--------|-----------|---------------------------|
| `filter_by_exclusive_lab_dynamic` | Έλεγχος αποκλειστικής δέσμευσης εργαστηρίου | `Αποκλειστικό εργαστήριο (ΚΟΛΙΑΤΣΟΥ)` |
| `filter_by_availability` | Επαλήθευση εργασίας σήμερα | `Σε άδεια` / `Εκτός προγράμματος` |
| `filter_by_capacity` | Έλεγχος ημερήσιου ορίου | `Έχει συμπληρώσει το ημερήσιο όριο (15/15)` |
| `filter_by_modality_quotas_dynamic` | Έλεγχος ορίου CT ή MRI | `Έχει συμπληρώσει το όριο (20 CT/ημέρα)` |
| `filter_by_modality` | Έλεγχος δυνατότητας CT/MRI | `Δεν αναλαμβάνει CT` |
| `filter_by_skills_hard` | Αποκλεισμός βάσει εξειδίκευσης | `Δεν διαγιγνώσκει τον συγκεκριμένο κωδικό` |

#### Στάδιο 2: Σταθμισμένη Βαθμολόγηση

$$\text{Συνολική Βαθμολογία} = \sum (\text{Ακατέργαστη Βαθμολογία Παράγοντα} \times \text{Βάρος Παράγοντα})$$

| Παράγοντας | Κλειδί | Προεπιλογή | Περιγραφή |
|-----------|--------|-----------|-----------|
| **Ιστορικό Ασθενή** | `pts_history` | `0.35` | Συνέχεια φροντίδας |
| **Συνεργασία Γιατρού** | `pts_partnership` | `0.20` | Προτιμώμενος διαγνωστής για τον εκδίδοντα γιατρό |
| **Bonus Εξειδίκευσης** | `pts_skills_pref` | `0.20` | Προτίμηση εξειδίκευσης |
| **Προτίμηση Εργαστηρίου** | `pts_lab_pref` | `0.15` | Ταιριάζει στο προτιμώμενο εργαστήριο |
| **Εναπομένουσα Χωρητικότητα** | `pts_capacity` | `0.10` | Αναλογία εναπομενουσών θέσεων |

#### Στάδιο 3: Εξισορρόπηση Φορτίου Ισοπαλιών
Υποψήφιοι εντός `SCORE_TIE_TOLERANCE` (5%) κατατάσσονται ανά:
1. Λιγότερες εξετάσεις σήμερα (plus offset συνεδρίας)
2. Μεγαλύτερη ημερήσια χωρητικότητα
3. Τυχαία διακύμανση (τελικός αποφασιστής)

#### Στάδιο 4: Solver
- **Μεμονωμένη Εξέταση:** Greedy επιλογή Κατάταξης #1.
- **Ομαδική:** CP-SAT solver μεγιστοποιεί τη συνολική συμβατότητα.

---

### 2. Σύστημα Αυτόματης Ανάθεσης

1. **Αποκλειστικές Συνεργασίες:** Ενεργά ζεύγη γιατρού-διαγνωστή ανατίθενται αυτόματα.
2. **Δυναμικοί Κανόνες Δρομολόγησης:** Κωδικοί εξετάσεων (Αρθρογραφίες, Φασματοσκοπίες, TMJ) δρομολογούνται σε εξειδικευμένους διαγνωστές.
3. **On-Call Παμμακαρίστου:** Εξετάσεις από Παμμακάριστο δρομολογούνται στον εφημερεύοντα της ημέρας.

Εμφανίζονται στην καρτέλα **Ανατεθέντες** με σήμανση `AUTO` και περιγραφή κανόνα.

---

### 3. Αρχιτεκτονική Κεντρικής Βάσης Δεδομένων & Ταυτόχρονη Χρήση (Multi-User LAN)

Σε περιβάλλον παραγωγής, το DiagFlow συνδέεται απευθείας στην **Κεντρική Βάση Δεδομένων MSSQL** μέσω του τοπικού δικτύου (LAN). Όλοι οι πίνακες του DiagFlow διατηρούνται στον ίδιο physical server με τους πίνακες του Slis, χρησιμοποιώντας το πρόθεμα `df_*` ώστε να αποκλείεται οποιαδήποτε σύγκρουση ονομάτων. Πολλαπλοί σταθμοί εργασίας γραμματείας και διαχειριστών εκτελούν το `DiagFlow.exe` ταυτόχρονα και παραμένουν πλήρως συγχρονισμένοι σε πραγματικό χρόνο.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│             Κεντρικός Διακομιστής MSSQL (π.χ. server_hostname/SlisDB)       │
├─────────────────────────────────────────────┬───────────────────────────────┤
│          Σχήμα Slis (Εξετάσεις/Διαδικασίες) │    Σχήμα DiagFlow (Πρόθεμα df_)│
├─────────────────────────────────────────────┼───────────────────────────────┤
│ • exammore (ιατρικές εξετάσεις)             │ • df_diagnosticians & skills  │
│ • SP: getExamsListForPeriod_V1              │ • df_partnerships & df_doctors│
│ • SP: getWardDoctors                        │ • df_availability (άδειες)    │
│ • SP: getdiagnosticsList                    │ • df_local_assignments       │
│                                             │ • df_assignment_log (audit)   │
│                                             │ • df_pamakristos_schedule     │
│                                             │ • df_exam_routing_rules       │
│                                             │ • df_exclusive_lab_rules      │
│                                             │ • df_modality_quotas          │
│                                             │ • df_system_settings & admin  │
└─────────────────────────────────────────────┴───────────────────────────────┘
                                ▲                      ▲
                  LAN (pyodbc)  │                      │  LAN (pyodbc)
            ┌───────────────────┴──┐                ┌──┴───────────────────┐
            │  Υπολογιστής 1 (Admin)│                │ Υπολογιστής 2 (Γραμμ.)│
            │     DiagFlow.exe     │                │     DiagFlow.exe     │
            └──────────────────────┘                └──────────────────────┘
```

#### Πλεονεκτήματα Ταυτόχρονης Χρήσης:
- **Άμεση Ενημέρωση Ρυθμίσεων:** Αλλαγές σε άδειες, όρια ή συνεργασίες από το Admin Panel οποιουδήποτε υπολογιστή εφαρμόζονται άμεσα σε όλα τα τερματικά.
- **Κοινόχρηστες Προσωρινές Αναθέσεις (`df_local_assignments`):** Όταν η Γραμματέας Α αναθέτει μια εξέταση, οι υπόλοιποι χρήστες βλέπουν άμεσα τους ενημερωμένους μετρητές και τις εκκρεμότητες.
- **Scripts Δημιουργίας & Αρχικοποίησης:** `db/create_central_tables.sql` (DDL πινάκων) και `db/seed_central_tables.sql` (αρχικά δεδομένα).

---

### 4. Υπηρεσία Αμφίδρομης Συγχρονισμού Slis

- **Άντληση (On-Demand / Εκκίνηση):** Όταν `USE_MOCK_SLIS_DB=false`, εκτελεί τη stored procedure `EXEC getExamsListForPeriod 'YYYY-MM-DD', 'YYYY-MM-DD'` στη βάση Slis MSSQL για άντληση μη ανατεθέντων εξετάσεων (`DIAGNOSTIS IS NULL`) των τελευταίων 3 ημερών.
- **Συγχρονισμός Γιατρών (Εκκίνηση / Ημερήσιο 3 ΠΜ Cron):** Όταν `USE_MOCK_SLIS_DB=false`, εκτελεί τη stored procedure `EXEC getWardDoctors` για συγχρονισμό νέων γιατρών (`CODE`, `DOCNAME`) στον πίνακα `doctors` της βάσης `diagflow.db`.
- **Συγχρονισμός Διαγνωστών (Ανανέωση Admin Panel):** Όταν `USE_MOCK_SLIS_DB=false`, εκτελεί τη stored procedure `EXEC getdiagnosticsList` όταν ο admin πατάει "Ανανέωση" για συγχρονισμό νέων διαγνωστών (`PERSONELID`, `DOCNAME`) στον πίνακα `diagnosticians`.
- **Ώθηση (Χειροκίνητη):** Επιβεβαιωμένες τοπικές αναθέσεις ωθούνται άμεσα στο Slis (`UPDATE exammore SET diagnostisid=? WHERE exammoreid=?`).

---

## 💻 Διεπαφές Χρήστη

### Dashboard Αναθεώρησης Γραμματείας (`index.html`)
- **1. Καρτέλα Εκκρεμών:** Πίνακας μη ανατεθειμένων εξετάσεων, ομαδοποίηση εντολών, αυτόματες προτάσεις, tooltips βαθμολογίας, εναλλακτικές λύσεις και ομαδικές αναθέσεις.
- **2. Καρτέλα Ανατεθέντων:** Ανατεθειμένες εξετάσεις, σήμανση κατάστασης ("✅ Ενημερώθηκε", "⚠️ Εκκρεμεί Ενημέρωση στο Slis"), χειροκίνητη ή ομαδική ώθηση στο Slis, και ετικέτες κανόνων αυτόματης δρομολόγησης.
- **3. Dashboard Ποσοστώσεων:** Ζωντανή επισκόπηση ημερήσιων ορίων, ολοκληρωμένων διαγνώσεων, υπολοίπου χωρητικότητας και ανάλυσης CT/MRI ανά διαγνωστή.
- **4. Αναζήτηση Slis:** Ζωντανή αναζήτηση στη βάση Slis με ειδικά εικονίδια πεδίων (`📋 Εντολή`, `👤 Ασθενής`, `🩺 Παραπέμπων Ιατρός`, `👨‍⚕️ Διαγνώστης`, `📆 Εύρος Ημερομηνιών`), καθαρισμένους τίτλους εξετάσεων, χρωματιστές ετικέτες κατηγορίας (`MRI`, `CT`, `MRA`), παρακολούθηση κατάστασης Slis ("⚠️ Εκκρεμεί Ενημέρωση στο Slis") και διαδραστικό μενού επαναποστολής με έλεγχο εξειδικεύσεων/ορίων σε πραγματικό χρόνο και ταξινόμηση διαθεσίμων στην κορυφή.

> 🔒 **Κανόνας Κλειδώματος Εντολών Multi-exam:** Όλες οι υπο-εξετάσεις που ανήκουν στην ίδια Εντολή (`extracode`) κλειδώνουν αυτόματα στον ίδιο διαγνωστή που συγκεντρώνει τη μεγαλύτερη βαθμολογία, εξασφαλίζοντας 100% συνέπεια διάγνωσης.

### Admin Panel (`admin.html`)
- **Ασφάλεια:** Token-based πιστοποίηση, bcrypt hashing (cost factor 12), περιορισμός ρυθμού IP (5 προσπάθειες/60s).
- **Διαχείριση Διαγνωστών:** Ημερήσια όρια, δυνατότητες CT/MRI, προτιμώμενο εργαστήριο.
- **Μήτρα Εξειδικεύσεων:** Χαρτογράφηση εξειδίκευσης ανά διαγνωστή και κωδικό εξέτασης.
- **Συνεργασίες:** Ζεύγη γιατρού-διαγνωστή και αποκλειστικότητα.
- **Δυναμικοί Κανόνες Δρομολόγησης:** Ρυθμιζόμενοι κανόνες δρομολόγησης εξετάσεων.
- **Αποκλειστικά Εργαστήρια και Ποσοστώσεις Υπηρεσίας:** Αυστηρές δεσμεύσεις και ημερήσια όρια CT/MRI.
- **Ρυθμίσεις Συστήματος:** Προσαρμογή βαρών βαθμολόγησης σε πραγματικό χρόνο.
- **Εβδομαδιαίο Πρόγραμμα Παμμακαρίστου:** Διαδραστικός διαχειριστής εναλλαγής on-call.

---

## 🛠️ Προαπαιτούμενα

- **Python 3.11+**
- **SQLite 3** (ενσωματωμένο στην Python, χωρίς ξεχωριστή εγκατάσταση)
- **ODBC Driver 17 για SQL Server** (για σύνδεση παραγωγής MSSQL Slis)
- **Web Browser** (Chrome, Edge, Firefox ή Safari) για Web mode
- **Windows 10/11** (για αυτόνομη κατασκευή `.exe`)

---

## 🚀 Οδηγός Εγκατάστασης & Εκτέλεσης στο Localhost

### 💻 Εκτέλεση του DiagFlow Τοπικά (Localhost)

Αυτή η ενότητα παρέχει πλήρεις οδηγίες βήμα-προς-βήμα για την εκτέλεση του DiagFlow στο `localhost` (λειτουργία ανάπτυξης & δοκιμών), αναλύοντας όλα τα απαραίτητα αρχεία, τις εντολές αρχικοποίησης, τις επιλογές εκκίνησης διακομιστή και τη λειτουργία δοκιμών.

#### 1. Προαπαιτούμενα & Απαιτήσεις Συστήματος
* **Python 3.10+** (Υποστηρίζονται πλήρως οι εκδόσεις Python 3.11, 3.12, 3.13, 3.14)
* **Git** (για την κλωνοποίηση του αποθετηρίου)
* **Πρόγραμμα περιήγησης Web** (Edge, Chrome, Firefox, Safari) ή **Edge WebView2** (για λειτουργία desktop GUI)

#### 2. Απαραίτητα Αρχεία & Στοιχεία
Πριν την εκκίνηση, βεβαιωθείτε ότι υπάρχουν τα παρακάτω βασικά αρχεία στον κατάλογο του έργου:
* `requirements.txt` — Εξαρτήσεις πακέτων Python
* `.env.example` — Πρότυπο αρχείο ρυθμίσεων περιβάλλοντος
* `src/diagflow/main.py` — Σημείο εισόδου διακομιστή FastAPI & διαδρομές REST API
* `src/diagflow/launcher.py` — Launcher εφαρμογής Desktop GUI (`pywebview`)
* `db/create_diagflow_db.py` — Script αρχικοποίησης βάσης ρυθμίσεων (`db/diagflow.db`)
* `db/seed_mock_db.py` — Script αρχικοποίησης δοκιμαστικής βάσης εξετάσεων SLIS (`db/mock_slis.db`)
* `db/seed_templates.py` — Script δημιουργίας ανώνυμων προτύπων βάσεων (`db/templates/`)
* `frontend/` — Αρχεία HTML/JS/CSS για το Dashboard Γραμματείας και το Admin UI

#### 3. Εντολές Τερματικού Βήμα-προς-Βήμα

##### Βήμα 1: Κλωνοποίηση Αποθετηρίου & Δημιουργία Εικονικού Περιβάλλοντος
```powershell
# Κλωνοποίηση αποθετηρίου
git clone https://github.com/Georgekon4002/diagflow.git
cd diagflow

# Δημιουργία εικονικού περιβάλλοντος Python
python -m venv .venv

# Ενεργοποίηση εικονικού περιβάλλοντος
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Windows (Command Prompt):
.\.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate
```

##### Βήμα 2: Εγκατάσταση Εξαρτήσεων
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

##### Βήμα 3: Δημιουργία Αρχείου Περιβάλλοντος (`.env`)
```powershell
# Αντιγραφή προτύπου περιβάλλοντος
copy .env.example .env    # Windows CMD / PowerShell
# cp .env.example .env     # Linux / macOS
```

Ρυθμίστε το αρχείο `.env`:
```ini
# --- Database Configuration ---
USE_MOCK_SLIS_DB=true
MOCK_SLIS_DB_PATH=db/mock_slis.db
SLIS_DB_CONNECTION_STRING=mssql+pyodbc://diagflow_user:SecurePassword123!@server_hostname/SlisDB?driver=ODBC+Driver+17+for+SQL+Server
CONFIG_DB_CONNECTION_STRING=sqlite:///db/diagflow.db

# --- Rule Engine Weights ---
WEIGHT_PARTNERSHIP=0.35
WEIGHT_PATIENT_HISTORY=0.20
WEIGHT_SKILLS=0.20
WEIGHT_LAB=0.15
WEIGHT_CAPACITY=0.10

# --- Server Settings ---
APP_HOST=127.0.0.1
APP_PORT=8000
LOG_LEVEL=INFO
```

##### Βήμα 4: Αρχικοποίηση Βάσεων Δεδομένων & Δοκιμαστικών Δεδομένων
```powershell
# Ορισμός PYTHONPATH ώστε να περιλαμβάνει τον κατάλογο src/
$env:PYTHONPATH="src"     # Windows PowerShell
# set PYTHONPATH=src      # Windows CMD
# export PYTHONPATH=src   # Linux / macOS

# 1. Δημιουργία & αρχικοποίηση βάσης ρυθμίσεων (db/diagflow.db)
python db/create_diagflow_db.py

# 2. Δημιουργία & αρχικοποίηση δοκιμαστικής βάσης SLIS (db/mock_slis.db)
python db/seed_mock_db.py

# 3. (Προαιρετικό) Δημιουργία & ανανέωση ανώνυμων προτύπων βάσεων (db/templates/*)
python db/seed_templates.py
```
> [!NOTE]
> **Σημείωση Ασφάλειας & Ιδιωτικότητας:** Τα πρωτογενή αρχεία SQL που περιέχουν πραγματικά δεδομένα (`db/init_diagflow.sql` και `db/init_mock_slis.sql`) εξαιρούνται ρητά από το `.gitignore` ώστε να μην ανεβαίνουν ποτέ ευαίσθητα δεδομένα στο GitHub. Τα scripts αρχικοποίησης (`create_diagflow_db.py` & `seed_mock_db.py`) ανιχνεύουν αυτόματα αν λείπουν τα πρωτογενή αρχεία και χρησιμοποιούν ως fallback τα ανωνυμοποιημένα πρότυπα από το `db/templates/`.

##### Βήμα 5: Εκκίνηση Εφαρμογής

###### Επιλογή Α: Διακομιστής Ανάπτυξης Web (Uvicorn + Hot Reloading)
Εκτελεί το FastAPI στο `localhost` με αυτόματη ανανέωση κώδικα:
```powershell
$env:PYTHONPATH="src"
uvicorn diagflow.main:app --reload --host 127.0.0.1 --port 8000
```
Πρόσβαση στις σελίδες μέσω browser:
* **Dashboard Γραμματείας:** [http://localhost:8000](http://localhost:8000)
* **Admin Control Panel:** [http://localhost:8000/admin.html](http://localhost:8000/admin.html)
* **Τεκμηρίωση API (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)

###### Επιλογή Β: Παράθυρο Εφαρμογής Desktop GUI (pywebview Launcher)
Εκκινεί την εφαρμογή σε αυτόνομο παράθυρο Windows desktop:
```powershell
$env:PYTHONPATH="src"
python src/diagflow/launcher.py
```

###### Επιλογή Γ: Κατασκευή & Εκτέλεση Εκτελέσιμου Αρχείου (`DiagFlow.exe`)
Δημιουργεί και εκτελεί το αυτόνομο αρχείο `.exe`:
```powershell
python scripts/build_exe.py
.\dist\DiagFlow.exe
```

##### Βήμα 6: Εκτέλεση Αυτοματοποιημένων Δοκιμών (Pytest)
```powershell
$env:PYTHONPATH="src"
python -m pytest
```

---

### Επιλογή Β: Δημιουργία και Εκτέλεση Αυτόνομου Desktop EXE

#### 1. Κατασκευή Executable

```powershell
python scripts/build_exe.py
```

Παράγει: `dist/DiagFlow.exe`

#### 2. Εκτέλεση Desktop App

```powershell
.\dist\DiagFlow.exe
```

Εκκινεί αυτόματα τον FastAPI server στη θύρα `8080` και ανοίγει το Dashboard σε παράθυρο desktop.

---

### 📦 Ανάπτυξη σε Άλλο PC

#### Αυτόνομο EXE (Ευκολότερο για Τελικούς Χρήστες):
1. Αντιγράψτε το `dist/DiagFlow.exe` στο νέο μηχάνημα.
2. Βεβαιωθείτε ότι ο φάκελος `db/` (με `diagflow.db` και `mock_slis.db`) βρίσκεται στον ίδιο κατάλογο.
3. Διπλό κλικ για εκτέλεση.

#### Web Server (Για Πρόσβαση Δικτύου):
1. Αντιγράψτε ολόκληρο τον κατάλογο `diagflow`.
2. Εγκαταστήστε Python 3.11 και `pip install -r requirements.txt`.
3. Ορίστε `APP_HOST=0.0.0.0` στο `.env`.
4. Εκτελέστε `uvicorn src.diagflow.main:app --host 0.0.0.0 --port 8000`.
5. Πρόσβαση από άλλα PC μέσω `http://<IP_ΣΤΟΧΟΥ>:8000`.

---

## 📊 Αρχιτεκτονική Βάσης Δεδομένων και Σχήματα

### `diagflow.db` (Διαμόρφωση και Κατάσταση Εφαρμογής)

| Πίνακας | Περιγραφή | Κύριο Κλειδί | Βασικές Στήλες |
|---------|-----------|--------------|----------------|
| `diagnosticians` | Κύρια λίστα προσωπικού | `id` (INT) | `name`, `active`, `can_ct`, `can_mri`, `quota_monday..sunday`, `preferred_lab_id` |
| `diagnostician_skills` | Εξειδικεύσεις κωδικών εξετάσεων | `id` (INT) | `diagnostician_id`, `exam_code`, `is_preferred` |
| `partnerships` | Ζεύγη γιατρού-διαγνωστή | `id` (INT) | `issuing_doctor_id`, `preferred_diagnostician_id`, `exclusive`, `is_active` |
| `availability` | Ημερολόγιο αδειών και κατάστασης | `id` (INT) | `diagnostician_id`, `date`, `status`, `is_pamakristos_oncall` |
| `doctors` | Κατάλογος γιατρών | `id` (TEXT) | `name` |
| `local_assignments` | Τοπικές μη ωθημένες αναθέσεις | `exammoreid` (INT) | `diagnostician_id`, `diagnostician_name`, `assigned_at`, `is_auto`, `rule_desc` |
| `assignment_log` | Ίχνος ελέγχου | `exammoreid` (INT) | `diagnostician_id`, `assigned_at`, `modality`, `extracode` |
| `pamakristos_schedule` | Εβδομαδιαία εναλλαγή on-call | `weekday` (INT) | `diagnostician_id` (0=Δευτ .. 6=Κυρ) |
| `exam_routing_rules` | Δυναμικοί κανόνες αυτόματης ανάθεσης | `id` (INT) | `lab_id`, `exam_codes`, `diagnostician_id`, `description`, `is_active` |
| `exclusive_lab_rules` | Αυστηρές δεσμεύσεις εργαστηρίου | `id` (INT) | `diagnostician_id`, `lab_id`, `lab_name`, `is_active` |
| `modality_quotas` | Ειδικά ημερήσια όρια CT/MRI | `id` (INT) | `diagnostician_id`, `modality`, `max_count`, `is_active` |
| `system_settings` | Δυναμικά βάρη παραγόντων βαθμολόγησης | `key` (TEXT) | `value` |

### `mock_slis.db` / Slis MSSQL (Καθρέφτης Δεδομένων Εξετάσεων)

| Πίνακας | Περιγραφή | Κύριο Κλειδί | Βασικές Στήλες |
|---------|-----------|--------------|----------------|
| `slis_exams` | Εκκρεμείς και ανατεθείσες εξετάσεις | `exammoreid` (INT) | `extracode`, `visitdate`, `labcodeid`, `wcode`, `diagnostis`, `slis_synced_at` |
| `exam_categories` | Κατάλογος κωδικών εξετάσεων | `examnumcode` (INT) | `name`, `category` |
| `diagnosticians` | Αναφορά προσωπικού Slis | `PERSONELID` (INT) | `DOCNAME` |
| `doctors` | Αναφορά γιατρών Slis | `CODE` (INT) | `DOCNAME` |

---

## ⚙️ Ρύθμιση και Περιβαλλοντικές Παράμετροι

| Μεταβλητή | Προεπιλογή | Περιγραφή |
|-----------|------------|-----------|
| `USE_MOCK_SLIS_DB` | `true` | Χρήση τοπικής SQLite. Ορίστε `false` για MSSQL παραγωγής. |
| `MOCK_SLIS_DB_PATH` | `db/mock_slis.db` | Σχετική διαδρομή βάσης mock. |
| `SLIS_DB_CONNECTION_STRING` | — | MSSQL ODBC connection string για παραγωγή Slis. |
| `CONFIG_DB_CONNECTION_STRING` | — | MSSQL connection string για ρύθμιση DiagFlow. |
| `SCORE_TIE_TOLERANCE` | `0.05` | Κατώφλι ανοχής βαθμολογίας (5%). |
| `APP_HOST` | `0.0.0.0` | Διεπαφή IP host για δέσμευση server. |
| `APP_PORT` | `8000` | Αριθμός θύρας server. |
| `LOG_LEVEL` | `DEBUG` | Επίπεδο logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

---

## 📡 Αναφορά API

Όλα τα REST API endpoints έχουν πρόθεμα `/api`. Διαδραστική τεκμηρίωση Swagger στο `/docs`.

### 📋 Εξετάσεις
- `GET /api/exams/pending` — Ανάκτηση εκκρεμών εξετάσεων.
- `GET /api/exams/assigned` — Ανάκτηση ανατεθέντων εξετάσεων.

### ⚙️ Μηχανή Ανάθεσης
- `POST /api/assignments/suggest` — Δημιουργία πρότασης ανάθεσης.
- `POST /api/assignments/confirm` — Επιβεβαίωση πρότασης.
- `POST /api/assignments/override` — Παράκαμψη πρότασης.
- `POST /api/assignments/bulk-confirm` — Ομαδική επιβεβαίωση.
- `POST /api/assignments/bulk-override` — Ομαδική παράκαμψη.

### 🔄 Συγχρονισμός Slis
- `POST /api/slis/pull` — Ανανέωση εκκρεμών εξετάσεων.
- `POST /api/slis/push-all` — Ώθηση όλων των αναθέσεων στο Slis.
- `POST /api/slis/push-selected` — Ώθηση επιλεγμένων αναθέσεων.

### 👨‍⚕️ Διαγνωστές και Πρόγραμμα
- `GET /api/diagnosticians` — Λίστα ενεργών διαγνωστών.
- `GET /api/pamakristos/oncall` — Σημερινός εφημερεύων Παμμακαρίστου.
- `GET /api/pamakristos/schedule` — Εβδομαδιαίο πρόγραμμα on-call.
- `POST /api/pamakristos/oncall` — Ορισμός χειροκίνητου on-call.

### 🔐 Admin Panel (Απαιτεί `X-Admin-Token`)
- `POST /api/admin/auth/login` — Πιστοποίηση admin.
- `POST /api/admin/auth/change-credentials` — Αλλαγή διαπιστευτηρίων.
- `GET/POST /api/admin/diagnosticians` — Λίστα / δημιουργία διαγνωστών.
- `PUT/DELETE /api/admin/diagnosticians/{id}` — Ενημέρωση / διαγραφή.
- `GET/POST/DELETE /api/admin/partnerships` — CRUD συνεργασιών.
- `GET/POST/DELETE /api/admin/doctors` — CRUD γιατρών.
- `GET/POST /api/admin/availability` — Διαθεσιμότητα και άδειες.
- `GET/POST/DELETE /api/admin/skills` — CRUD εξειδικεύσεων.
- `GET/POST/DELETE /api/admin/exam-routing-rules` — CRUD κανόνων δρομολόγησης.
- `GET/POST/DELETE /api/admin/exclusive-lab-rules` — CRUD αποκλειστικών εργαστηρίων.
- `GET/POST/DELETE /api/admin/modality-quotas` — CRUD ορίων CT/MRI.
- `GET/POST /api/admin/system-settings` — Βάρη βαθμολόγησης.
- `POST /api/admin/sync-diagnosticians` — Χειροκίνητος συγχρονισμός προσωπικού.
- `POST /api/admin/sync-doctors` — Χειροκίνητος συγχρονισμός γιατρών.

---

## 📁 Δομή Έργου

```
diagflow/
├── README.md
├── README.el.md                       # Ελληνική μετάφραση τεκμηρίωσης
├── USER_GUIDE.md                      # Οδηγός για μη τεχνικούς χρήστες
├── pyproject.toml
├── requirements.txt
├── .env.example
├── DiagFlow.spec
├── db/
│   ├── diagflow.db
│   ├── mock_slis.db
│   ├── init.sql
│   ├── init_diagflow.sql
│   ├── init_mock_slis.sql
│   ├── create_diagflow_db.py
│   └── seed_mock_db.py
├── src/diagflow/
│   ├── main.py
│   ├── config.py
│   ├── launcher.py
│   ├── api/
│   │   ├── routes.py
│   │   ├── schemas.py
│   │   └── dependencies.py
│   ├── db/
│   │   ├── diagflow_db.py
│   │   ├── engines.py
│   │   ├── models.py
│   │   └── slis_models.py
│   ├── engine/
│   │   ├── pipeline.py
│   │   ├── filters.py
│   │   ├── scoring.py
│   │   ├── solver.py
│   │   └── rules.py
│   ├── services/
│   │   ├── assignment.py
│   │   ├── diagnostician.py
│   │   ├── pamakristos.py
│   │   └── slis_sync.py
│   └── utils/
│       └── logging.py
├── frontend/
│   ├── index.html
│   ├── admin.html
│   ├── css/styles.css
│   ├── js/
│   │   ├── app.js
│   │   └── admin.js
│   └── media/
│       └── logos/
├── puml/
├── scripts/
├── tests/
└── docs/
```

---

## 📐 Διαγράμματα Αρχιτεκτονικής PlantUML

| Διάγραμμα | Αρχείο Πηγής | Περιγραφή |
|-----------|--------------|-----------|
| **Αρχιτεκτονική Συστήματος** | [`architecture.puml`](puml/architecture.puml) | Διάγραμμα συστατικών: FastAPI, βάσεις, pywebview, PyInstaller. |
| **Ακολουθία Ανάθεσης** | [`assignment_sequence.puml`](puml/assignment_sequence.puml) | End-to-end ακολουθία suggest, confirm, push. |
| **Κλάσεις: API και Launcher** | [`class_api.puml`](puml/class_api.puml) | Δομικό διάγραμμα routes, schemas, services. |
| **Κλάσεις: Δεδομένα και Μηχανή** | [`data_api.puml`](puml/data_api.puml) | Data access, φίλτρα, scoring, solver. |
| **Μοντέλο Δεδομένων** | [`data_model.puml`](puml/data_model.puml) | Οντότητες και σχέσεις cross-database. |
| **Διάγραμμα ER** | [`er_diagram.puml`](puml/er_diagram.puml) | Πλήρες ER με κλειδιά και περιορισμούς. |
| **Ροή Μηχανής Κανόνων** | [`rule_engine_flow.puml`](puml/rule_engine_flow.puml) | Διάγραμμα δραστηριοτήτων 4 σταδίων. |

---

## 📸 Στιγμιότυπα Οθόνης

### 🖥️ Dashboard Γραμματείας

<div align="center">

| Αρχική Οθόνη (Καρτέλα Εκκρεμών) | Αρχική Οθόνη (Καρτέλα Εκκρεμών — συν.) |
|:---:|:---:|
| ![Αρχική 1](media/screenshots/homescreen1.png) | ![Αρχική 2](media/screenshots/homescreen2.png) |

| Επισκόπηση Dashboard | Αυτόματες Αναθέσεις (Καρτέλα Ανατεθέντων) |
|:---:|:---:|
| ![Dashboard](media/screenshots/dashboard_blurred.png) | ![Αυτόματη Ανάθεση](media/screenshots/auto-assign.png) |

| Φιλτράρισμα και Αναζήτηση | Πολλαπλή Επιλογή |
|:---:|:---:|
| ![Φιλτράρισμα](media/screenshots/filtering.png) | ![Πολλαπλή Επιλογή](media/screenshots/multipleselect.png) |

| Αναζήτηση Slis & Επανάθεση Διαγνώστη (4η Καρτέλα) |  |
|:---:|:---:|
| ![Αναζήτηση Slis](media/screenshots/changediagnostician.png) |  |

</div>

---

### 🧮 Μηχανή Κανόνων και Βαθμολόγηση

<div align="center">

| Παράθυρο Εναλλακτικών | Ανάλυση Συστήματος Βαθμολόγησης |
|:---:|:---:|
| ![Εναλλακτικές](media/screenshots/alternatives_blurred.png) | ![Σύστημα Βαθμολόγησης](media/screenshots/scoring-system.png) |

| Λεπτομέρεια Βαθμολογίας | Διάγραμμα Ροής Ανάθεσης |
|:---:|:---:|
| ![Βαθμολόγηση](media/screenshots/scoring.png) | ![Ροή](media/screenshots/flow.png) |

| Ετικέτα Κανόνα Αυτόματης Ανάθεσης |  |
|:---:|:---:|
| ![Ετικέτα](media/screenshots/red-comment_auto-assign.png) |  |

</div>

---

### 🔐 Admin Control Panel

<div align="center">

| Διαχείριση Διαγνωστών | Ημερολόγιο Διαθεσιμότητας |
|:---:|:---:|
| ![Admin Διαγνωστές](media/screenshots/admin_diagnosticians.png) | ![Admin Διαθεσιμότητα](media/screenshots/admin_availability.png) |

| Μήτρα Εξειδικεύσεων (Θολή) | Μήτρα Εξειδικεύσεων |
|:---:|:---:|
| ![Admin Εξειδικεύσεις 1](media/screenshots/admin_skills1_blurred.png) | ![Admin Εξειδικεύσεις 2](media/screenshots/admin_skills2.png) |

| Συνεργασίες | Πρόγραμμα Παμμακαρίστου |
|:---:|:---:|
| ![Admin Συνεργασίες](media/screenshots/admin_partners.png) | ![Admin Παμμακάριστος](media/screenshots/admin_pammakaristos.png) |

| Κατάλογος Εξετάσεων & Ανατομικές Ομάδες | Ομαδική Επιλογή & Ανάθεση Δεξιοτήτων |
|:---:|:---:|
| ![Admin Εξετάσεις 1](media/screenshots/admin_exams1.png) | ![Admin Εξετάσεις 2](media/screenshots/admin_exams2.png) |

| Επεξεργαστής Κανόνων | Αποκλειστικά Εργαστήρια & Χωρητικότητα ανά Modality |
|:---:|:---:|
| ![Admin Προχωρημένα 1](media/screenshots/admin_advanced1.png) | ![Admin Προχωρημένα 2](media/screenshots/admin_advanced2.png) |

| Επεξεργαστής Βαρών Βαθμολόγησης |  |
|:---:|:---:|
| ![Admin Προχωρημένα 3](media/screenshots/admin_advanced3.png) |  |

</div>

---

## 📄 Άδεια Χρήσης

Εσωτερικό ιδιόκτητο λογισμικό — **Κοσμοϊατρική © 2026**. Με επιφύλαξη παντός δικαιώματος.

---

<div align="center">
  <img src="media/logos/logo_multiple.png" alt="DiagFlow Logo" height="50" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="media/logos/textbox.png" alt="DiagFlow Textbox" height="50" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="media/logos/logo_transparent_crop.png" alt="DiagFlow Transparent Logo" height="50" />
</div>

