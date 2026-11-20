PRAGMA user_version = 18;
BEGIN TRANSACTION;
CREATE TABLE account_currency (
    account_key TEXT PRIMARY KEY,
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    updated_at TEXT NOT NULL
);
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    institution TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL
);
INSERT INTO "accounts" VALUES(1,'popular:credit_card','popular','credit_card','POPULAR VISA PRESTIGE');
INSERT INTO "accounts" VALUES(2,'bhd:credit_card','bhd','credit_card','BHD MC BLACK');
INSERT INTO "accounts" VALUES(3,'bhd:savings:999-1','bhd','savings','BHD Cuenta de ahorro 999-1');
CREATE TABLE budget_caps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL UNIQUE REFERENCES categories(id) ON DELETE CASCADE,
    cap_cents INTEGER CHECK (cap_cents IS NULL OR cap_cents >= 0),
    manual INTEGER NOT NULL DEFAULT 0 CHECK (manual IN (0, 1)),
    basis_cents INTEGER CHECK (basis_cents IS NULL OR basis_cents >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE cards (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    last4 TEXT NOT NULL,
    product TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE (account_id, last4)
);
INSERT INTO "cards" VALUES(1,1,'1234','VISA PRESTIGE','2026-01-13','2026-01-13');
INSERT INTO "cards" VALUES(2,2,'9999','MC BLACK','2026-01-26','2026-01-26');
CREATE TABLE cash_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_key TEXT NOT NULL CHECK (length(account_key) <= 80),
    kind TEXT NOT NULL CHECK (kind IN ('initial', 'income', 'expense')),
    day TEXT NOT NULL CHECK (length(day) = 10),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense', 'transfer')),
    color TEXT CHECK (color IS NULL OR (length(color) = 7 AND color GLOB '#*'
        AND NOT substr(color, 2) GLOB '*[^0-9A-Fa-f]*')),
    hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    builtin INTEGER NOT NULL DEFAULT 0 CHECK (builtin IN (0, 1)),
    builtin_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    CHECK ((builtin = 1) = (builtin_key IS NOT NULL))
);
INSERT INTO "categories" VALUES(1,'Supermercado','expense',NULL,0,1,'GROCERIES','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(2,'Restaurantes','expense',NULL,0,1,'RESTAURANTS','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(3,'Delivery','expense',NULL,0,1,'DELIVERY','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(4,'Transporte','expense',NULL,0,1,'TRANSPORT','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(5,'Vehículo y combustible','expense',NULL,0,1,'VEHICLE','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(6,'Viajes','expense',NULL,0,1,'TRAVEL','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(7,'Compras en línea','expense',NULL,0,1,'ONLINE','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(8,'Courier','expense',NULL,0,1,'COURIER','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(9,'Libros','expense',NULL,0,1,'BOOKS','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(10,'Suscripciones digitales','expense',NULL,0,1,'SUBSCRIPTIONS','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(11,'Servicios (luz, teléfono)','expense',NULL,0,1,'UTILITIES','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(12,'Salud','expense',NULL,0,1,'HEALTH','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(13,'Ropa y tiendas','expense',NULL,0,1,'SHOPPING','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(14,'Hogar y electrónica','expense',NULL,0,1,'HOME','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(15,'Entretenimiento','expense',NULL,0,1,'ENTERTAINMENT','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(16,'Cuidado personal','expense',NULL,0,1,'PERSONAL_CARE','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(17,'Seguros','expense',NULL,0,1,'INSURANCE','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(18,'Gobierno e impuestos','expense',NULL,0,1,'GOVERNMENT','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(19,'Educación','expense',NULL,0,1,'EDUCATION','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(20,'Servicios profesionales','expense',NULL,0,1,'PROFESSIONAL','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(21,'Efectivo','expense',NULL,0,1,'CASH','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(22,'Vivienda','expense',NULL,0,1,'HOUSING','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(23,'Mascotas','expense',NULL,0,1,'PETS','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(24,'Cargos del banco','expense',NULL,0,1,'BANK_FEES','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(25,'Préstamos','expense',NULL,0,1,'LOANS','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(26,'Otros','expense',NULL,0,1,'OTHER','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(27,'Salario','income',NULL,0,1,'SALARY','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(28,'Pagos por servicios','income',NULL,0,1,'SERVICE_PAYMENTS','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(29,'Cripto','income',NULL,0,1,'CRYPTO','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(30,'Otros ingresos','income',NULL,0,1,'OTHER_INCOME','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(31,'Pago de tarjeta','transfer',NULL,0,1,'CARD_PAYMENT','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(32,'Entre mis cuentas','transfer',NULL,0,1,'OWN_TRANSFER','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(33,'Transferencias a terceros','transfer',NULL,0,1,'THIRD_PARTY','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(34,'Reembolso','transfer',NULL,0,1,'REIMBURSEMENT','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(35,'Cambio de divisas','transfer',NULL,0,1,'CURRENCY_EXCHANGE','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(36,'Inversiones','transfer',NULL,0,1,'INVESTMENT','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(37,'Rendimientos','income',NULL,0,1,'INVESTMENT_RETURN','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(38,'Devolución de capital','transfer',NULL,0,1,'INVESTMENT_CAPITAL','2026-11-19T21:22:37+00:00');
INSERT INTO "categories" VALUES(39,'Caja fuerte','transfer',NULL,0,1,'CASH_BOX','2026-11-19T21:22:37+00:00');
CREATE TABLE category_keywords (
    category_id INTEGER NOT NULL REFERENCES categories(id),
    keyword TEXT NOT NULL,
    PRIMARY KEY (category_id, keyword)
);
CREATE TABLE change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    author TEXT NOT NULL CHECK (author IN ('user', 'claude')),
    kind TEXT NOT NULL CHECK (length(kind) BETWEEN 1 AND 40),
    target_type TEXT NOT NULL CHECK (target_type IN ('transaction', 'merchant', 'category', 'link', 'cash_box', 'recurring')),
    target TEXT NOT NULL,
    subject TEXT NOT NULL,
    merchant TEXT,
    before_text TEXT NOT NULL,
    after_text TEXT NOT NULL,
    changes TEXT NOT NULL,
    affected INTEGER NOT NULL CHECK (affected >= 0),
    reason TEXT CHECK (reason IS NULL OR length(reason) <= 500),
    undoes INTEGER REFERENCES change_log(id)
);
INSERT INTO "change_log" VALUES(1,'2026-11-19T21:22:37+00:00','user','shared','link','1','Ana',NULL,'—','reembolso a mano RD$ 30.00','[{"table": "link_manual", "key": {"id": 3}, "before": null, "after": {"id": 3, "link_id": 1, "amount_cents": 3000, "day": "2026-01-05", "person": "Ana", "place": null, "created_at": "2026-11-19T21:22:37.259309+00:00", "currency": "DOP"}, "columns": ["id", "link_id", "amount_cents", "day", "person", "place", "currency"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(2,'2026-11-19T21:22:37+00:00','user','shared','link','1','Ana',NULL,'reembolso a mano RD$ 30.00','—','[{"table": "link_manual", "key": {"id": 3}, "before": {"id": 3, "link_id": 1, "amount_cents": 3000, "day": "2026-01-05", "person": "Ana", "place": null, "created_at": "2026-11-19T21:22:37.259309+00:00", "currency": "DOP"}, "after": null, "columns": ["id", "link_id", "amount_cents", "day", "person", "place", "currency"], "parent": {"key": "links:[1]", "identity": {"kind": "shared", "created_at": "2026-11-19T21:22:37.256581+00:00"}}}]',0,NULL,NULL);
CREATE TABLE change_log_fingerprints (
    entry_id INTEGER NOT NULL REFERENCES change_log(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    PRIMARY KEY (entry_id, fingerprint)
);
CREATE TABLE change_log_rows (
    entry_id INTEGER NOT NULL REFERENCES change_log(id) ON DELETE CASCADE,
    row_key TEXT NOT NULL,
    PRIMARY KEY (entry_id, row_key)
);
INSERT INTO "change_log_rows" VALUES(1,'link_manual:[3]');
INSERT INTO "change_log_rows" VALUES(2,'link_manual:[3]');
CREATE TABLE document_parts (
    document_id INTEGER NOT NULL REFERENCES documents(id),
    part INTEGER NOT NULL CHECK (part >= 1),
    label TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('parsed', 'invalid', 'error', 'duplicate')),
    detail TEXT,
    note TEXT,
    PRIMARY KEY (document_id, part)
);
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES gmail_messages(message_id),
    source TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'parsed', 'invalid', 'error', 'unsupported', 'archived', 'duplicate'
    )),
    parser TEXT,
    detail TEXT,
    processed_at TEXT,
    UNIQUE (message_id, filename)
);
INSERT INTO "documents" VALUES(1,'m0','bank','f.pdf','p','s',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(2,'m1','bank','f.pdf','p','s',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(3,'m2','bank','f.pdf','p','s',1,'z','parsed',NULL,NULL,NULL);
CREATE TABLE exchange_rates (
    month TEXT PRIMARY KEY,
    dop_per_usd TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('bcrd', 'manual')),
    updated_at TEXT NOT NULL
);
INSERT INTO "exchange_rates" VALUES('2025-12','60.0000','bcrd','2026-11-19T21:22:37+00:00');
INSERT INTO "exchange_rates" VALUES('2026-01','61.5000','bcrd','2026-11-19T21:22:37+00:00');
CREATE TABLE gmail_messages (
    message_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT NOT NULL,
    attachments_saved INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);
INSERT INTO "gmail_messages" VALUES('m0','bank','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m1','bank','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m2','bank','x','y','z',1,'z');
CREATE TABLE insights (
    month TEXT PRIMARY KEY
        CHECK (length(month) = 7 AND month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'),
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 4000),
    data_hash TEXT NOT NULL,
    accounts TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE link_manual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    day TEXT NOT NULL,
    person TEXT CHECK (person IS NULL OR length(person) <= 80),
    place TEXT CHECK (place IS NULL OR length(place) <= 80),
    created_at TEXT NOT NULL
, currency TEXT CHECK (currency IS NULL OR currency IN ('DOP', 'USD')));
INSERT INTO "link_manual" VALUES(1,1,2500,'2026-01-03','Ana','Banco Ficticio','2026-11-19T21:22:37.256755+00:00','DOP');
INSERT INTO "link_manual" VALUES(2,4,500,'2026-01-02','Luis',NULL,'2026-11-19T21:22:37.256949+00:00','USD');
CREATE TABLE link_members (
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('expense', 'reimbursement', 'leg', 'contribution', 'return', 'capital', 'mixed', 'stored', 'deposit', 'reserved')),
    added_at TEXT NOT NULL, people INTEGER CHECK (people IS NULL OR people >= 2), my_share_cents INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0), for_other INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1)), capital_cents INTEGER CHECK (capital_cents IS NULL OR capital_cents > 0), box_currency TEXT CHECK (box_currency IS NULL OR box_currency IN ('DOP', 'USD')), box_amount_cents INTEGER CHECK (box_amount_cents IS NULL OR box_amount_cents > 0),
    PRIMARY KEY (link_id, fingerprint)
);
INSERT INTO "link_members" VALUES(1,'9fc4ee521041bb64e055abe0','expense','2026-11-19T21:22:37.256659+00:00',3,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(1,'6cc07dedb56189a5204baa81','reimbursement','2026-11-19T21:22:37.256716+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(2,'14765c23d52eb8ac49415505','expense','2026-11-19T21:22:37.256799+00:00',NULL,NULL,1,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(2,'a169d6d8dad9bd8c5db71158','expense','2026-11-19T21:22:37.256816+00:00',NULL,10000,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(2,'d616417d9961aa551a43b715','reimbursement','2026-11-19T21:22:37.256845+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(3,'46c3922c1a289d0c1e60052d','expense','2026-11-19T21:22:37.256903+00:00',2,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(3,'da2ee4359db0d9274a5f593a','reimbursement','2026-11-19T21:22:37.256915+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(4,'4e01b3e3d7c26c67e1734f35','expense','2026-11-19T21:22:37.256934+00:00',2,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(4,'b104dce876dead324aa19f2d','reimbursement','2026-11-19T21:22:37.256960+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(5,'6f3cdca1db0ea565aac075ca','expense','2026-11-19T21:22:37.256979+00:00',4,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(5,'889859212b46821e63e6560e','reimbursement','2026-11-19T21:22:37.256990+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(6,'0f0f0f0f0f0f0f0f0f0f0f0f','expense','2026-11-19T21:22:37.257008+00:00',2,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(6,'3112e851e5d2ec43822a9db2','reimbursement','2026-11-19T21:22:37.257018+00:00',NULL,NULL,0,NULL,NULL,NULL);
CREATE TABLE links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('shared', 'exchange', 'investment', 'cash_box', 'reserve')),
    people INTEGER CHECK (people IS NULL OR people >= 2),
    my_share_cents INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0),
    for_other INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1)),
    for_whom TEXT CHECK (for_whom IS NULL OR length(for_whom) <= 80),
    written_off INTEGER NOT NULL DEFAULT 0 CHECK (written_off IN (0, 1)),
    agreed_rate TEXT,
    closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, name TEXT CHECK (name IS NULL OR length(name) <= 80), with_whom TEXT CHECK (with_whom IS NULL OR length(with_whom) <= 80), account_key TEXT CHECK (account_key IS NULL OR length(account_key) <= 80), reserve_cents INTEGER CHECK (reserve_cents IS NULL OR reserve_cents > 0), category_id INTEGER, due_month TEXT CHECK (due_month IS NULL OR (length(due_month) = 7 AND due_month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]')), every_months INTEGER CHECK (every_months IS NULL OR every_months BETWEEN 1 AND 12), multiple INTEGER NOT NULL DEFAULT 0 CHECK (multiple IN (0, 1)), source TEXT CHECK (source IS NULL OR length(source) <= 200), start_month TEXT CHECK (start_month IS NULL OR (length(start_month) = 7 AND start_month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]')));
INSERT INTO "links" VALUES(1,'shared',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T21:22:37.256581+00:00','2026-11-19T21:22:37.256581+00:00',NULL,'Ana',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(2,'shared',NULL,NULL,0,NULL,1,NULL,0,'2026-11-19T21:22:37.256786+00:00','2026-11-19T21:22:37.256876+00:00','Casa','Luis y Rosa',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(3,'shared',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T21:22:37.256893+00:00','2026-11-19T21:22:37.256893+00:00',NULL,'Ana',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(4,'shared',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T21:22:37.256926+00:00','2026-11-19T21:22:37.256926+00:00',NULL,'Luis',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(5,'shared',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T21:22:37.256971+00:00','2026-11-19T21:22:37.256971+00:00',NULL,'Rosa, Pedro & Ana',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(6,'shared',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T21:22:37.257000+00:00','2026-11-19T21:22:37.257000+00:00',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
CREATE TABLE merchant_categories (
    merchant TEXT PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    updated_at TEXT NOT NULL
);
CREATE TABLE one_off_dismissals (
    fingerprint TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL
);
CREATE TABLE recurring_marks (
    merchant TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT CHECK (status IN ('confirmed', 'dismissed', 'cancelled')),
    installments_left INTEGER CHECK (installments_left IS NULL OR installments_left >= 0),
    status_on TEXT,
    installments_on TEXT,
    updated_at TEXT NOT NULL, cadence TEXT CHECK (cadence IS NULL OR cadence IN ('monthly', 'yearly')), group_key TEXT CHECK (group_key IS NULL OR length(group_key) <= 40),
    PRIMARY KEY (merchant, currency)
);
CREATE TABLE recurring_unions (
    merchant TEXT PRIMARY KEY CHECK (length(merchant) BETWEEN 1 AND 200),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 200),
    updated_at TEXT NOT NULL
);
CREATE TABLE reserve_dismissals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE CHECK (length(key) BETWEEN 1 AND 200),
    dismissed_at TEXT NOT NULL
);
CREATE TABLE review_marks (
    fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('unusual_income', 'large_third_party', 'duplicate', 'price_up', 'possible_contribution', 'possible_return', 'possible_reserve')),
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY (fingerprint, kind)
);
CREATE TABLE reviewed_fingerprints (
    fingerprint TEXT PRIMARY KEY,
    reviewed_at TEXT NOT NULL
);
CREATE TABLE rule_dismissals (
    merchant TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    dismissed_at TEXT NOT NULL,
    PRIMARY KEY (merchant, category_id)
);
CREATE TABLE statements (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    card_id INTEGER REFERENCES cards(id),
    parser TEXT NOT NULL,
    product TEXT NOT NULL,
    currency TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT NOT NULL,
    due_date TEXT,
    previous_balance_cents INTEGER,
    closing_balance_cents INTEGER,
    minimum_payment_cents INTEGER,
    credit_limit_cents INTEGER,
    printed_debits_cents INTEGER,
    printed_credits_cents INTEGER,
    transaction_count INTEGER
);
INSERT INTO "statements" VALUES(1,1,1,1,'popular_card','VISA PRESTIGE','DOP',NULL,'2026-01-13','2026-02-07',500000,150050,15000,10000000,NULL,NULL,3);
INSERT INTO "statements" VALUES(2,1,1,1,'popular_card','VISA PRESTIGE','USD',NULL,'2026-01-13','2026-02-07',0,2500,2500,200000,NULL,NULL,1);
INSERT INTO "statements" VALUES(3,2,2,2,'bhd_card','MC BLACK','DOP',NULL,'2026-01-26','2026-02-20',100000,250000,12500,10000000,250000,100000,3);
INSERT INTO "statements" VALUES(4,2,2,2,'bhd_card','MC BLACK','USD',NULL,'2026-01-26','2026-02-20',1000,3000,500,200000,3000,1000,2);
INSERT INTO "statements" VALUES(5,3,3,NULL,'bhd_savings','Cuenta de ahorro','DOP',NULL,'2026-01-31',NULL,1000000,1200050,NULL,NULL,300000,500050,3);
CREATE TABLE transaction_notes (
    fingerprint TEXT PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id),
    one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)),
    updated_at TEXT NOT NULL,
    note TEXT CHECK (note IS NULL OR length(note) <= 500)
);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statements(id),
    sequence INTEGER NOT NULL,
    transacted_on TEXT NOT NULL,
    posted_on TEXT,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    currency TEXT NOT NULL,
    reference TEXT,
    mcc TEXT,
    raw_line TEXT NOT NULL,
    UNIQUE (statement_id, sequence)
);
INSERT INTO "transactions" VALUES(1,1,0,'2025-12-14','2025-12-15','COLMADO INVENTADO SANTO DOMINGO',120050,'debit','DOP','11111111111111111111111','5411','15/12 14/12 11111111111111111111111 COLMADO INVENTADO SANTO DOMINGO 1,200.50');
INSERT INTO "transactions" VALUES(2,1,1,'2026-01-01','2026-01-02','CAFE FICTICIO SANTO DOMINGO',30000,'debit','DOP','22222222222222222222222','5814','02/01 01/01 22222222222222222222222 CAFE FICTICIO SANTO DOMINGO 300.00');
INSERT INTO "transactions" VALUES(3,1,2,'2026-01-05','2026-01-05','SU PAGO GRACIAS',500000,'credit','DOP','33333333333333333333333',NULL,'05/01 05/01 33333333333333333333333 SU PAGO GRACIAS -5,000.00');
INSERT INTO "transactions" VALUES(4,2,0,'2025-12-18','2025-12-20','TIENDA ONLINE SEATTLE',2500,'debit','USD','44444444444444444444444','5942','20/12 18/12 44444444444444444444444 TIENDA ONLINE SEATTLE 25.00');
INSERT INTO "transactions" VALUES(5,3,0,'2025-12-28','2025-12-29','SUPERMERCADO FICTICIO SANTO DOMINGO-DO',200000,'debit','DOP',NULL,NULL,'28/12 29/12 9999 SUPERMERCADO FICTICIO SANTO DOMINGO-DO 2,000.00');
INSERT INTO "transactions" VALUES(6,3,1,'2026-01-10','2026-01-11','FARMACIA INVENTADA SANTO DOMINGO-DO',50000,'debit','DOP',NULL,NULL,'10/01 11/01 9999 FARMACIA INVENTADA SANTO DOMINGO-DO 500.00');
INSERT INTO "transactions" VALUES(7,3,2,'2026-01-19','2026-01-19','PAGO DEBITO A CUENTA MBP',100000,'credit','DOP',NULL,NULL,'19/01 19/01 PAGO DEBITO A CUENTA MBP 1,000.00');
INSERT INTO "transactions" VALUES(8,4,0,'2026-01-05','2026-01-06','TIENDA ONLINE SEATTLE-US',3000,'debit','USD',NULL,NULL,'05/01 06/01 9999 TIENDA ONLINE SEATTLE-US 30.00');
INSERT INTO "transactions" VALUES(9,4,1,'2026-01-15','2026-01-15','PAGO DEBITO A CUENTA MBP',1000,'credit','USD',NULL,NULL,'15/01 15/01 PAGO DEBITO A CUENTA MBP 10.00');
INSERT INTO "transactions" VALUES(10,5,0,'2026-01-05',NULL,'TRANSFERENCIA RECIBIDA',500000,'credit','DOP','1234567890',NULL,'05/01 1234567890 TRANSFERENCIA RECIBIDA 5,000.00 15,000.00');
INSERT INTO "transactions" VALUES(11,5,1,'2026-01-10',NULL,'PAGO DE TC 5100 XXXX XXXX 9999',300000,'debit','DOP',NULL,NULL,'10/01 PAGO DE TC 5100 XXXX XXXX 9999 3,000.00 12,000.00');
INSERT INTO "transactions" VALUES(12,5,2,'2026-01-31',NULL,'PAGO INTERESES CA',50,'credit','DOP',NULL,NULL,'31/01 PAGO INTERESES CA 0.50 12,000.50');
INSERT INTO "transactions" VALUES(13,5,3,'2026-01-04',NULL,'TOKE DE PEDRO INVENTADO',5000,'credit','DOP',NULL,NULL,'TOKE DE PEDRO INVENTADO');
INSERT INTO "transactions" VALUES(14,5,4,'2026-01-06',NULL,'TOKE DE LUISA INVENTADA',5000,'credit','DOP',NULL,NULL,'TOKE DE LUISA INVENTADA');
INSERT INTO "transactions" VALUES(15,5,5,'2026-01-07',NULL,'TRANSFERENCIA DE ANA FICTICIA',200000,'credit','DOP',NULL,NULL,'TRANSFERENCIA DE ANA FICTICIA');
INSERT INTO "transactions" VALUES(16,5,6,'2026-01-09',NULL,'TOKE DE ROSA FICTICIA',123457,'credit','DOP',NULL,NULL,'TOKE DE ROSA FICTICIA');
INSERT INTO "transactions" VALUES(17,5,7,'2026-01-12',NULL,'TOKE DE LUIS INVENTADO',40000,'credit','DOP',NULL,NULL,'TOKE DE LUIS INVENTADO');
INSERT INTO "transactions" VALUES(18,5,8,'2026-01-14',NULL,'DEPOSITO DE PRIMA FICTICIA',6000,'debit','DOP',NULL,NULL,'DEPOSITO DE PRIMA FICTICIA');
INSERT INTO "transactions" VALUES(19,5,9,'2026-01-16',NULL,'TOKE DE ANA FICTICIA',777700,'credit','DOP',NULL,NULL,'TOKE DE ANA FICTICIA');
CREATE INDEX documents_sha256 ON documents(sha256);
CREATE UNIQUE INDEX statements_unique_period
    ON statements (account_id, COALESCE(card_id, 0), currency, period_end)
    WHERE parser NOT IN ('popular_web', 'banreservas_partial', 'bhd_savings_partial');
CREATE UNIQUE INDEX statements_unique_printout
    ON statements (
        account_id, currency, COALESCE(period_start, ''), period_end,
        COALESCE(closing_balance_cents, 0), COALESCE(printed_debits_cents, 0),
        COALESCE(printed_credits_cents, 0), COALESCE(transaction_count, 0)
    )
    WHERE parser IN ('popular_web', 'banreservas_partial', 'bhd_savings_partial');
CREATE INDEX change_log_at ON change_log(at);
CREATE INDEX change_log_undoes ON change_log(undoes);
CREATE INDEX change_log_rows_key ON change_log_rows(row_key);
CREATE INDEX change_log_fingerprints_fp ON change_log_fingerprints(fingerprint);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('categories',39);
INSERT INTO "sqlite_sequence" VALUES('links',6);
INSERT INTO "sqlite_sequence" VALUES('link_manual',3);
INSERT INTO "sqlite_sequence" VALUES('change_log',2);
COMMIT;
