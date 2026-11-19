-- A database as the previous release (schema 17) wrote it, made with that release's code
-- through its board API (synthetic data from tests/samples.py and tests/e2e_server.py).
-- Loaded by tests/test_schema_v18.py.
BEGIN TRANSACTION;
CREATE TABLE account_currency (
    account_key TEXT PRIMARY KEY,
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    updated_at TEXT NOT NULL
);
INSERT INTO "account_currency" VALUES('manual:caja-fuerte','USD','2026-02-01T12:00:00');
INSERT INTO "account_currency" VALUES('popular:savings:FIC-3','DOP','2026-02-01T12:00:00');
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
INSERT INTO "accounts" VALUES(4,'demo:credit_card','demo','credit_card','DEMO VISA DEMO');
INSERT INTO "accounts" VALUES(5,'ficticio:credit_card','ficticio','credit_card','FICTICIO MASTERCARD FICTICIA');
INSERT INTO "accounts" VALUES(6,'ficticio:checking:777-0','ficticio','checking','FICTICIO Cuenta corriente 777-0');
INSERT INTO "accounts" VALUES(7,'ficticio:savings:888-1','ficticio','savings','FICTICIO Cuenta de ahorro 888-1');
INSERT INTO "accounts" VALUES(8,'hogar:credit_card','hogar','credit_card','HOGAR VISA HOGAR');
INSERT INTO "accounts" VALUES(9,'hogar:checking:999-2','hogar','checking','HOGAR Cuenta de la casa 999-2');
INSERT INTO "accounts" VALUES(10,'hogar:checking:555-3','hogar','checking','HOGAR Cuenta P2P 555-3');
INSERT INTO "accounts" VALUES(11,'manual:caja-fuerte','manual','cash','Caja fuerte');
INSERT INTO "accounts" VALUES(12,'banreservas:savings:FIC-0','banreservas','savings','BANRESERVAS Cuenta ficticia 0 FIC-0');
INSERT INTO "accounts" VALUES(13,'banreservas:savings:FIC-1','banreservas','savings','BANRESERVAS Cuenta ficticia 1 FIC-1');
INSERT INTO "accounts" VALUES(14,'bhd:savings:FIC-2','bhd','savings','BHD Cuenta ficticia 2 FIC-2');
INSERT INTO "accounts" VALUES(15,'popular:savings:FIC-3','popular','savings','POPULAR Cuenta ficticia 3 FIC-3');
INSERT INTO "accounts" VALUES(16,'popular:savings:FIC-4','popular','savings','POPULAR Cuenta ficticia 4 FIC-4');
INSERT INTO "accounts" VALUES(17,'popular:savings:FIC-5','popular','savings','POPULAR Cuenta ficticia 5 FIC-5');
CREATE TABLE budget_caps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL UNIQUE REFERENCES categories(id) ON DELETE CASCADE,
    cap_cents INTEGER CHECK (cap_cents IS NULL OR cap_cents >= 0),
    manual INTEGER NOT NULL DEFAULT 0 CHECK (manual IN (0, 1)),
    basis_cents INTEGER CHECK (basis_cents IS NULL OR basis_cents >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO "budget_caps" VALUES(1,1,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(2,2,100000,0,100000,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(3,3,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(4,4,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(5,5,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(6,6,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(7,7,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(8,8,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(9,9,150000,0,150000,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(10,10,50000,0,50000,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(11,11,200000,0,200000,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(12,12,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(13,13,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(14,14,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(15,15,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(16,16,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(17,17,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(18,18,500000,1,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(19,19,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(20,20,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(21,21,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(22,22,2500000,0,2500000,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(23,23,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(24,24,NULL,0,0,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(25,25,1200000,0,1200000,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
INSERT INTO "budget_caps" VALUES(26,26,1650000,0,1650000,'2026-11-19T05:25:27+00:00','2026-11-19T05:25:27+00:00');
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
INSERT INTO "cards" VALUES(3,4,'4242','VISA DEMO','2026-02-10','2026-02-10');
INSERT INTO "cards" VALUES(4,5,'5151','MASTERCARD FICTICIA','2025-11-28','2026-01-28');
INSERT INTO "cards" VALUES(5,8,'6262','VISA HOGAR','2026-02-10','2026-02-10');
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
INSERT INTO "cash_entries" VALUES(1,'manual:caja-fuerte','initial','2025-12-01',20000,'USD','2026-11-19T05:25:26.687286+00:00','2026-11-19T05:25:26.687286+00:00');
INSERT INTO "cash_entries" VALUES(2,'manual:caja-fuerte','expense','2026-01-05',5000,'USD','2026-11-19T05:25:27.172685+00:00','2026-11-19T05:25:27.172685+00:00');
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL CHECK (kind IN ('ingreso', 'gasto', 'transferencia')),
    color TEXT CHECK (color IS NULL OR (length(color) = 7 AND color GLOB '#*'
        AND NOT substr(color, 2) GLOB '*[^0-9A-Fa-f]*')),
    hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    builtin INTEGER NOT NULL DEFAULT 0 CHECK (builtin IN (0, 1)),
    builtin_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    CHECK ((builtin = 1) = (builtin_key IS NOT NULL))
);
INSERT INTO "categories" VALUES(1,'Supermercado','gasto',NULL,0,1,'GROCERIES','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(2,'Restaurantes','gasto',NULL,0,1,'RESTAURANTS','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(3,'Delivery','gasto',NULL,0,1,'DELIVERY','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(4,'Transporte','gasto',NULL,0,1,'TRANSPORT','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(5,'Vehículo y combustible','gasto',NULL,0,1,'VEHICLE','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(6,'Viajes','gasto',NULL,0,1,'TRAVEL','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(7,'Compras en línea','gasto',NULL,0,1,'ONLINE','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(8,'Courier','gasto',NULL,0,1,'COURIER','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(9,'Libros','gasto',NULL,0,1,'BOOKS','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(10,'Suscripciones digitales','gasto',NULL,0,1,'SUBSCRIPTIONS','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(11,'Servicios (luz, teléfono)','gasto',NULL,0,1,'UTILITIES','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(12,'Salud','gasto',NULL,0,1,'HEALTH','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(13,'Ropa y tiendas','gasto',NULL,0,1,'SHOPPING','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(14,'Hogar y electrónica','gasto',NULL,0,1,'HOME','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(15,'Entretenimiento','gasto',NULL,0,1,'ENTERTAINMENT','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(16,'Cuidado personal','gasto',NULL,0,1,'PERSONAL_CARE','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(17,'Seguros','gasto',NULL,0,1,'INSURANCE','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(18,'Gobierno e impuestos','gasto',NULL,0,1,'GOVERNMENT','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(19,'Educación','gasto',NULL,0,1,'EDUCATION','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(20,'Servicios profesionales','gasto',NULL,0,1,'PROFESSIONAL','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(21,'Efectivo','gasto',NULL,0,1,'CASH','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(22,'Vivienda','gasto',NULL,0,1,'HOUSING','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(23,'Mascotas','gasto',NULL,0,1,'PETS','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(24,'Cargos del banco','gasto',NULL,0,1,'BANK_FEES','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(25,'Préstamos','gasto',NULL,0,1,'LOANS','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(26,'Otros','gasto',NULL,0,1,'OTHER','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(27,'Salario','ingreso',NULL,0,1,'SALARY','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(28,'Pagos por servicios','ingreso',NULL,0,1,'SERVICE_PAYMENTS','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(29,'Cripto','ingreso',NULL,0,1,'CRYPTO','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(30,'Otros ingresos','ingreso',NULL,0,1,'OTHER_INCOME','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(31,'Pago de tarjeta','transferencia',NULL,0,1,'CARD_PAYMENT','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(32,'Entre mis cuentas','transferencia',NULL,0,1,'OWN_TRANSFER','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(33,'Transferencias a terceros','transferencia',NULL,0,1,'THIRD_PARTY','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(34,'Reembolso','transferencia',NULL,0,1,'REIMBURSEMENT','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(35,'Cambio de divisas','transferencia',NULL,0,1,'CURRENCY_EXCHANGE','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(36,'Inversiones','transferencia',NULL,0,1,'INVESTMENT','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(37,'Rendimientos','ingreso',NULL,0,1,'INVESTMENT_RETURN','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(38,'Devolución de capital','transferencia',NULL,0,1,'INVESTMENT_CAPITAL','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(39,'Caja fuerte','transferencia',NULL,0,1,'CASH_BOX','2026-11-19T05:25:26+00:00');
INSERT INTO "categories" VALUES(40,'Mascotas ficticias','transferencia',NULL,0,0,NULL,'2026-11-19T05:25:26+00:00');
CREATE TABLE category_keywords (
    category_id INTEGER NOT NULL REFERENCES categories(id),
    keyword TEXT NOT NULL,
    PRIMARY KEY (category_id, keyword)
);
INSERT INTO "category_keywords" VALUES(40,'VETE FICTICIA');
CREATE TABLE change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    author TEXT NOT NULL CHECK (author IN ('usuario', 'claude')),
    kind TEXT NOT NULL CHECK (length(kind) BETWEEN 1 AND 40),
    target_type TEXT NOT NULL CHECK (target_type IN ('transaccion', 'comercio', 'categoria', 'vinculo', 'caja', 'recurrente')),
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
INSERT INTO "change_log" VALUES(1,'2026-11-19T05:25:26+00:00','usuario','categoria','transaccion','46c3922c1a289d0c1e60052d','COLMADO INVENTADO','COLMADO INVENTADO','Supermercado','Restaurantes','[{"table": "transaction_notes", "key": {"fingerprint": "46c3922c1a289d0c1e60052d"}, "before": null, "after": {"fingerprint": "46c3922c1a289d0c1e60052d", "category_id": 2, "one_off": 0, "updated_at": "2026-11-19T05:25:26+00:00", "note": null}, "columns": ["category_id"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(2,'2026-11-19T05:25:26+00:00','usuario','regla','comercio','ALQUILER FICTICIO','ALQUILER FICTICIO','ALQUILER FICTICIO','sin regla','Vivienda','[{"table": "merchant_categories", "key": {"merchant": "ALQUILER FICTICIO"}, "before": null, "after": {"merchant": "ALQUILER FICTICIO", "category_id": 22, "updated_at": "2026-11-19T05:25:26+00:00"}, "columns": ["merchant", "category_id"], "parent": {}}]',3,NULL,NULL);
INSERT INTO "change_log" VALUES(3,'2026-11-19T05:25:26+00:00','usuario','nota','transaccion','211edaee61cfa76847a0f6a5','SEGURO HOGAR','SEGURO HOGAR','—','Póliza ficticia','[{"table": "transaction_notes", "key": {"fingerprint": "211edaee61cfa76847a0f6a5"}, "before": null, "after": {"fingerprint": "211edaee61cfa76847a0f6a5", "category_id": null, "one_off": 0, "updated_at": "2026-11-19T05:25:26+00:00", "note": "Póliza ficticia"}, "columns": ["note"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(4,'2026-11-19T05:25:26+00:00','claude','gasto_unico','transaccion','31966ff4af5e9d3ea6c0ffbc','TELFIC AGORA','TELFIC AGORA','no','sí','[{"table": "transaction_notes", "key": {"fingerprint": "31966ff4af5e9d3ea6c0ffbc"}, "before": null, "after": {"fingerprint": "31966ff4af5e9d3ea6c0ffbc", "category_id": null, "one_off": 1, "updated_at": "2026-11-19T05:25:26+00:00", "note": null}, "columns": ["one_off"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(5,'2026-11-19T05:25:26+00:00','usuario','categoria_lote','categoria','27','2 transacciones',NULL,'Otros ingresos','Salario','[{"table": "transaction_notes", "key": {"fingerprint": "b3464542fed5c8457d1b32c9"}, "before": null, "after": {"fingerprint": "b3464542fed5c8457d1b32c9", "category_id": 27, "one_off": 0, "updated_at": "2026-11-19T05:25:26+00:00", "note": null}, "columns": ["category_id"], "parent": {}}, {"table": "transaction_notes", "key": {"fingerprint": "9cd2a4aaebd9a95d05ac82bf"}, "before": null, "after": {"fingerprint": "9cd2a4aaebd9a95d05ac82bf", "category_id": 27, "one_off": 0, "updated_at": "2026-11-19T05:25:26+00:00", "note": null}, "columns": ["category_id"], "parent": {}}]',2,'Motivo ficticio',NULL);
INSERT INTO "change_log" VALUES(6,'2026-11-19T05:25:27+00:00','usuario','palabras_clave','categoria','40','Mascotas ficticias',NULL,'—','VETERINARIA FICTICIA','[{"table": "category_keywords", "key": {"category_id": 40, "keyword": "VETERINARIA FICTICIA"}, "before": null, "after": {"category_id": 40, "keyword": "VETERINARIA FICTICIA"}, "columns": ["category_id", "keyword"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(7,'2026-11-19T05:25:27+00:00','usuario','palabras_clave','categoria','40','Mascotas ficticias',NULL,'VETERINARIA FICTICIA','VETE FICTICIA','[{"table": "category_keywords", "key": {"category_id": 40, "keyword": "VETERINARIA FICTICIA"}, "before": {"category_id": 40, "keyword": "VETERINARIA FICTICIA"}, "after": null, "columns": ["category_id", "keyword"], "parent": {"key": "categories:[40]", "identity": {"builtin_key": null, "created_at": "2026-11-19T05:25:26+00:00"}}}, {"table": "category_keywords", "key": {"category_id": 40, "keyword": "VETE FICTICIA"}, "before": null, "after": {"category_id": 40, "keyword": "VETE FICTICIA"}, "columns": ["category_id", "keyword"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(8,'2026-11-19T05:25:27+00:00','usuario','categoria_tipo','categoria','40','Mascotas ficticias',NULL,'gasto','transferencia','[{"table": "categories", "key": {"id": 40}, "before": {"id": 40, "name": "Mascotas ficticias", "kind": "gasto", "color": null, "hidden": 0, "builtin": 0, "builtin_key": null, "created_at": "2026-11-19T05:25:26+00:00"}, "after": {"id": 40, "name": "Mascotas ficticias", "kind": "transferencia", "color": null, "hidden": 0, "builtin": 0, "builtin_key": null, "created_at": "2026-11-19T05:25:26+00:00"}, "columns": ["kind"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(9,'2026-11-19T05:25:27+00:00','usuario','categoria_borrada','categoria','41','Borrable ficticia',NULL,'Borrable ficticia','borrada','[{"table": "categories", "key": {"id": 41}, "before": {"id": 41, "name": "Borrable ficticia", "kind": "gasto", "color": null, "hidden": 0, "builtin": 0, "builtin_key": null, "created_at": "2026-11-19T05:25:27+00:00"}, "after": null, "columns": ["id", "kind", "builtin", "builtin_key"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(10,'2026-11-19T05:25:27+00:00','usuario','compartido','transaccion','4c2a960bf9db1206541c56ba','ASADOR FICTICIO','ASADOR FICTICIO','—','grupo compartido, gasto compartido','[{"table": "links", "key": {"id": 8}, "before": null, "after": {"id": 8, "kind": "shared", "people": null, "my_share_cents": null, "for_other": 0, "for_whom": null, "written_off": 0, "agreed_rate": null, "closed": 0, "created_at": "2026-11-19T05:25:27.116139+00:00", "updated_at": "2026-11-19T05:25:27.116139+00:00", "name": null, "with_whom": null, "account_key": null, "reserve_cents": null, "category_id": null, "due_month": null, "every_months": null, "multiple": 0, "source": null, "start_month": null}, "columns": ["id", "kind", "people", "my_share_cents", "for_other", "for_whom", "written_off", "agreed_rate", "closed", "name", "with_whom", "account_key", "reserve_cents", "category_id", "due_month", "every_months", "multiple", "source", "start_month"], "parent": {}}, {"table": "link_members", "key": {"link_id": 8, "fingerprint": "4c2a960bf9db1206541c56ba"}, "before": null, "after": {"link_id": 8, "fingerprint": "4c2a960bf9db1206541c56ba", "role": "expense", "added_at": "2026-11-19T05:25:27.116255+00:00", "people": 3, "my_share_cents": null, "for_other": 0, "capital_cents": null, "box_currency": null, "box_amount_cents": null}, "columns": ["link_id", "fingerprint", "role", "people", "my_share_cents", "for_other", "capital_cents", "box_currency", "box_amount_cents"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(11,'2026-11-19T05:25:27+00:00','usuario','inversion','vinculo','9','Pedro',NULL,'—','inversión, aporte','[{"table": "links", "key": {"id": 9}, "before": null, "after": {"id": 9, "kind": "investment", "people": null, "my_share_cents": null, "for_other": 0, "for_whom": null, "written_off": 0, "agreed_rate": null, "closed": 0, "created_at": "2026-11-19T05:25:27.139446+00:00", "updated_at": "2026-11-19T05:25:27.139446+00:00", "name": null, "with_whom": "Pedro", "account_key": null, "reserve_cents": null, "category_id": null, "due_month": null, "every_months": null, "multiple": 0, "source": null, "start_month": null}, "columns": ["id", "kind", "people", "my_share_cents", "for_other", "for_whom", "written_off", "agreed_rate", "closed", "name", "with_whom", "account_key", "reserve_cents", "category_id", "due_month", "every_months", "multiple", "source", "start_month"], "parent": {}}, {"table": "link_members", "key": {"link_id": 9, "fingerprint": "22d549a1c6cbb4c701f8e06e"}, "before": null, "after": {"link_id": 9, "fingerprint": "22d549a1c6cbb4c701f8e06e", "role": "contribution", "added_at": "2026-11-19T05:25:27.139557+00:00", "people": null, "my_share_cents": null, "for_other": 0, "capital_cents": null, "box_currency": null, "box_amount_cents": null}, "columns": ["link_id", "fingerprint", "role", "people", "my_share_cents", "for_other", "capital_cents", "box_currency", "box_amount_cents"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(12,'2026-11-19T05:25:27+00:00','usuario','inversion','vinculo','9','Pedro',NULL,'—','rendimiento','[{"table": "link_members", "key": {"link_id": 9, "fingerprint": "ec599575ece00cca8949e1c0"}, "before": null, "after": {"link_id": 9, "fingerprint": "ec599575ece00cca8949e1c0", "role": "return", "added_at": "2026-11-19T05:25:27.159020+00:00", "people": null, "my_share_cents": null, "for_other": 0, "capital_cents": null, "box_currency": null, "box_amount_cents": null}, "columns": ["link_id", "fingerprint", "role", "people", "my_share_cents", "for_other", "capital_cents", "box_currency", "box_amount_cents"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(13,'2026-11-19T05:25:27+00:00','usuario','caja_movimiento','caja','caja-2','Caja fuerte',NULL,'—','salida US$ 50.00 el 2026-01-05, categoría n.º 1','[{"table": "cash_entries", "key": {"id": 2}, "before": null, "after": {"id": 2, "account_key": "manual:caja-fuerte", "kind": "expense", "day": "2026-01-05", "amount_cents": 5000, "currency": "USD", "created_at": "2026-11-19T05:25:27.172685+00:00", "updated_at": "2026-11-19T05:25:27.172685+00:00"}, "columns": ["id", "account_key", "kind", "day", "amount_cents", "currency"], "parent": {}}, {"table": "transaction_notes", "key": {"fingerprint": "caja-2"}, "before": null, "after": {"fingerprint": "caja-2", "category_id": 1, "one_off": 0, "updated_at": "2026-11-19T05:25:27+00:00", "note": null}, "columns": ["category_id"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(14,'2026-11-19T05:25:27+00:00','usuario','nota','transaccion','caja-2','CAJA FUERTE','CAJA FUERTE','—','Efectivo ficticio','[{"table": "transaction_notes", "key": {"fingerprint": "caja-2"}, "before": {"fingerprint": "caja-2", "category_id": 1, "one_off": 0, "updated_at": "2026-11-19T05:25:27+00:00", "note": null}, "after": {"fingerprint": "caja-2", "category_id": 1, "one_off": 0, "updated_at": "2026-11-19T05:25:27+00:00", "note": "Efectivo ficticio"}, "columns": ["note"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(15,'2026-11-19T05:25:27+00:00','usuario','caja_fuerte','transaccion','cfe008585d589c1dee8ac5ef','RETIRO CAJERO SANTO','RETIRO CAJERO SANTO','Efectivo','Caja fuerte','[{"table": "link_members", "key": {"link_id": 7, "fingerprint": "cfe008585d589c1dee8ac5ef"}, "before": null, "after": {"link_id": 7, "fingerprint": "cfe008585d589c1dee8ac5ef", "role": "stored", "added_at": "2026-11-19T05:25:27.221773+00:00", "people": null, "my_share_cents": null, "for_other": 0, "capital_cents": null, "box_currency": null, "box_amount_cents": null}, "columns": ["link_id", "fingerprint", "role", "people", "my_share_cents", "for_other", "capital_cents", "box_currency", "box_amount_cents"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(16,'2026-11-19T05:25:27+00:00','usuario','revisado','transaccion','27fa93d1246b65fe3500492a','AUT PAGO 0000000088','AUT PAGO 0000000088','por revisar','revisado','[{"table": "review_marks", "key": {"fingerprint": "27fa93d1246b65fe3500492a", "kind": "duplicado"}, "before": null, "after": {"fingerprint": "27fa93d1246b65fe3500492a", "kind": "duplicado", "reviewed_at": "2026-11-19T05:25:27+00:00"}, "columns": ["fingerprint", "kind"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(17,'2026-11-19T05:25:27+00:00','usuario','revisado','transaccion','96d1b330a420d10dd8f5e851','MB A 0000000077','MB A 0000000077','por revisar','revisado','[{"table": "review_marks", "key": {"fingerprint": "96d1b330a420d10dd8f5e851", "kind": "tercero_grande"}, "before": null, "after": {"fingerprint": "96d1b330a420d10dd8f5e851", "kind": "tercero_grande", "reviewed_at": "2026-11-19T05:25:27+00:00"}, "columns": ["fingerprint", "kind"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(18,'2026-11-19T05:25:27+00:00','usuario','revisado','transaccion','51a26b7878e6424c0915ebad','LBTR EMPRESA FICTICIA','LBTR EMPRESA FICTICIA','por revisar','revisado','[{"table": "review_marks", "key": {"fingerprint": "51a26b7878e6424c0915ebad", "kind": "ingreso_inusual"}, "before": null, "after": {"fingerprint": "51a26b7878e6424c0915ebad", "kind": "ingreso_inusual", "reviewed_at": "2026-11-19T05:25:27+00:00"}, "columns": ["fingerprint", "kind"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(19,'2026-11-19T05:25:27+00:00','usuario','revisado','transaccion','caja-2','CAJA FUERTE','CAJA FUERTE','por revisar','revisado','[{"table": "review_marks", "key": {"fingerprint": "caja-2", "kind": "subio"}, "before": null, "after": {"fingerprint": "caja-2", "kind": "subio", "reviewed_at": "2026-11-19T05:25:27+00:00"}, "columns": ["fingerprint", "kind"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(20,'2026-11-19T05:25:27+00:00','usuario','revisado','transaccion','22d549a1c6cbb4c701f8e06e','MB A 0000000066','MB A 0000000066','por revisar','revisado','[{"table": "review_marks", "key": {"fingerprint": "22d549a1c6cbb4c701f8e06e", "kind": "aporte_posible"}, "before": null, "after": {"fingerprint": "22d549a1c6cbb4c701f8e06e", "kind": "aporte_posible", "reviewed_at": "2026-11-19T05:25:27+00:00"}, "columns": ["fingerprint", "kind"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(21,'2026-11-19T05:25:27+00:00','usuario','revisado','transaccion','a31ce74e9c41af9490348a73','TRANSF ANA PRESTAMO','TRANSF ANA PRESTAMO','por revisar','revisado','[{"table": "review_marks", "key": {"fingerprint": "a31ce74e9c41af9490348a73", "kind": "cobro_posible"}, "before": null, "after": {"fingerprint": "a31ce74e9c41af9490348a73", "kind": "cobro_posible", "reviewed_at": "2026-11-19T05:25:27+00:00"}, "columns": ["fingerprint", "kind"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(22,'2026-11-19T05:25:27+00:00','usuario','revisado','transaccion','4067a5965945d2ff5b8af70c','MARBETE FICTICIO','MARBETE FICTICIO','por revisar','revisado','[{"table": "review_marks", "key": {"fingerprint": "4067a5965945d2ff5b8af70c", "kind": "reserva_posible"}, "before": null, "after": {"fingerprint": "4067a5965945d2ff5b8af70c", "kind": "reserva_posible", "reviewed_at": "2026-11-19T05:25:27+00:00"}, "columns": ["fingerprint", "kind"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(23,'2026-11-19T05:25:27+00:00','usuario','revisado','transaccion','4067a5965945d2ff5b8af70c','MARBETE FICTICIO','MARBETE FICTICIO','por revisar','no es único','[{"table": "one_off_dismissals", "key": {"fingerprint": "4067a5965945d2ff5b8af70c"}, "before": null, "after": {"fingerprint": "4067a5965945d2ff5b8af70c", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["fingerprint"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(24,'2026-11-19T05:25:27+00:00','usuario','recurrente','recurrente','SEGURO HOGAR · DOP','SEGURO HOGAR','SEGURO HOGAR','—','es recurrente, anual, en Seguros','[{"table": "recurring_marks", "key": {"merchant": "SEGURO HOGAR", "currency": "DOP"}, "before": null, "after": {"merchant": "SEGURO HOGAR", "currency": "DOP", "status": "confirmed", "installments_left": null, "status_on": "2026-02-20", "installments_on": null, "updated_at": "2026-11-19T05:25:27+00:00", "cadence": "anual", "group_key": "seguros"}, "columns": ["merchant", "currency", "status", "installments_left", "status_on", "installments_on", "cadence", "group_key"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(25,'2026-11-19T05:25:27+00:00','usuario','recurrente','recurrente','proveedor:telfic · DOP','Telefónica Ficticia','proveedor:telfic','—','es recurrente, en Suscripciones','[{"table": "recurring_marks", "key": {"merchant": "proveedor:telfic", "currency": "DOP"}, "before": null, "after": {"merchant": "proveedor:telfic", "currency": "DOP", "status": "confirmed", "installments_left": null, "status_on": "2026-02-20", "installments_on": null, "updated_at": "2026-11-19T05:25:27+00:00", "cadence": null, "group_key": "suscripciones"}, "columns": ["merchant", "currency", "status", "installments_left", "status_on", "installments_on", "cadence", "group_key"], "parent": {}}]',4,NULL,NULL);
INSERT INTO "change_log" VALUES(26,'2026-11-19T05:25:27+00:00','usuario','recurrente_union','recurrente','AGUA FICTICIA','AGUA FICTICIA → Acueducto Ficticio',NULL,'—','con Acueducto Ficticio','[{"table": "recurring_unions", "key": {"merchant": "AGUA FICTICIA"}, "before": null, "after": {"merchant": "AGUA FICTICIA", "target": "proveedor:acueducto-ficticio", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["merchant", "target"], "parent": {}}]',3,NULL,NULL);
INSERT INTO "change_log" VALUES(27,'2026-11-19T05:25:27+00:00','usuario','presupuesto','categoria','presupuesto','Presupuesto',NULL,'sin activar','26 categorías, 7 con tope','[{"table": "budget_caps", "key": {"id": 1}, "before": null, "after": {"id": 1, "category_id": 1, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 2}, "before": null, "after": {"id": 2, "category_id": 2, "cap_cents": 100000, "manual": 0, "basis_cents": 100000, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 3}, "before": null, "after": {"id": 3, "category_id": 3, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 4}, "before": null, "after": {"id": 4, "category_id": 4, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 5}, "before": null, "after": {"id": 5, "category_id": 5, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 6}, "before": null, "after": {"id": 6, "category_id": 6, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 7}, "before": null, "after": {"id": 7, "category_id": 7, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 8}, "before": null, "after": {"id": 8, "category_id": 8, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 9}, "before": null, "after": {"id": 9, "category_id": 9, "cap_cents": 150000, "manual": 0, "basis_cents": 150000, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 10}, "before": null, "after": {"id": 10, "category_id": 10, "cap_cents": 50000, "manual": 0, "basis_cents": 50000, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 11}, "before": null, "after": {"id": 11, "category_id": 11, "cap_cents": 200000, "manual": 0, "basis_cents": 200000, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 12}, "before": null, "after": {"id": 12, "category_id": 12, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 13}, "before": null, "after": {"id": 13, "category_id": 13, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 14}, "before": null, "after": {"id": 14, "category_id": 14, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 15}, "before": null, "after": {"id": 15, "category_id": 15, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 16}, "before": null, "after": {"id": 16, "category_id": 16, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 17}, "before": null, "after": {"id": 17, "category_id": 17, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 18}, "before": null, "after": {"id": 18, "category_id": 18, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 19}, "before": null, "after": {"id": 19, "category_id": 19, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 20}, "before": null, "after": {"id": 20, "category_id": 20, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 21}, "before": null, "after": {"id": 21, "category_id": 21, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 22}, "before": null, "after": {"id": 22, "category_id": 22, "cap_cents": 2500000, "manual": 0, "basis_cents": 2500000, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 23}, "before": null, "after": {"id": 23, "category_id": 23, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 24}, "before": null, "after": {"id": 24, "category_id": 24, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 25}, "before": null, "after": {"id": 25, "category_id": 25, "cap_cents": 1200000, "manual": 0, "basis_cents": 1200000, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}, {"table": "budget_caps", "key": {"id": 26}, "before": null, "after": {"id": 26, "category_id": 26, "cap_cents": 1650000, "manual": 0, "basis_cents": 1650000, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["id", "category_id", "cap_cents", "manual", "basis_cents"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(28,'2026-11-19T05:25:27+00:00','usuario','presupuesto','categoria','18','Gobierno e impuestos',NULL,'sin presupuesto','tope RD$ 5,000','[{"table": "budget_caps", "key": {"id": 18}, "before": {"id": 18, "category_id": 18, "cap_cents": null, "manual": 0, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "after": {"id": 18, "category_id": 18, "cap_cents": 500000, "manual": 1, "basis_cents": 0, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["cap_cents", "manual"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(29,'2026-11-19T05:25:27+00:00','usuario','presupuesto_aviso','categoria','2','Restaurantes',NULL,'lo habitual pasó de RD$ 3,000 a RD$ 1,000','tope RD$ 1,000','[{"table": "budget_caps", "key": {"id": 2}, "before": {"id": 2, "category_id": 2, "cap_cents": 100000, "manual": 0, "basis_cents": 300000, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "after": {"id": 2, "category_id": 2, "cap_cents": 100000, "manual": 0, "basis_cents": 100000, "created_at": "2026-11-19T05:25:27+00:00", "updated_at": "2026-11-19T05:25:27+00:00"}, "columns": ["basis_cents"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(30,'2026-11-19T05:25:27+00:00','claude','cambio','vinculo','2','Cambio n.º 2',NULL,'cambio (agreed_rate: 63.1000)','cambio (agreed_rate: 63.2500)','[{"table": "links", "key": {"id": 2}, "before": {"id": 2, "kind": "exchange", "people": null, "my_share_cents": null, "for_other": 0, "for_whom": null, "written_off": 0, "agreed_rate": "63.1000", "closed": 0, "created_at": "2026-11-19T05:25:26.676567+00:00", "updated_at": "2026-11-19T05:25:26.676567+00:00", "name": null, "with_whom": null, "account_key": null, "reserve_cents": null, "category_id": null, "due_month": null, "every_months": null, "multiple": 0, "source": null, "start_month": null}, "after": {"id": 2, "kind": "exchange", "people": null, "my_share_cents": null, "for_other": 0, "for_whom": null, "written_off": 0, "agreed_rate": "63.2500", "closed": 0, "created_at": "2026-11-19T05:25:26.676567+00:00", "updated_at": "2026-11-19T05:25:27.431782+00:00", "name": null, "with_whom": null, "account_key": null, "reserve_cents": null, "category_id": null, "due_month": null, "every_months": null, "multiple": 0, "source": null, "start_month": null}, "columns": ["agreed_rate"], "parent": {}}]',2,NULL,NULL);
INSERT INTO "change_log" VALUES(31,'2026-11-19T05:25:27+00:00','usuario','reserva','vinculo','10','Seguro ficticio',NULL,'—','RD$ 4,800 · cada año en enero','[{"table": "links", "key": {"id": 10}, "before": null, "after": {"id": 10, "kind": "reserve", "people": null, "my_share_cents": null, "for_other": 0, "for_whom": null, "written_off": 0, "agreed_rate": null, "closed": 0, "created_at": "2026-11-19T05:25:27.448525+00:00", "updated_at": "2026-11-19T05:25:27.448525+00:00", "name": "Seguro ficticio", "with_whom": null, "account_key": null, "reserve_cents": 480000, "category_id": 17, "due_month": "2027-01", "every_months": 12, "multiple": 0, "source": "recurrente:SEGURO HOGAR:DOP", "start_month": "2026-02"}, "columns": ["id", "kind", "people", "my_share_cents", "for_other", "for_whom", "written_off", "agreed_rate", "closed", "name", "with_whom", "account_key", "reserve_cents", "category_id", "due_month", "every_months", "multiple", "source", "start_month"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(32,'2026-11-19T05:25:27+00:00','usuario','reserva_gasto','transaccion','211edaee61cfa76847a0f6a5','SEGURO HOGAR','SEGURO HOGAR','—','cubierto por «Seguro ficticio»','[{"table": "link_members", "key": {"link_id": 10, "fingerprint": "211edaee61cfa76847a0f6a5"}, "before": null, "after": {"link_id": 10, "fingerprint": "211edaee61cfa76847a0f6a5", "role": "reserved", "added_at": "2026-11-19T05:25:27.464917+00:00", "people": null, "my_share_cents": null, "for_other": 0, "capital_cents": null, "box_currency": null, "box_amount_cents": null}, "columns": ["link_id", "fingerprint", "role", "people", "my_share_cents", "for_other", "capital_cents", "box_currency", "box_amount_cents"], "parent": {}}]',1,NULL,NULL);
INSERT INTO "change_log" VALUES(33,'2026-11-19T05:25:27+00:00','usuario','reserva','vinculo','11','Telefonía ficticia',NULL,'—','RD$ 1,000 · una vez, en 2026-06','[{"table": "links", "key": {"id": 11}, "before": null, "after": {"id": 11, "kind": "reserve", "people": null, "my_share_cents": null, "for_other": 0, "for_whom": null, "written_off": 0, "agreed_rate": null, "closed": 0, "created_at": "2026-11-19T05:25:27.473473+00:00", "updated_at": "2026-11-19T05:25:27.473473+00:00", "name": "Telefonía ficticia", "with_whom": null, "account_key": null, "reserve_cents": 100000, "category_id": 11, "due_month": "2026-06", "every_months": null, "multiple": 0, "source": "recurrente:proveedor:telfic:DOP", "start_month": "2026-02"}, "columns": ["id", "kind", "people", "my_share_cents", "for_other", "for_whom", "written_off", "agreed_rate", "closed", "name", "with_whom", "account_key", "reserve_cents", "category_id", "due_month", "every_months", "multiple", "source", "start_month"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(34,'2026-11-19T05:25:27+00:00','usuario','reserva_descarte','vinculo','pico:ENTERTAINMENT:12','pico:ENTERTAINMENT:12',NULL,'sugerida','descartada','[{"table": "reserve_dismissals", "key": {"id": 1}, "before": null, "after": {"id": 1, "key": "pico:ENTERTAINMENT:12", "dismissed_at": "2026-11-19T05:25:27.482377+00:00"}, "columns": ["id", "key"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(35,'2026-11-19T05:25:27+00:00','usuario','reserva_descarte','vinculo','recurrente:proveedor:acueducto-ficticio:DOP','recurrente:proveedor:acueducto-ficticio:DOP',NULL,'sugerida','descartada','[{"table": "reserve_dismissals", "key": {"id": 2}, "before": null, "after": {"id": 2, "key": "recurrente:proveedor:acueducto-ficticio:DOP", "dismissed_at": "2026-11-19T05:25:27.491667+00:00"}, "columns": ["id", "key"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(36,'2026-11-19T05:25:27+00:00','usuario','reserva_descarte','vinculo','irregular:Mascotas ficticias','irregular:Mascotas ficticias',NULL,'sugerida','descartada','[{"table": "reserve_dismissals", "key": {"id": 3}, "before": null, "after": {"id": 3, "key": "irregular:Mascotas ficticias", "dismissed_at": "2026-11-19T05:25:27.503101+00:00"}, "columns": ["id", "key"], "parent": {}}]',0,NULL,NULL);
INSERT INTO "change_log" VALUES(37,'2026-11-19T05:25:27+00:00','usuario','nota','transaccion','caja-2','CAJA FUERTE','CAJA FUERTE','Efectivo ficticio','—','[{"table": "transaction_notes", "key": {"fingerprint": "caja-2"}, "before": {"fingerprint": "caja-2", "category_id": 1, "one_off": 0, "updated_at": "2026-11-19T05:25:27+00:00", "note": "Efectivo ficticio"}, "after": {"fingerprint": "caja-2", "category_id": 1, "one_off": 0, "updated_at": "2026-11-19T05:25:27+00:00", "note": null}, "columns": ["note"], "parent": {}}]',1,NULL,14);
INSERT INTO "change_log" VALUES(38,'2026-11-19T05:25:27+00:00','usuario','nota','transaccion','caja-2','CAJA FUERTE','CAJA FUERTE','—','Efectivo ficticio','[{"table": "transaction_notes", "key": {"fingerprint": "caja-2"}, "before": {"fingerprint": "caja-2", "category_id": 1, "one_off": 0, "updated_at": "2026-11-19T05:25:27+00:00", "note": null}, "after": {"fingerprint": "caja-2", "category_id": 1, "one_off": 0, "updated_at": "2026-11-19T05:25:27+00:00", "note": "Efectivo ficticio"}, "columns": ["note"], "parent": {}}]',1,NULL,37);
CREATE TABLE change_log_fingerprints (
    entry_id INTEGER NOT NULL REFERENCES change_log(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    PRIMARY KEY (entry_id, fingerprint)
);
INSERT INTO "change_log_fingerprints" VALUES(1,'46c3922c1a289d0c1e60052d');
INSERT INTO "change_log_fingerprints" VALUES(2,'1e7fe74ef569175c04548191');
INSERT INTO "change_log_fingerprints" VALUES(2,'6e298e5b797058bea5120c12');
INSERT INTO "change_log_fingerprints" VALUES(2,'7078559a89b116110578e2b3');
INSERT INTO "change_log_fingerprints" VALUES(3,'211edaee61cfa76847a0f6a5');
INSERT INTO "change_log_fingerprints" VALUES(4,'31966ff4af5e9d3ea6c0ffbc');
INSERT INTO "change_log_fingerprints" VALUES(5,'9cd2a4aaebd9a95d05ac82bf');
INSERT INTO "change_log_fingerprints" VALUES(5,'b3464542fed5c8457d1b32c9');
INSERT INTO "change_log_fingerprints" VALUES(10,'4c2a960bf9db1206541c56ba');
INSERT INTO "change_log_fingerprints" VALUES(11,'22d549a1c6cbb4c701f8e06e');
INSERT INTO "change_log_fingerprints" VALUES(12,'ec599575ece00cca8949e1c0');
INSERT INTO "change_log_fingerprints" VALUES(13,'caja-2');
INSERT INTO "change_log_fingerprints" VALUES(14,'caja-2');
INSERT INTO "change_log_fingerprints" VALUES(15,'cfe008585d589c1dee8ac5ef');
INSERT INTO "change_log_fingerprints" VALUES(16,'27fa93d1246b65fe3500492a');
INSERT INTO "change_log_fingerprints" VALUES(17,'96d1b330a420d10dd8f5e851');
INSERT INTO "change_log_fingerprints" VALUES(18,'51a26b7878e6424c0915ebad');
INSERT INTO "change_log_fingerprints" VALUES(19,'caja-2');
INSERT INTO "change_log_fingerprints" VALUES(20,'22d549a1c6cbb4c701f8e06e');
INSERT INTO "change_log_fingerprints" VALUES(21,'a31ce74e9c41af9490348a73');
INSERT INTO "change_log_fingerprints" VALUES(22,'4067a5965945d2ff5b8af70c');
INSERT INTO "change_log_fingerprints" VALUES(23,'4067a5965945d2ff5b8af70c');
INSERT INTO "change_log_fingerprints" VALUES(24,'211edaee61cfa76847a0f6a5');
INSERT INTO "change_log_fingerprints" VALUES(25,'661aeb935e4e5cebba7705e4');
INSERT INTO "change_log_fingerprints" VALUES(25,'73eb00db7f87c881388e0e87');
INSERT INTO "change_log_fingerprints" VALUES(25,'b34d99119386b8eb4a9aecb4');
INSERT INTO "change_log_fingerprints" VALUES(25,'d5f6c5cec1cbe805fcce8337');
INSERT INTO "change_log_fingerprints" VALUES(26,'138d340174715b8da9b06a57');
INSERT INTO "change_log_fingerprints" VALUES(26,'7277095a5cda8118ebafbf06');
INSERT INTO "change_log_fingerprints" VALUES(26,'c2e1706da62258f4312e9dbe');
INSERT INTO "change_log_fingerprints" VALUES(30,'7680bbc883e74e658fa1f1f7');
INSERT INTO "change_log_fingerprints" VALUES(30,'c4c0c2e52d190b835e1e5b01');
INSERT INTO "change_log_fingerprints" VALUES(32,'211edaee61cfa76847a0f6a5');
INSERT INTO "change_log_fingerprints" VALUES(37,'caja-2');
INSERT INTO "change_log_fingerprints" VALUES(38,'caja-2');
CREATE TABLE change_log_rows (
    entry_id INTEGER NOT NULL REFERENCES change_log(id) ON DELETE CASCADE,
    row_key TEXT NOT NULL,
    PRIMARY KEY (entry_id, row_key)
);
INSERT INTO "change_log_rows" VALUES(1,'transaction_notes:["46c3922c1a289d0c1e60052d"]');
INSERT INTO "change_log_rows" VALUES(2,'merchant_categories:["ALQUILER FICTICIO"]');
INSERT INTO "change_log_rows" VALUES(3,'transaction_notes:["211edaee61cfa76847a0f6a5"]');
INSERT INTO "change_log_rows" VALUES(4,'transaction_notes:["31966ff4af5e9d3ea6c0ffbc"]');
INSERT INTO "change_log_rows" VALUES(5,'transaction_notes:["b3464542fed5c8457d1b32c9"]');
INSERT INTO "change_log_rows" VALUES(5,'transaction_notes:["9cd2a4aaebd9a95d05ac82bf"]');
INSERT INTO "change_log_rows" VALUES(6,'category_keywords:[40, "VETERINARIA FICTICIA"]');
INSERT INTO "change_log_rows" VALUES(7,'category_keywords:[40, "VETERINARIA FICTICIA"]');
INSERT INTO "change_log_rows" VALUES(7,'category_keywords:[40, "VETE FICTICIA"]');
INSERT INTO "change_log_rows" VALUES(8,'categories:[40]');
INSERT INTO "change_log_rows" VALUES(9,'categories:[41]');
INSERT INTO "change_log_rows" VALUES(10,'links:[8]');
INSERT INTO "change_log_rows" VALUES(10,'link_members:[8, "4c2a960bf9db1206541c56ba"]');
INSERT INTO "change_log_rows" VALUES(11,'links:[9]');
INSERT INTO "change_log_rows" VALUES(11,'link_members:[9, "22d549a1c6cbb4c701f8e06e"]');
INSERT INTO "change_log_rows" VALUES(12,'link_members:[9, "ec599575ece00cca8949e1c0"]');
INSERT INTO "change_log_rows" VALUES(13,'cash_entries:[2]');
INSERT INTO "change_log_rows" VALUES(13,'transaction_notes:["caja-2"]');
INSERT INTO "change_log_rows" VALUES(14,'transaction_notes:["caja-2"]');
INSERT INTO "change_log_rows" VALUES(15,'link_members:[7, "cfe008585d589c1dee8ac5ef"]');
INSERT INTO "change_log_rows" VALUES(16,'review_marks:["27fa93d1246b65fe3500492a", "duplicado"]');
INSERT INTO "change_log_rows" VALUES(17,'review_marks:["96d1b330a420d10dd8f5e851", "tercero_grande"]');
INSERT INTO "change_log_rows" VALUES(18,'review_marks:["51a26b7878e6424c0915ebad", "ingreso_inusual"]');
INSERT INTO "change_log_rows" VALUES(19,'review_marks:["caja-2", "subio"]');
INSERT INTO "change_log_rows" VALUES(20,'review_marks:["22d549a1c6cbb4c701f8e06e", "aporte_posible"]');
INSERT INTO "change_log_rows" VALUES(21,'review_marks:["a31ce74e9c41af9490348a73", "cobro_posible"]');
INSERT INTO "change_log_rows" VALUES(22,'review_marks:["4067a5965945d2ff5b8af70c", "reserva_posible"]');
INSERT INTO "change_log_rows" VALUES(23,'one_off_dismissals:["4067a5965945d2ff5b8af70c"]');
INSERT INTO "change_log_rows" VALUES(24,'recurring_marks:["SEGURO HOGAR", "DOP"]');
INSERT INTO "change_log_rows" VALUES(25,'recurring_marks:["proveedor:telfic", "DOP"]');
INSERT INTO "change_log_rows" VALUES(26,'recurring_unions:["AGUA FICTICIA"]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[1]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[2]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[3]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[4]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[5]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[6]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[7]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[8]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[9]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[10]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[11]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[12]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[13]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[14]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[15]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[16]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[17]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[18]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[19]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[20]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[21]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[22]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[23]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[24]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[25]');
INSERT INTO "change_log_rows" VALUES(27,'budget_caps:[26]');
INSERT INTO "change_log_rows" VALUES(28,'budget_caps:[18]');
INSERT INTO "change_log_rows" VALUES(29,'budget_caps:[2]');
INSERT INTO "change_log_rows" VALUES(30,'links:[2]');
INSERT INTO "change_log_rows" VALUES(31,'links:[10]');
INSERT INTO "change_log_rows" VALUES(32,'link_members:[10, "211edaee61cfa76847a0f6a5"]');
INSERT INTO "change_log_rows" VALUES(33,'links:[11]');
INSERT INTO "change_log_rows" VALUES(34,'reserve_dismissals:[1]');
INSERT INTO "change_log_rows" VALUES(35,'reserve_dismissals:[2]');
INSERT INTO "change_log_rows" VALUES(36,'reserve_dismissals:[3]');
INSERT INTO "change_log_rows" VALUES(37,'transaction_notes:["caja-2"]');
INSERT INTO "change_log_rows" VALUES(38,'transaction_notes:["caja-2"]');
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
INSERT INTO "documents" VALUES(1,'m0','banco','f.pdf','p','s',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(2,'m1','banco','f.pdf','p','s',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(3,'m2','banco','f.pdf','p','s',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(4,'m-demo-0','banco','f.pdf','p','d0',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(5,'m-demo-1','banco','f.pdf','p','d1',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(6,'m-demo-2','banco','f.pdf','p','d2',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(7,'m-demo-3','banco','f.pdf','p','d3',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(8,'m-demo-4','banco','f.pdf','p','d4',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(9,'m-demo-5','banco','f.pdf','p','d5',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(10,'m-demo-6','banco','f.pdf','p','d6',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(11,'m-demo-7','banco','f.pdf','p','d7',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(12,'m-demo-8','banco','f.pdf','p','d8',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(13,'m-demo-9','banco','f.pdf','p','d9',1,'z','parsed',NULL,NULL,NULL);
INSERT INTO "documents" VALUES(14,'importado-00000000000000000000000000000000','importado','estado-0.pdf','raw/importados/2025-11/estado-0.pdf','0000000000000000000000000000000000000000000000000000000000000000',1,'2026-02-01T12:00:00','parsed','banreservas_cuenta',NULL,NULL);
INSERT INTO "documents" VALUES(15,'importado-00000000000000000000000000000001','importado','estado-1.pdf','raw/importados/2025-11/estado-1.pdf','0000000000000000000000000000000000000000000000000000000000000001',1,'2026-02-01T12:00:00','parsed','banreservas_parcial',NULL,NULL);
INSERT INTO "documents" VALUES(16,'importado-00000000000000000000000000000002','importado','estado-2.pdf','raw/importados/2025-11/estado-2.pdf','0000000000000000000000000000000000000000000000000000000000000002',1,'2026-02-01T12:00:00','parsed','bhd_ahorro_parcial',NULL,NULL);
INSERT INTO "documents" VALUES(17,'importado-00000000000000000000000000000003','importado','estado-3.pdf','raw/importados/2025-11/estado-3.pdf','0000000000000000000000000000000000000000000000000000000000000003',1,'2026-02-01T12:00:00','parsed','popular_cuenta',NULL,NULL);
INSERT INTO "documents" VALUES(18,'importado-00000000000000000000000000000004','importado','estado-4.pdf','raw/importados/2025-11/estado-4.pdf','0000000000000000000000000000000000000000000000000000000000000004',1,'2026-02-01T12:00:00','parsed','popular_historico',NULL,NULL);
INSERT INTO "documents" VALUES(19,'importado-00000000000000000000000000000005','importado','estado-5.pdf','raw/importados/2025-11/estado-5.pdf','0000000000000000000000000000000000000000000000000000000000000005',1,'2026-02-01T12:00:00','parsed','popular_web',NULL,NULL);
INSERT INTO "documents" VALUES(20,'generado-e82ffb4d765b07242ef2e343c6e2be70','generado','demo-ficticio.pdf','generado:demo-ficticio.pdf','e82ffb4d765b07242ef2e343c6e2be7066cea2d953bdcc77d782c2128192aba4',18,'2026-02-01T12:00:00','pending',NULL,NULL,NULL);
CREATE TABLE exchange_rates (
    month TEXT PRIMARY KEY,
    dop_per_usd TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('bcrd', 'manual')),
    updated_at TEXT NOT NULL
);
INSERT INTO "exchange_rates" VALUES('2025-12','63.1000','bcrd','2026-11-19T05:25:26+00:00');
INSERT INTO "exchange_rates" VALUES('2026-01','63.4000','bcrd','2026-11-19T05:25:26+00:00');
INSERT INTO "exchange_rates" VALUES('2026-02','63.7000','bcrd','2026-11-19T05:25:26+00:00');
CREATE TABLE gmail_messages (
    message_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT NOT NULL,
    attachments_saved INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);
INSERT INTO "gmail_messages" VALUES('m0','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m1','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m2','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-0','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-1','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-2','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-3','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-4','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-5','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-6','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-7','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-8','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('m-demo-9','banco','x','y','z',1,'z');
INSERT INTO "gmail_messages" VALUES('importado-00000000000000000000000000000000','importado','importación manual','estado-0.pdf','2026-02-01T12:00:00',1,'2026-02-01T12:00:00');
INSERT INTO "gmail_messages" VALUES('importado-00000000000000000000000000000001','importado','importación manual','estado-1.pdf','2026-02-01T12:00:00',1,'2026-02-01T12:00:00');
INSERT INTO "gmail_messages" VALUES('importado-00000000000000000000000000000002','importado','importación manual','estado-2.pdf','2026-02-01T12:00:00',1,'2026-02-01T12:00:00');
INSERT INTO "gmail_messages" VALUES('importado-00000000000000000000000000000003','importado','importación manual','estado-3.pdf','2026-02-01T12:00:00',1,'2026-02-01T12:00:00');
INSERT INTO "gmail_messages" VALUES('importado-00000000000000000000000000000004','importado','importación manual','estado-4.pdf','2026-02-01T12:00:00',1,'2026-02-01T12:00:00');
INSERT INTO "gmail_messages" VALUES('importado-00000000000000000000000000000005','importado','importación manual','estado-5.pdf','2026-02-01T12:00:00',1,'2026-02-01T12:00:00');
INSERT INTO "gmail_messages" VALUES('generado-e82ffb4d765b07242ef2e343c6e2be70','generado','importación manual','demo-ficticio.pdf','2026-02-01T12:00:00',1,'2026-02-01T12:00:00');
CREATE TABLE insights (
    month TEXT PRIMARY KEY
        CHECK (length(month) = 7 AND month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'),
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 4000),
    data_hash TEXT NOT NULL,
    accounts TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO "insights" VALUES('2026-01','Análisis ficticio de enero.','hash-ficticio','manual:caja-fuerte,popular:savings:FIC-3','2026-02-01T12:00:00','2026-02-01T12:00:00');
CREATE TABLE link_manual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    day TEXT NOT NULL,
    person TEXT CHECK (person IS NULL OR length(person) <= 80),
    place TEXT CHECK (place IS NULL OR length(place) <= 80),
    created_at TEXT NOT NULL
, currency TEXT CHECK (currency IS NULL OR currency IN ('DOP', 'USD')));
INSERT INTO "link_manual" VALUES(1,4,217500,'2026-01-10','Marta',NULL,'2026-11-19T05:25:26.681837+00:00','DOP');
CREATE TABLE link_members (
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('expense', 'reimbursement', 'leg', 'contribution', 'return', 'capital', 'mixed', 'stored', 'deposit', 'reserved')),
    added_at TEXT NOT NULL, people INTEGER CHECK (people IS NULL OR people >= 2), my_share_cents INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0), for_other INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1)), capital_cents INTEGER CHECK (capital_cents IS NULL OR capital_cents > 0), box_currency TEXT CHECK (box_currency IS NULL OR box_currency IN ('DOP', 'USD')), box_amount_cents INTEGER CHECK (box_amount_cents IS NULL OR box_amount_cents > 0),
    PRIMARY KEY (link_id, fingerprint)
);
INSERT INTO "link_members" VALUES(1,'cf6b2d28bda4405a6b74ec7d','expense','2026-11-19T05:25:26.676514+00:00',NULL,NULL,1,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(2,'c4c0c2e52d190b835e1e5b01','leg','2026-11-19T05:25:26.676567+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(2,'7680bbc883e74e658fa1f1f7','leg','2026-11-19T05:25:26.676567+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(3,'04e8dc2ca60a0906883547f1','leg','2026-11-19T05:25:26.676644+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(3,'51e9619f52227657f064cff2','leg','2026-11-19T05:25:26.676644+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(4,'e79a58e2b0d0263e01cbfef2','expense','2026-11-19T05:25:26.681757+00:00',2,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(5,'47f6034da7b6f6c5bd980440','expense','2026-11-19T05:25:26.681881+00:00',2,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(6,'96d1b330a420d10dd8f5e851','contribution','2026-11-19T05:25:26.687043+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(6,'a31ce74e9c41af9490348a73','mixed','2026-11-19T05:25:26.687103+00:00',NULL,NULL,0,5000000,NULL,NULL);
INSERT INTO "link_members" VALUES(8,'4c2a960bf9db1206541c56ba','expense','2026-11-19T05:25:27.116255+00:00',3,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(9,'22d549a1c6cbb4c701f8e06e','contribution','2026-11-19T05:25:27.139557+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(9,'ec599575ece00cca8949e1c0','return','2026-11-19T05:25:27.159020+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(7,'cfe008585d589c1dee8ac5ef','stored','2026-11-19T05:25:27.221773+00:00',NULL,NULL,0,NULL,NULL,NULL);
INSERT INTO "link_members" VALUES(10,'211edaee61cfa76847a0f6a5','reserved','2026-11-19T05:25:27.464917+00:00',NULL,NULL,0,NULL,NULL,NULL);
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
INSERT INTO "links" VALUES(1,'shared',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T05:25:26.676440+00:00','2026-11-19T05:25:26.676440+00:00',NULL,'Luis',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(2,'exchange',NULL,NULL,0,NULL,0,'63.2500',0,'2026-11-19T05:25:26.676567+00:00','2026-11-19T05:25:27.431782+00:00',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(3,'exchange',NULL,NULL,0,NULL,0,'63.1000',0,'2026-11-19T05:25:26.676644+00:00','2026-11-19T05:25:26.676644+00:00',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(4,'shared',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T05:25:26.681716+00:00','2026-11-19T05:25:26.681816+00:00','Ropa de Marta','Marta',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(5,'shared',NULL,NULL,0,NULL,1,NULL,0,'2026-11-19T05:25:26.681870+00:00','2026-11-19T05:25:26.681894+00:00',NULL,'Rosa',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(6,'investment',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T05:25:26.686967+00:00','2026-11-19T05:25:26.687118+00:00','Préstamo a Ana','Ana',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(7,'cash_box',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T05:25:26.687240+00:00','2026-11-19T05:25:27.221875+00:00',NULL,NULL,'manual:caja-fuerte',NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(8,'shared',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T05:25:27.116139+00:00','2026-11-19T05:25:27.116139+00:00',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(9,'investment',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T05:25:27.139446+00:00','2026-11-19T05:25:27.159104+00:00',NULL,'Pedro',NULL,NULL,NULL,NULL,NULL,0,NULL,NULL);
INSERT INTO "links" VALUES(10,'reserve',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T05:25:27.448525+00:00','2026-11-19T05:25:27.465017+00:00','Seguro ficticio',NULL,NULL,480000,17,'2027-01',12,0,'recurrente:SEGURO HOGAR:DOP','2026-02');
INSERT INTO "links" VALUES(11,'reserve',NULL,NULL,0,NULL,0,NULL,0,'2026-11-19T05:25:27.473473+00:00','2026-11-19T05:25:27.473473+00:00','Telefonía ficticia',NULL,NULL,100000,11,'2026-06',NULL,0,'recurrente:proveedor:telfic:DOP','2026-02');
CREATE TABLE merchant_categories (
    merchant TEXT PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    updated_at TEXT NOT NULL
);
INSERT INTO "merchant_categories" VALUES('ALQUILER FICTICIO',22,'2026-11-19T05:25:26+00:00');
CREATE TABLE one_off_dismissals (
    fingerprint TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL
);
INSERT INTO "one_off_dismissals" VALUES('4067a5965945d2ff5b8af70c','2026-11-19T05:25:27+00:00');
CREATE TABLE recurring_marks (
    merchant TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT CHECK (status IN ('confirmed', 'dismissed', 'cancelled')),
    installments_left INTEGER CHECK (installments_left IS NULL OR installments_left >= 0),
    status_on TEXT,
    installments_on TEXT,
    updated_at TEXT NOT NULL, cadence TEXT CHECK (cadence IS NULL OR cadence IN ('mensual', 'anual')), group_key TEXT CHECK (group_key IS NULL OR length(group_key) <= 40),
    PRIMARY KEY (merchant, currency)
);
INSERT INTO "recurring_marks" VALUES('MARBETE FICTICIO','DOP','confirmed',NULL,'2026-02-20',NULL,'2026-11-19T05:25:26+00:00','anual',NULL);
INSERT INTO "recurring_marks" VALUES('SEGURO HOGAR','DOP','confirmed',NULL,'2026-02-20',NULL,'2026-11-19T05:25:27+00:00','anual','seguros');
INSERT INTO "recurring_marks" VALUES('proveedor:telfic','DOP','confirmed',NULL,'2026-02-20',NULL,'2026-11-19T05:25:27+00:00',NULL,'suscripciones');
CREATE TABLE recurring_unions (
    merchant TEXT PRIMARY KEY CHECK (length(merchant) BETWEEN 1 AND 200),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 200),
    updated_at TEXT NOT NULL
);
INSERT INTO "recurring_unions" VALUES('AGUA FICTICIA','proveedor:acueducto-ficticio','2026-11-19T05:25:27+00:00');
CREATE TABLE reserve_dismissals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE CHECK (length(key) BETWEEN 1 AND 200),
    dismissed_at TEXT NOT NULL
);
INSERT INTO "reserve_dismissals" VALUES(1,'pico:ENTERTAINMENT:12','2026-11-19T05:25:27.482377+00:00');
INSERT INTO "reserve_dismissals" VALUES(2,'recurrente:proveedor:acueducto-ficticio:DOP','2026-11-19T05:25:27.491667+00:00');
INSERT INTO "reserve_dismissals" VALUES(3,'irregular:Mascotas ficticias','2026-11-19T05:25:27.503101+00:00');
CREATE TABLE review_marks (
    fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('ingreso_inusual', 'tercero_grande', 'duplicado', 'subio', 'aporte_posible', 'cobro_posible', 'reserva_posible')),
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY (fingerprint, kind)
);
INSERT INTO "review_marks" VALUES('27fa93d1246b65fe3500492a','duplicado','2026-11-19T05:25:27+00:00');
INSERT INTO "review_marks" VALUES('96d1b330a420d10dd8f5e851','tercero_grande','2026-11-19T05:25:27+00:00');
INSERT INTO "review_marks" VALUES('51a26b7878e6424c0915ebad','ingreso_inusual','2026-11-19T05:25:27+00:00');
INSERT INTO "review_marks" VALUES('caja-2','subio','2026-11-19T05:25:27+00:00');
INSERT INTO "review_marks" VALUES('22d549a1c6cbb4c701f8e06e','aporte_posible','2026-11-19T05:25:27+00:00');
INSERT INTO "review_marks" VALUES('a31ce74e9c41af9490348a73','cobro_posible','2026-11-19T05:25:27+00:00');
INSERT INTO "review_marks" VALUES('4067a5965945d2ff5b8af70c','reserva_posible','2026-11-19T05:25:27+00:00');
CREATE TABLE reviewed_fingerprints (
    fingerprint TEXT PRIMARY KEY,
    reviewed_at TEXT NOT NULL
);
INSERT INTO "reviewed_fingerprints" VALUES('caja-2','2026-02-01T12:00:00');
INSERT INTO "reviewed_fingerprints" VALUES('211edaee61cfa76847a0f6a5','2026-02-01T12:00:00');
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
INSERT INTO "statements" VALUES(1,1,1,1,'popular_tc','VISA PRESTIGE','DOP',NULL,'2026-01-13','2026-02-07',500000,150050,15000,10000000,NULL,NULL,3);
INSERT INTO "statements" VALUES(2,1,1,1,'popular_tc','VISA PRESTIGE','USD',NULL,'2026-01-13','2026-02-07',0,2500,2500,200000,NULL,NULL,1);
INSERT INTO "statements" VALUES(3,2,2,2,'bhd_tc','MC BLACK','DOP',NULL,'2026-01-26','2026-02-20',100000,250000,12500,10000000,250000,100000,3);
INSERT INTO "statements" VALUES(4,2,2,2,'bhd_tc','MC BLACK','USD',NULL,'2026-01-26','2026-02-20',1000,3000,500,200000,3000,1000,2);
INSERT INTO "statements" VALUES(5,3,3,NULL,'bhd_ahorro','Cuenta de ahorro','DOP',NULL,'2026-01-31',NULL,1000000,1200050,NULL,NULL,300000,500050,3);
INSERT INTO "statements" VALUES(6,4,4,3,'demo','VISA DEMO','DOP',NULL,'2026-02-10','2026-03-05',0,7421375,50000,8000000,7421375,0,13);
INSERT INTO "statements" VALUES(7,4,4,3,'demo','VISA DEMO','USD',NULL,'2026-02-10','2026-03-05',0,3197,2500,NULL,3197,0,3);
INSERT INTO "statements" VALUES(8,5,5,4,'demo','MASTERCARD FICTICIA','DOP',NULL,'2025-11-28','2025-12-23',600000,600000,30000,5000000,0,0,0);
INSERT INTO "statements" VALUES(9,6,5,4,'demo','MASTERCARD FICTICIA','DOP',NULL,'2025-12-28','2026-01-22',600000,1415000,71000,5000000,1415000,600000,3);
INSERT INTO "statements" VALUES(10,7,5,4,'demo','MASTERCARD FICTICIA','DOP',NULL,'2026-01-28','2026-02-22',1415000,763740,38000,5000000,148740,800000,3);
INSERT INTO "statements" VALUES(11,8,6,NULL,'demo','Cuenta corriente','DOP',NULL,'2026-01-31',NULL,2000000,18400000,NULL,NULL,1800000,18200000,7);
INSERT INTO "statements" VALUES(12,9,6,NULL,'demo','Cuenta corriente','DOP','2026-02-01','2026-02-15',NULL,18400000,25296075,NULL,NULL,0,6896075,4);
INSERT INTO "statements" VALUES(13,9,6,NULL,'demo','Cuenta corriente','USD','2026-02-01','2026-02-15',NULL,500000,393833,NULL,NULL,106167,0,2);
INSERT INTO "statements" VALUES(14,10,7,NULL,'demo','Cuenta de ahorro','DOP','2025-12-01','2026-02-15',NULL,60000000,25688000,NULL,NULL,48305000,13993000,9);
INSERT INTO "statements" VALUES(15,10,7,NULL,'demo','Cuenta de ahorro','USD','2025-12-01','2026-02-15',NULL,200000,230000,NULL,NULL,10000,40000,2);
INSERT INTO "statements" VALUES(16,11,8,5,'demo','VISA HOGAR','DOP',NULL,'2026-02-10','2026-03-05',0,9685000,90000,15000000,9685000,0,14);
INSERT INTO "statements" VALUES(17,12,9,NULL,'demo','Cuenta de la casa','DOP','2025-12-01','2026-02-15',NULL,20000000,13400000,NULL,NULL,6600000,0,4);
INSERT INTO "statements" VALUES(18,13,10,NULL,'demo','Cuenta P2P','DOP','2025-12-01','2026-02-15',NULL,100000,4250000,NULL,NULL,0,4150000,4);
INSERT INTO "statements" VALUES(19,14,12,NULL,'banreservas_cuenta','Cuenta ficticia 0','DOP','2025-11-01','2025-11-30',NULL,100000,90000,NULL,NULL,10000,0,1);
INSERT INTO "statements" VALUES(20,15,13,NULL,'banreservas_parcial','Cuenta ficticia 1','DOP','2025-11-01','2025-11-30',NULL,100000,90000,NULL,NULL,10000,0,1);
INSERT INTO "statements" VALUES(21,16,14,NULL,'bhd_ahorro_parcial','Cuenta ficticia 2','DOP','2025-11-01','2025-11-30',NULL,100000,90000,NULL,NULL,10000,0,1);
INSERT INTO "statements" VALUES(22,17,15,NULL,'popular_cuenta','Cuenta ficticia 3','DOP','2025-11-01','2025-11-30',NULL,100000,90000,NULL,NULL,10000,0,1);
INSERT INTO "statements" VALUES(23,18,16,NULL,'popular_historico','Cuenta ficticia 4','DOP','2025-11-01','2025-11-30',NULL,100000,90000,NULL,NULL,10000,0,1);
INSERT INTO "statements" VALUES(24,19,17,NULL,'popular_web','Cuenta ficticia 5','DOP','2025-11-01','2025-11-30',NULL,100000,90000,NULL,NULL,10000,0,1);
CREATE TABLE transaction_notes (
    fingerprint TEXT PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id),
    one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)),
    updated_at TEXT NOT NULL,
    note TEXT CHECK (note IS NULL OR length(note) <= 500)
);
INSERT INTO "transaction_notes" VALUES('04e8dc2ca60a0906883547f1',NULL,0,'2026-11-19T05:25:26+00:00','Cambio con Pedro');
INSERT INTO "transaction_notes" VALUES('46c3922c1a289d0c1e60052d',2,0,'2026-11-19T05:25:26+00:00',NULL);
INSERT INTO "transaction_notes" VALUES('211edaee61cfa76847a0f6a5',NULL,0,'2026-11-19T05:25:26+00:00','Póliza ficticia');
INSERT INTO "transaction_notes" VALUES('31966ff4af5e9d3ea6c0ffbc',NULL,1,'2026-11-19T05:25:26+00:00',NULL);
INSERT INTO "transaction_notes" VALUES('b3464542fed5c8457d1b32c9',27,0,'2026-11-19T05:25:26+00:00',NULL);
INSERT INTO "transaction_notes" VALUES('9cd2a4aaebd9a95d05ac82bf',27,0,'2026-11-19T05:25:26+00:00',NULL);
INSERT INTO "transaction_notes" VALUES('caja-2',1,0,'2026-11-19T05:25:27+00:00','Efectivo ficticio');
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
INSERT INTO "transactions" VALUES(13,6,0,'2026-01-20','2026-01-20','RESTAURANTE INVENTADO SANTO DOMINGO',185000,'debit','DOP',NULL,NULL,'2026-01-20 RESTAURANTE INVENTADO SANTO DOMINGO 1850.00');
INSERT INTO "transactions" VALUES(14,6,1,'2026-01-28','2026-01-28','GASOLINERA FICTICIA SANTIAGO',240000,'debit','DOP',NULL,NULL,'2026-01-28 GASOLINERA FICTICIA SANTIAGO 2400.00');
INSERT INTO "transactions" VALUES(15,6,2,'2026-02-03','2026-02-03','SUPERMERCADO FICTICIO SANTO DOMINGO',312075,'debit','DOP',NULL,NULL,'2026-02-03 SUPERMERCADO FICTICIO SANTO DOMINGO 3120.75');
INSERT INTO "transactions" VALUES(16,6,3,'2026-02-07','2026-02-07','CINE INVENTADO SANTO DOMINGO',64000,'debit','DOP',NULL,NULL,'2026-02-07 CINE INVENTADO SANTO DOMINGO 640.00');
INSERT INTO "transactions" VALUES(17,6,4,'2026-02-04','2026-02-04','TALLER FICTICIO MECANICA',150000,'debit','DOP',NULL,NULL,'2026-02-04 TALLER FICTICIO MECANICA 1500.00');
INSERT INTO "transactions" VALUES(18,6,5,'2026-02-06','2026-02-06','AGENCIA FICTICIA VIAJES PUNTA CANA',4500000,'debit','DOP',NULL,'4722','2026-02-06 AGENCIA FICTICIA VIAJES PUNTA CANA 45000.00');
INSERT INTO "transactions" VALUES(19,6,6,'2026-02-02','2026-02-02','RESTAURANTE COMPARTIDO FICTICIO',300000,'debit','DOP',NULL,'5812','2026-02-02 RESTAURANTE COMPARTIDO FICTICIO 3000.00');
INSERT INTO "transactions" VALUES(20,6,7,'2026-02-09','2026-02-09','ASADOR FICTICIO CUMPLEANOS',520000,'debit','DOP',NULL,'5812','2026-02-09 ASADOR FICTICIO CUMPLEANOS 5200.00');
INSERT INTO "transactions" VALUES(21,6,8,'2026-02-09','2026-02-09','IMPUESTO DGII FICTICIO',300,'debit','DOP',NULL,NULL,'2026-02-09 IMPUESTO DGII FICTICIO 3.00');
INSERT INTO "transactions" VALUES(22,6,9,'2025-12-20','2025-12-20','TIENDA REGALOS FICTICIA',400000,'debit','DOP',NULL,'5947','2025-12-20 TIENDA REGALOS FICTICIA 4000.00');
INSERT INTO "transactions" VALUES(23,6,10,'2025-12-08','2025-12-08','GIMNASIO FICTICIO',250000,'debit','DOP',NULL,'9999','2025-12-08 GIMNASIO FICTICIO 2500.00');
INSERT INTO "transactions" VALUES(24,6,11,'2026-01-08','2026-01-08','GIMNASIO FICTICIO',250000,'debit','DOP',NULL,'9999','2026-01-08 GIMNASIO FICTICIO 2500.00');
INSERT INTO "transactions" VALUES(25,6,12,'2026-02-08','2026-02-08','GIMNASIO FICTICIO',250000,'debit','DOP',NULL,'9999','2026-02-08 GIMNASIO FICTICIO 2500.00');
INSERT INTO "transactions" VALUES(26,7,0,'2025-12-05','2025-12-05','STREAMING FICTICIO',999,'debit','USD',NULL,'4899','2025-12-05 STREAMING FICTICIO 9.99');
INSERT INTO "transactions" VALUES(27,7,1,'2026-01-05','2026-01-05','STREAMING FICTICIO',999,'debit','USD',NULL,'4899','2026-01-05 STREAMING FICTICIO 9.99');
INSERT INTO "transactions" VALUES(28,7,2,'2026-02-05','2026-02-05','STREAMING FICTICIO',1199,'debit','USD',NULL,'4899','2026-02-05 STREAMING FICTICIO 11.99');
INSERT INTO "transactions" VALUES(29,9,0,'2025-12-12','2025-12-12','SU PAGO GRACIAS',600000,'credit','DOP',NULL,NULL,'2025-12-12 SU PAGO GRACIAS 6000.00');
INSERT INTO "transactions" VALUES(30,9,1,'2025-12-06','2025-12-06','FERRETERIA INVENTADA SANTIAGO',980000,'debit','DOP',NULL,NULL,'2025-12-06 FERRETERIA INVENTADA SANTIAGO 9800.00');
INSERT INTO "transactions" VALUES(31,9,2,'2025-12-18','2025-12-18','TIENDA FICTICIA DE ROPA',435000,'debit','DOP',NULL,NULL,'2025-12-18 TIENDA FICTICIA DE ROPA 4350.00');
INSERT INTO "transactions" VALUES(32,10,0,'2026-01-12','2026-01-12','SU PAGO GRACIAS',800000,'credit','DOP',NULL,NULL,'2026-01-12 SU PAGO GRACIAS 8000.00');
INSERT INTO "transactions" VALUES(33,10,1,'2026-01-09','2026-01-09','LIBRERIA INVENTADA SANTO DOMINGO',120000,'debit','DOP',NULL,NULL,'2026-01-09 LIBRERIA INVENTADA SANTO DOMINGO 1200.00');
INSERT INTO "transactions" VALUES(34,10,2,'2026-01-28','2026-01-28','INTERESES FINANCIAMIENTO',28740,'debit','DOP',NULL,NULL,'2026-01-28 INTERESES FINANCIAMIENTO 287.40');
INSERT INTO "transactions" VALUES(35,11,0,'2025-12-15','2025-12-15','DEPOSITO NOMINA EMPRESA INVENTADA',8500000,'credit','DOP',NULL,NULL,'2025-12-15 DEPOSITO NOMINA EMPRESA INVENTADA 85000.00');
INSERT INTO "transactions" VALUES(36,11,1,'2026-01-11','2026-01-11','PAGO TARJETA DE CREDITO FICTICIA',800000,'debit','DOP',NULL,NULL,'2026-01-11 PAGO TARJETA DE CREDITO FICTICIA 8000.00');
INSERT INTO "transactions" VALUES(37,11,2,'2026-01-15','2026-01-15','DEPOSITO NOMINA EMPRESA INVENTADA',8500000,'credit','DOP',NULL,NULL,'2026-01-15 DEPOSITO NOMINA EMPRESA INVENTADA 85000.00');
INSERT INTO "transactions" VALUES(38,11,3,'2026-01-18','2026-01-18','RETIRO CAJERO SANTO DOMINGO',500000,'debit','DOP',NULL,NULL,'2026-01-18 RETIRO CAJERO SANTO DOMINGO 5000.00');
INSERT INTO "transactions" VALUES(39,11,4,'2026-01-20','2026-01-20','MB a 0000000001 PERSONA INVENTADA',300000,'debit','DOP',NULL,NULL,'2026-01-20 MB a 0000000001 PERSONA INVENTADA 3000.00');
INSERT INTO "transactions" VALUES(40,11,5,'2026-01-25','2026-01-25','AUT PAGO 0000000009 PRESTAMO FICTICIO',200000,'debit','DOP',NULL,NULL,'2026-01-25 AUT PAGO 0000000009 PRESTAMO FICTICIO 2000.00');
INSERT INTO "transactions" VALUES(41,11,6,'2026-01-22','2026-01-22','DEPOSITO CLIENTE FICTICIO',1200000,'credit','DOP',NULL,NULL,'2026-01-22 DEPOSITO CLIENTE FICTICIO 12000.00');
INSERT INTO "transactions" VALUES(42,12,0,'2026-02-04','2026-02-04','TOKE DE PERSONA FICTICIA',100000,'credit','DOP',NULL,NULL,'2026-02-04 TOKE DE PERSONA FICTICIA 1000.00');
INSERT INTO "transactions" VALUES(43,12,1,'2026-02-06','2026-02-06','TOKE DE AMIGA INVENTADA',50000,'credit','DOP',NULL,NULL,'2026-02-06 TOKE DE AMIGA INVENTADA 500.00');
INSERT INTO "transactions" VALUES(44,12,2,'2026-02-09','2026-02-09','TRANSF DE CAROLA FICTICIA',376075,'credit','DOP',NULL,NULL,'2026-02-09 TRANSF DE CAROLA FICTICIA 3760.75');
INSERT INTO "transactions" VALUES(45,12,3,'2026-02-12','2026-02-12','DEPOSITO CAMBIO FICTICIO',6370000,'credit','DOP',NULL,NULL,'2026-02-12 DEPOSITO CAMBIO FICTICIO 63700.00');
INSERT INTO "transactions" VALUES(46,13,0,'2026-02-13','2026-02-13','TRANSFERENCIA A PERSONA FICTICIA',100000,'debit','USD',NULL,NULL,'2026-02-13 TRANSFERENCIA A PERSONA FICTICIA 1000.00');
INSERT INTO "transactions" VALUES(47,13,1,'2026-02-14','2026-02-14','TRANSFERENCIA SALDO PERSONA FICTICIA',6167,'debit','USD',NULL,NULL,'2026-02-14 TRANSFERENCIA SALDO PERSONA FICTICIA 61.67');
INSERT INTO "transactions" VALUES(48,14,0,'2025-12-03','2025-12-03','TRANSFERENCIA A CAMBISTA FICTICIO',3155000,'debit','DOP',NULL,NULL,'2025-12-03 TRANSFERENCIA A CAMBISTA FICTICIO 31550.00');
INSERT INTO "transactions" VALUES(49,14,1,'2025-12-10','2025-12-10','DEPOSITO PRIMO FICTICIO',1893000,'credit','DOP',NULL,NULL,'2025-12-10 DEPOSITO PRIMO FICTICIO 18930.00');
INSERT INTO "transactions" VALUES(50,14,2,'2025-12-02','2025-12-02','MB a 0000000066 PEDRO INVERSOR FICTICIO',30000000,'debit','DOP',NULL,NULL,'2025-12-02 MB a 0000000066 PEDRO INVERSOR FICTICIO 300000.00');
INSERT INTO "transactions" VALUES(51,14,3,'2025-12-05','2025-12-05','MB a 0000000077 ANA PRESTAMO FICTICIA',5000000,'debit','DOP',NULL,NULL,'2025-12-05 MB a 0000000077 ANA PRESTAMO FICTICIA 50000.00');
INSERT INTO "transactions" VALUES(52,14,4,'2025-12-15','2025-12-15','MB a 0000000066 PEDRO INVERSOR FICTICIO',10000000,'debit','DOP',NULL,NULL,'2025-12-15 MB a 0000000066 PEDRO INVERSOR FICTICIO 100000.00');
INSERT INTO "transactions" VALUES(53,14,5,'2025-12-18','2025-12-18','MB a 0000000066 PEDRO INVERSOR FICTICIO',150000,'debit','DOP',NULL,NULL,'2025-12-18 MB a 0000000066 PEDRO INVERSOR FICTICIO 1500.00');
INSERT INTO "transactions" VALUES(54,14,6,'2025-12-22','2025-12-22','TRANSF DE PEDRO INVERSOR FICTICIO',900000,'credit','DOP',NULL,NULL,'2025-12-22 TRANSF DE PEDRO INVERSOR FICTICIO 9000.00');
INSERT INTO "transactions" VALUES(55,14,7,'2025-12-26','2025-12-26','TRANSF DE ANA PRESTAMO FICTICIA',5200000,'credit','DOP',NULL,NULL,'2025-12-26 TRANSF DE ANA PRESTAMO FICTICIA 52000.00');
INSERT INTO "transactions" VALUES(56,14,8,'2025-12-29','2025-12-29','TRANSF DE PEDRO INVERSOR FICTICIO',6000000,'credit','DOP',NULL,NULL,'2025-12-29 TRANSF DE PEDRO INVERSOR FICTICIO 60000.00');
INSERT INTO "transactions" VALUES(57,15,0,'2025-12-04','2025-12-04','DEPOSITO CAMBISTA FICTICIO',40000,'credit','USD',NULL,NULL,'2025-12-04 DEPOSITO CAMBISTA FICTICIO 400.00');
INSERT INTO "transactions" VALUES(58,15,1,'2025-12-11','2025-12-11','ENVIO A PRIMO FICTICIO',10000,'debit','USD',NULL,NULL,'2025-12-11 ENVIO A PRIMO FICTICIO 100.00');
INSERT INTO "transactions" VALUES(59,16,0,'2025-12-05','2025-12-05','TELFIC PAGO',150000,'debit','DOP',NULL,'4814','2025-12-05 TELFIC PAGO 1500.00');
INSERT INTO "transactions" VALUES(60,16,1,'2026-01-06','2026-01-06','TELFIC IBANKING',90000,'debit','DOP',NULL,'4814','2026-01-06 TELFIC IBANKING 900.00');
INSERT INTO "transactions" VALUES(61,16,2,'2026-01-20','2026-01-20','TELFIC P',60000,'debit','DOP',NULL,'4814','2026-01-20 TELFIC P 600.00');
INSERT INTO "transactions" VALUES(62,16,3,'2026-02-04','2026-02-04','TELFIC WB',150000,'debit','DOP',NULL,'4814','2026-02-04 TELFIC WB 1500.00');
INSERT INTO "transactions" VALUES(63,16,4,'2026-01-10','2026-01-10','TELFIC RECARGA 8095550000',30000,'debit','DOP',NULL,'4814','2026-01-10 TELFIC RECARGA 8095550000 300.00');
INSERT INTO "transactions" VALUES(64,16,5,'2026-01-18','2026-01-18','TELFIC AGORA MALL',750000,'debit','DOP',NULL,'4814','2026-01-18 TELFIC AGORA MALL 7500.00');
INSERT INTO "transactions" VALUES(65,16,6,'2025-12-09','2025-12-09','AGUA FICTICIA PAGO',45000,'debit','DOP',NULL,'4900','2025-12-09 AGUA FICTICIA PAGO 450.00');
INSERT INTO "transactions" VALUES(66,16,7,'2026-01-09','2026-01-09','AGUA FICTICIA PAGO',45000,'debit','DOP',NULL,'4900','2026-01-09 AGUA FICTICIA PAGO 450.00');
INSERT INTO "transactions" VALUES(67,16,8,'2026-02-09','2026-02-09','AGUA FICTICIA PAGO',45000,'debit','DOP',NULL,'4900','2026-02-09 AGUA FICTICIA PAGO 450.00');
INSERT INTO "transactions" VALUES(68,16,9,'2025-12-01','2025-12-01','ALQUILER FICTICIO',2500000,'debit','DOP',NULL,'6513','2025-12-01 ALQUILER FICTICIO 25000.00');
INSERT INTO "transactions" VALUES(69,16,10,'2026-01-01','2026-01-01','ALQUILER FICTICIO',2500000,'debit','DOP',NULL,'6513','2026-01-01 ALQUILER FICTICIO 25000.00');
INSERT INTO "transactions" VALUES(70,16,11,'2026-02-01','2026-02-01','ALQUILER FICTICIO',2500000,'debit','DOP',NULL,'6513','2026-02-01 ALQUILER FICTICIO 25000.00');
INSERT INTO "transactions" VALUES(71,16,12,'2026-01-15','2026-01-15','SEGURO HOGAR FICTICIO',480000,'debit','DOP',NULL,'6300','2026-01-15 SEGURO HOGAR FICTICIO 4800.00');
INSERT INTO "transactions" VALUES(72,16,13,'2026-01-20','2026-01-20','MARBETE FICTICIO',340000,'debit','DOP',NULL,'9311','2026-01-20 MARBETE FICTICIO 3400.00');
INSERT INTO "transactions" VALUES(73,17,0,'2025-12-10','2025-12-10','AUT PAGO 0000000088 REF 1',1200000,'debit','DOP',NULL,NULL,'2025-12-10 AUT PAGO 0000000088 REF 1 12000.00');
INSERT INTO "transactions" VALUES(74,17,1,'2026-01-10','2026-01-10','AUT PAGO 0000000088 REF 2',1200000,'debit','DOP',NULL,NULL,'2026-01-10 AUT PAGO 0000000088 REF 2 12000.00');
INSERT INTO "transactions" VALUES(75,17,2,'2026-01-28','2026-01-28','AUT PAGO 0000000088 REF 3',3000000,'debit','DOP',NULL,NULL,'2026-01-28 AUT PAGO 0000000088 REF 3 30000.00');
INSERT INTO "transactions" VALUES(76,17,3,'2026-02-10','2026-02-10','AUT PAGO 0000000088 REF 4',1200000,'debit','DOP',NULL,NULL,'2026-02-10 AUT PAGO 0000000088 REF 4 12000.00');
INSERT INTO "transactions" VALUES(77,18,0,'2026-01-08','2026-01-08','MB DESDE 0000000123 COMPRADOR P2P FICTICIO',1200000,'credit','DOP',NULL,NULL,'2026-01-08 MB DESDE 0000000123 COMPRADOR P2P FICTICIO 12000.00');
INSERT INTO "transactions" VALUES(78,18,1,'2026-01-16','2026-01-16','TRANSFERENCIA RECIBIDA COMPRADORA P2P FICTICIA',850000,'credit','DOP',NULL,NULL,'2026-01-16 TRANSFERENCIA RECIBIDA COMPRADORA P2P FICTICIA 8500.00');
INSERT INTO "transactions" VALUES(79,18,2,'2026-01-27','2026-01-27','LBTR EMPRESA FICTICIA P2P',2000000,'credit','DOP',NULL,NULL,'2026-01-27 LBTR EMPRESA FICTICIA P2P 20000.00');
INSERT INTO "transactions" VALUES(80,18,3,'2026-01-20','2026-01-20','DEPOSITO REGALO FICTICIO',100000,'credit','DOP',NULL,NULL,'2026-01-20 DEPOSITO REGALO FICTICIO 1000.00');
INSERT INTO "transactions" VALUES(81,19,0,'2025-11-10','2025-11-10','COMPRA FICTICIA BANRESERVAS_CUENTA',10000,'debit','DOP',NULL,NULL,'2025-11-10 COMPRA FICTICIA BANRESERVAS_CUENTA');
INSERT INTO "transactions" VALUES(82,20,0,'2025-11-11','2025-11-11','COMPRA FICTICIA BANRESERVAS_PARCIAL',10000,'debit','DOP',NULL,NULL,'2025-11-11 COMPRA FICTICIA BANRESERVAS_PARCIAL');
INSERT INTO "transactions" VALUES(83,21,0,'2025-11-12','2025-11-12','COMPRA FICTICIA BHD_AHORRO_PARCIAL',10000,'debit','DOP',NULL,NULL,'2025-11-12 COMPRA FICTICIA BHD_AHORRO_PARCIAL');
INSERT INTO "transactions" VALUES(84,22,0,'2025-11-13','2025-11-13','COMPRA FICTICIA POPULAR_CUENTA',10000,'debit','DOP',NULL,NULL,'2025-11-13 COMPRA FICTICIA POPULAR_CUENTA');
INSERT INTO "transactions" VALUES(85,23,0,'2025-11-14','2025-11-14','COMPRA FICTICIA POPULAR_HISTORICO',10000,'debit','DOP',NULL,NULL,'2025-11-14 COMPRA FICTICIA POPULAR_HISTORICO');
INSERT INTO "transactions" VALUES(86,24,0,'2025-11-15','2025-11-15','COMPRA FICTICIA POPULAR_WEB',10000,'debit','DOP',NULL,NULL,'2025-11-15 COMPRA FICTICIA POPULAR_WEB');
CREATE INDEX documents_sha256 ON documents(sha256);
CREATE UNIQUE INDEX statements_unique_period
    ON statements (account_id, COALESCE(card_id, 0), currency, period_end)
    WHERE parser NOT IN ('popular_web', 'banreservas_parcial', 'bhd_ahorro_parcial');
CREATE UNIQUE INDEX statements_unique_printout
    ON statements (
        account_id, currency, COALESCE(period_start, ''), period_end,
        COALESCE(closing_balance_cents, 0), COALESCE(printed_debits_cents, 0),
        COALESCE(printed_credits_cents, 0), COALESCE(transaction_count, 0)
    )
    WHERE parser IN ('popular_web', 'banreservas_parcial', 'bhd_ahorro_parcial');
CREATE INDEX change_log_at ON change_log(at);
CREATE INDEX change_log_undoes ON change_log(undoes);
CREATE INDEX change_log_rows_key ON change_log_rows(row_key);
CREATE INDEX change_log_fingerprints_fp ON change_log_fingerprints(fingerprint);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('categories',41);
INSERT INTO "sqlite_sequence" VALUES('links',11);
INSERT INTO "sqlite_sequence" VALUES('link_manual',1);
INSERT INTO "sqlite_sequence" VALUES('cash_entries',2);
INSERT INTO "sqlite_sequence" VALUES('change_log',38);
INSERT INTO "sqlite_sequence" VALUES('budget_caps',27);
INSERT INTO "sqlite_sequence" VALUES('reserve_dismissals',3);
COMMIT;
PRAGMA user_version = 17;
